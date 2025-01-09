import os
import sys
from datetime import datetime
from pathlib import Path

import jsonpickle
from PySide6.QtCore import QTimer, Qt, QSortFilterProxyModel, QModelIndex
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QTableView, QMenu, QPushButton, \
    QLineEdit, QDialog, QHeaderView, QLabel, QSizePolicy

from Database import Database
from VideoFile import VideoFile
from Ui.AddFilesDialog import AddFilesDialog
from Ui.FilterWidget import FilterWidget
from Ui.TagListModel import TagListModel
from Ui.FileSortFilterProxyModel import FileSortFilterProxyModel
from Ui.StarRatingWidget import StarRatingWidget
from Ui.FileListModel import FileListModel
from VlcPlayerConnector import VlcPlayerConnector


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.selected_file: VideoFile | None = None

        self.setWindowTitle("Video Tagger")
        self.setGeometry(100, 100, 800, 600)

        self.vlc = VlcPlayerConnector()

        self.database = Database('VideoTagger.db')

        self.file_list_model: FileListModel = FileListModel([])
        self.file_list_filter_model: FileSortFilterProxyModel = FileSortFilterProxyModel()
        self.tag_list_model: TagListModel = TagListModel({})

        self._init_ui()

        self.load_files()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_vlc_status)
        self.timer.start(1000)

    def _init_ui(self):
        self.central_widget = QWidget()
        self.main_layout = QHBoxLayout()
        self.central_widget.setLayout(self.main_layout)
        self.setCentralWidget(self.central_widget)

        self.left_layout = QVBoxLayout()
        self.main_layout.addLayout(self.left_layout)

        self.filter_widget = FilterWidget(self)
        self.left_layout.addWidget(self.filter_widget)

        self.file_list = QTableView()
        self.file_list.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.file_list.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.file_list.verticalHeader().hide()
        self.file_list.setShowGrid(False)
        self.file_list.setSortingEnabled(True)
        self.file_list.horizontalHeader().setSectionsClickable(True)

        self.file_list_model = FileListModel([])
        self.file_list_filter_model = FileSortFilterProxyModel()
        self.file_list_filter_model.setSourceModel(self.file_list_model)
        self.file_list_filter_model.filter_changed.connect(self.update_file_list_status)
        self.file_list.setModel(self.file_list_filter_model)
        self.file_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.file_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.file_list.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.file_list.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.file_list.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.file_list.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.filter_widget.filter_changed.connect(self.file_list_filter_model.set_filter)

        self.left_layout.addWidget(self.file_list)

        self.file_list.selectionModel().selectionChanged.connect(self.on_file_selected)

        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.file_list_context_menu = QMenu(self)

        for i, header in list(enumerate(self.file_list_model.horizontal_header_labels))[1:]:
            action = QAction(header, self.file_list)
            column_visible = self.database.get_setting(f'column_visibility_{header}', str(True)) == 'True'
            action.setCheckable(True)
            action.setChecked(column_visible)
            self.file_list.setColumnHidden(i, not column_visible)
            action.toggled.connect(lambda checked, col=i: self.toggle_column_visibility(col, checked))
            self.file_list_context_menu.addAction(action)

        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self.show_file_list_context_menu)

        self.database_layout = QHBoxLayout()
        self.left_layout.addLayout(self.database_layout)

        self.file_list_status_label = QLabel()
        self.database_layout.addWidget(self.file_list_status_label)
        self.file_list_status_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))

        self.add_files_button = QPushButton("Add Files")
        self.add_files_button.clicked.connect(self.show_add_files_dialog)
        self.database_layout.addWidget(self.add_files_button)

        self.right_layout = QVBoxLayout()
        self.main_layout.addLayout(self.right_layout)

        self.file_path_text = QLineEdit()
        self.file_path_text.setReadOnly(True)
        self.right_layout.addWidget(self.file_path_text)

        self.tag_list = QTableView()
        self.tag_list.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.tag_list.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.tag_list.verticalHeader().hide()
        self.tag_list.setShowGrid(False)
        self.tag_list.setSortingEnabled(True)
        self.tag_list.horizontalHeader().setSectionsClickable(True)
        self.right_layout.addWidget(self.tag_list)
        self.load_tags()
        self.tag_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tag_list.customContextMenuRequested.connect(self.show_tag_list_context_menu)

        self.add_tag_layout = QHBoxLayout()
        self.right_layout.addLayout(self.add_tag_layout)
        self.add_tag_edit = QLineEdit()
        self.add_tag_edit.setPlaceholderText('Add Tag')
        self.add_tag_edit.returnPressed.connect(self.add_tag)
        self.add_tag_layout.addWidget(self.add_tag_edit)
        self.add_tag_button = QPushButton("Add")
        self.add_tag_button.clicked.connect(self.add_tag)
        self.add_tag_layout.addWidget(self.add_tag_button)

        self.rating_widget = StarRatingWidget(20, self)
        self.rating_widget.rating_changed.connect(self.set_rating)
        self.right_layout.addWidget(self.rating_widget)

    def show_add_files_dialog(self):
        dialog = AddFilesDialog(self.database, self)
        dialog.exec()
        if dialog.result() == QDialog.DialogCode.Accepted:
            for file_path in dialog.found_files:
                try:
                    size = os.path.getsize(file_path)
                    date_modified = datetime.fromtimestamp(os.path.getmtime(file_path))
                    self.database.add_file(VideoFile(-1, file_path, size, date_modified))
                except Exception as e:
                    print(e)
            self.load_files()

    def add_tag(self):
        tag = self.add_tag_edit.text()
        self.add_tag_edit.clear()
        self.tag_list_model.set_tag(tag)
        if self.selected_file is not None:
            self.database.set_tag(self.selected_file.id, tag)
            self.selected_file.tags.add(tag)
        else:
            self.database.add_tag(tag)

    def load_files(self):
        files = self.database.get_files()

        self.file_list_model.set_files(files)

        if files:
            common_path = os.path.commonpath([file.path for file in files])
            min_rating = 5
            max_rating = 0
            min_size = sys.maxsize
            max_size = 0
            min_date = datetime.max
            max_date = datetime.min
            for file in files:
                min_rating = min(min_rating, file.rating or 0)
                max_rating = max(max_rating, file.rating or 0)
                min_size = min(min_size, file.size)
                max_size = max(max_size, file.size)
                min_date = min(min_date, file.date_modified)
                max_date = max(max_date, file.date_modified)
            self.filter_widget.path = common_path
            self.filter_widget.rating = (min_rating, max_rating)
            self.filter_widget.size = (min_size, max_size)
            self.filter_widget.date = (min_date, max_date)
        else:
            self.filter_widget.path = ''
            self.filter_widget.rating = (0, 5)
            self.filter_widget.size = (0, sys.maxsize)
            self.filter_widget.date = (datetime.min, datetime.max)

        self.backup_database()

    def load_tags(self):
        tags = self.database.get_tags()
        self.tag_list_model = TagListModel(tags)
        proxy_model = QSortFilterProxyModel()
        proxy_model.setSourceModel(self.tag_list_model)
        self.tag_list.setModel(proxy_model)

        self.tag_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tag_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tag_list.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tag_list.sortByColumn(1, Qt.SortOrder.AscendingOrder)

        self.tag_list_model.tag_set.connect(self.database.set_tag)
        self.tag_list_model.tag_removed.connect(self.database.remove_tag)

    def show_tag_list_context_menu(self, pos):
        index = self.tag_list.indexAt(pos)
        if not index.isValid():
            return
        tag_name = index.sibling(index.row(), 1).data()
        menu = QMenu(self)
        delete_action = QAction("Delete Tag", self)
        delete_action.triggered.connect(lambda: self.delete_tag(tag_name))
        menu.addAction(delete_action)
        menu.exec(self.tag_list.viewport().mapToGlobal(pos))

    def delete_tag(self, tag_name: str):
        self.database.delete_tag(tag_name)
        index = self.tag_list_model.index(self.tag_list_model.tag_names.index(tag_name), 0)
        self.tag_list_model.beginRemoveRows(QModelIndex(), index.row(), index.row())
        self.tag_list_model.tag_names.remove(tag_name)
        self.tag_list_model.tags.pop(tag_name)
        self.tag_list_model.endRemoveRows()

    def on_file_selected(self, selected, _):
        indexes = selected.indexes()
        if indexes:
            self.selected_file = indexes[0].data(Qt.ItemDataRole.DisplayRole.UserRole)
            self.file_path_text.setText(self.selected_file.path)
            self.tag_list_model.current_file = self.selected_file
            self.rating_widget.rating = self.selected_file.rating
            self.vlc.play_video(self.selected_file.path)
        else:
            self.selected_file = None
            self.file_path_text.clear()
            self.tag_list_model.current_file = None
            self.rating_widget.rating = None
            self.vlc.stop_video()
        if self.file_list_filter_model:
            self.file_list_filter_model.current_file = self.selected_file

    def update_vlc_status(self):
        self.vlc.update_status()

    def set_rating(self, rating):
        if self.selected_file is not None:
            self.database.set_rating(self.selected_file.id, rating)
            self.selected_file.rating = rating
            self.on_current_file_modified()

    def on_current_file_modified(self):
        index = self.selected_file_index()
        if index and index.isValid():
            self.file_list_model.dataChanged.emit(self.file_list_model.index(index.row(), 0),
                                                  self.file_list_model.index(index.row(),
                                                                             self.file_list_model.columnCount() - 1))

    def show_file_list_context_menu(self, pos):
        self.file_list_context_menu.exec(self.file_list.viewport().mapToGlobal(pos))

    def toggle_column_visibility(self, column, visible):
        self.file_list.setColumnHidden(column, not visible)
        for action in self.file_list_context_menu.actions():
            self.database.set_setting(f'column_visibility_{action.text()}', str(action.isChecked()))

    def close_event(self, event):
        self.vlc.close()
        event.accept()

    def selected_file_index(self):
        if self.file_list_model is None:
            return QModelIndex()
        return self.file_list_model.index(self.file_list_model.files.index(self.selected_file), 0)

    def backup_database(self):
        data = {'Files': self.file_list_model.files, 'Settings': self.database.get_settings()}
        Path('../backup').mkdir(exist_ok=True)
        with open(f'backup/{datetime.now().isoformat()}.json', 'w', encoding='utf-8') as f:
            f.write(jsonpickle.encode(data, unpicklable=False, indent=4))

    def update_file_list_status(self):
        self.file_list_status_label.setText(f'Showing {self.file_list_filter_model.rowCount()} '
                                            f'of {self.file_list_model.rowCount()} files')
