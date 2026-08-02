import os
import sys
from datetime import datetime
from pathlib import Path

import jsonpickle
from PySide6.QtCore import QTimer, Qt, QSortFilterProxyModel, QModelIndex, Signal, QRegularExpression
from PySide6.QtGui import QAction, QKeyEvent, QWindow
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QTableView, QMenu, QPushButton, \
    QLineEdit, QDialog, QHeaderView, QInputDialog, QLabel, QSizePolicy, QMessageBox

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
    selected_file_changed = Signal(VideoFile)
    selected_file_modified = Signal(VideoFile)
    playing_file_changed = Signal(VideoFile)

    def __init__(self):
        super().__init__()

        self.selected_file: VideoFile | None = None
        self.playing_file: VideoFile | None = None
        self.copied_tags: set[str] = set()

        self.setWindowTitle("Video Tagger")
        self.setGeometry(100, 100, 800, 600)

        self.vlc = VlcPlayerConnector()

        self.database = Database('VideoTagger.db')

        self.file_list_model: FileListModel = FileListModel([])
        self.file_list_filter_model: FileSortFilterProxyModel = FileSortFilterProxyModel()
        self.tag_list_model: TagListModel = TagListModel({})
        self.tag_list_filter_model: QSortFilterProxyModel = QSortFilterProxyModel()
        self.selected_file_changed.connect(self.tag_list_model.set_current_file)

        self._init_ui()

        self.load_files()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_vlc_status)
        self.timer.start(1000)

        QApplication.instance().installEventFilter(self)

    def _init_ui(self):
        self.central_widget = QWidget()
        self.main_layout = QHBoxLayout()
        self.central_widget.setLayout(self.main_layout)
        self.setCentralWidget(self.central_widget)

        self.left_layout = QVBoxLayout()
        self.main_layout.addLayout(self.left_layout)

        self.filter_widget = FilterWidget(self.database.get_setting('filter_expanded', 'True') == 'True',
                                          'File List Filter', lambda: self.tag_list_model.tag_names, self)
        self.filter_widget.toggled.connect(lambda expanded: self.database.set_setting('filter_expanded', str(expanded)))
        self.left_layout.addWidget(self.filter_widget)

        self.file_list = QTableView()
        self.file_list.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.file_list.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.file_list.verticalHeader().hide()
        self.file_list.setShowGrid(False)
        self.file_list.setSortingEnabled(True)
        self.file_list.horizontalHeader().setSectionsClickable(True)

        self.file_list_model = FileListModel([])
        self.file_list_filter_model = FileSortFilterProxyModel()
        self.file_list_filter_model.setSourceModel(self.file_list_model)
        self.file_list_filter_model.filter_changed.connect(self.update_file_list_status)
        self.selected_file_changed.connect(self.file_list_filter_model.set_selected_file)
        self.selected_file_modified.connect(self.file_list_model.on_file_modified)
        self.playing_file_changed.connect(self.file_list_model.set_playing_file)
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
        self.file_list.selectionModel().selectionChanged.connect(self.on_file_selection_changed)
        self.file_list.doubleClicked.connect(self.play_selected_file)
        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self.show_file_list_context_menu)

        self.file_list_header = self.file_list.horizontalHeader()
        self.file_list_header.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.file_list_header_context_menu = QMenu(self)

        for i, header in list(enumerate(self.file_list_model.horizontal_header_labels))[1:]:
            action = QAction(header, self.file_list)
            column_visible = self.database.get_setting(f'column_visibility_{header}', str(True)) == 'True'
            action.setCheckable(True)
            action.setChecked(column_visible)
            self.file_list.setColumnHidden(i, not column_visible)
            action.toggled.connect(lambda checked, col=i: self.toggle_column_visibility(col, checked))
            self.file_list_header_context_menu.addAction(action)

        self.file_list_header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_list_header.customContextMenuRequested.connect(self.show_file_list_context_menu)

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

        self.copy_tags_action = QAction('Copy Tags', self)
        self.copy_tags_action.setShortcut('Ctrl+C')
        self.copy_tags_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.copy_tags_action.triggered.connect(self.copy_tags)
        self.addAction(self.copy_tags_action)

        self.paste_tags_action = QAction('Paste Tags', self)
        self.paste_tags_action.setShortcut('Ctrl+V')
        self.paste_tags_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.paste_tags_action.triggered.connect(self.paste_tags)
        self.addAction(self.paste_tags_action)

        self.add_tag_layout = QHBoxLayout()
        self.right_layout.addLayout(self.add_tag_layout)
        self.add_tag_edit = QLineEdit()
        self.add_tag_edit.setPlaceholderText('Add Tag')
        self.add_tag_edit.returnPressed.connect(self.add_tag)
        self.add_tag_edit.textChanged.connect(self.on_add_tag_text_changed)
        self.add_tag_layout.addWidget(self.add_tag_edit)
        self.add_tag_button = QPushButton("Add")
        self.add_tag_button.clicked.connect(self.add_tag)
        self.add_tag_layout.addWidget(self.add_tag_button)

        self.rating_widget = StarRatingWidget(20, self)
        self.rating_widget.rating_changed.connect(self.set_rating)
        self.right_layout.addWidget(self.rating_widget)

    def eventFilter(self, obj, event):
        if not isinstance(obj, QWindow):
            return super().eventFilter(obj, event)
        if event.type() == QKeyEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Space:
                self.vlc.pause_video()
            elif key == Qt.Key_Left:
                self.vlc.seek_relative(-5)
            elif key == Qt.Key_Right:
                self.vlc.seek_relative(5)
            elif key == Qt.Key_Up:
                self.vlc.set_volume_relative(1)
            elif key == Qt.Key_Down:
                self.vlc.set_volume_relative(-1)

        return super().eventFilter(obj, event)

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
            self._emit_selected_file_modified()
        else:
            self.database.add_tag(tag)

    def on_add_tag_text_changed(self, text):
        self.tag_list_filter_model.setFilterRegularExpression(QRegularExpression(text, QRegularExpression.PatternOption.CaseInsensitiveOption))

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
            min_size = max(min_size, 10_000_000)
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
        self.tag_list_filter_model = QSortFilterProxyModel()
        self.tag_list_filter_model.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.tag_list_filter_model.setFilterKeyColumn(1)
        self.tag_list_filter_model.setSourceModel(self.tag_list_model)
        self.tag_list.setModel(self.tag_list_filter_model)

        self.tag_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tag_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tag_list.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tag_list.sortByColumn(1, Qt.SortOrder.AscendingOrder)

        self.tag_list_model.tag_set.connect(self.database.set_tag)
        self.tag_list_model.tag_set.connect(self._on_tag_set)
        self.tag_list_model.tag_removed.connect(self.database.remove_tag)
        self.tag_list_model.tag_removed.connect(self._on_tag_removed)

    def show_tag_list_context_menu(self, pos):
        index = self.tag_list.indexAt(pos)
        if not index.isValid():
            return
        tag_name = index.sibling(index.row(), 1).data()
        menu = QMenu(self)

        add_tag_to_whitelist_action = QAction("Whitelist", self)
        is_in_whitelist = tag_name in self.filter_widget.tags_whitelist
        add_tag_to_whitelist_action.triggered.connect(
            lambda: self.filter_widget.set_tag_in_whitelist(tag_name, not is_in_whitelist))
        add_tag_to_whitelist_action.setCheckable(True)
        add_tag_to_whitelist_action.setChecked(is_in_whitelist)
        menu.addAction(add_tag_to_whitelist_action)

        add_tag_to_blacklist_action = QAction("Blacklist", self)
        is_in_blacklist = tag_name in self.filter_widget.tags_blacklist
        add_tag_to_blacklist_action.triggered.connect(
            lambda: self.filter_widget.set_tag_in_blacklist(tag_name, not is_in_blacklist))
        add_tag_to_blacklist_action.setCheckable(True)
        add_tag_to_blacklist_action.setChecked(is_in_blacklist)
        menu.addAction(add_tag_to_blacklist_action)

        menu.addSeparator()

        rename_action = QAction("Rename Tag", self)
        rename_action.triggered.connect(lambda: self.rename_tag(tag_name))
        menu.addAction(rename_action)

        delete_action = QAction("Delete Tag", self)
        delete_action.triggered.connect(lambda: self.delete_tag_question(tag_name))
        menu.addAction(delete_action)

        menu.addSeparator()

        copy_tags_action = menu.addAction('Copy Tags')
        copy_tags_action.setEnabled(self.selected_file is not None)
        copy_tags_action.triggered.connect(self.copy_tags)

        paste_tags_action = menu.addAction('Paste Tags')
        paste_tags_action.setEnabled(self.selected_file is not None and bool(self.copied_tags))
        paste_tags_action.triggered.connect(self.paste_tags)

        clear_tags_action = menu.addAction('Clear Tags')
        clear_tags_action.setEnabled(self.selected_file is not None and bool(self.selected_file.tags))
        clear_tags_action.triggered.connect(self.clear_tags)

        menu.addSeparator()

        menu.exec(self.tag_list.viewport().mapToGlobal(pos))

    def copy_tags(self):
        selected_files = self._get_selected_files()
        if not selected_files and self.selected_file is not None:
            selected_files = [self.selected_file]
        self.copied_tags = {tag for file in selected_files for tag in file.tags}
        self.tag_list_model.set_copied_tags(self.copied_tags)
        self.paste_tags_action.setEnabled(bool(self.copied_tags) and self.selected_file is not None)

    def paste_tags(self):
        selected_files = self._get_selected_files()
        if not selected_files and self.selected_file is not None:
            selected_files = [self.selected_file]
        if not selected_files:
            return

        modified = False
        for file in selected_files:
            for tag in self.copied_tags - file.tags:
                self.database.set_tag(file.id, tag)
                file.tags.add(tag)
                self.tag_list_model.tags[tag] += 1
                modified = True
            if modified:
                self.file_list_model.on_file_modified(file)

        if modified:
            self.tag_list_model.dataChanged.emit(self.tag_list_model.index(0, 0),
                                                 self.tag_list_model.index(self.tag_list_model.rowCount() - 1,
                                                                           self.tag_list_model.columnCount() - 1))
            self._emit_selected_file_modified()

    def clear_tags(self):
        selected_files = self._get_selected_files()
        if not selected_files:
            return

        modified = False
        for file in selected_files:
            for tag in file.tags.copy():
                self.database.remove_tag(file.id, tag)
                file.tags.remove(tag)
                self.tag_list_model.tags[tag] -= 1
                modified = True
            if modified:
                self.file_list_model.on_file_modified(file)

        if modified:
            self.tag_list_model.set_selected_files(selected_files)
            self._emit_selected_file_modified()

    def _on_tag_set(self, file_id: int, _tag: str):
        self._on_tag_changed(file_id)

    def _on_tag_removed(self, file_id: int, _tag: str):
        self._on_tag_changed(file_id)

    def _on_tag_changed(self, file_id: int):
        for file in self.file_list_model.files:
            if file.id == file_id:
                self.file_list_model.on_file_modified(file)
                if file is self.selected_file:
                    self._emit_selected_file_modified()
                return

    def rename_tag(self, old_name: str):
        new_name, ok = QInputDialog.getText(self, 'Rename Tag', 'New tag name:', text=old_name)
        if ok and new_name and new_name != old_name:
            self.database.rename_tag(old_name, new_name)
            self.tag_list_model.update_tag_name(old_name, new_name)
            self.file_list_model.on_tag_renamed(old_name, new_name)

    def delete_tag_question(self, tag_name: str):
        tag_count = self.tag_list_model.tags[tag_name]
        message = f'Delete tag "{tag_name}" with {tag_count} files?'
        response = QMessageBox.question(self, 'Delete Tag', message,
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)
        if response == QMessageBox.StandardButton.Yes:
            self.delete_tag(tag_name)

    def delete_tag(self, tag_name: str):
        self.database.delete_tag(tag_name)
        index = self.tag_list_model.index(self.tag_list_model.tag_names.index(tag_name), 0)
        self.tag_list_model.beginRemoveRows(QModelIndex(), index.row(), index.row())
        self.tag_list_model.tag_names.remove(tag_name)
        self.tag_list_model.tags.pop(tag_name)
        self.tag_list_model.endRemoveRows()

    def on_file_selected(self, selected, _):
        current_index = self.file_list.selectionModel().currentIndex()
        if current_index.isValid():
            self.set_selected_file(current_index.data(Qt.ItemDataRole.DisplayRole.UserRole))
        else:
            self.set_selected_file(None)

    def on_file_selection_changed(self, _, __):
        self.tag_list_model.set_selected_files(self._get_selected_files())

    def play_selected_file(self):
        self.playing_file = self.selected_file
        self.playing_file_changed.emit(self.playing_file)
        if self.playing_file:
            self.vlc.play_video(self.playing_file.path)
        else:
            self.vlc.stop_video()

    def update_vlc_status(self):
        self.vlc.update_status()

    def set_rating(self, rating):
        selected_files = self._get_selected_files()
        if not selected_files and self.selected_file is not None:
            selected_files = [self.selected_file]
        for file in selected_files:
            self.database.set_rating(file.id, rating)
            file.rating = rating
            self.file_list_model.on_file_modified(file)

        if self.selected_file is not None and self.selected_file in selected_files:
            self._emit_selected_file_modified()

    def _emit_selected_file_modified(self):
        self.selected_file_modified.emit(self.selected_file)

    @staticmethod
    def get_available_tags_for_files(files: list[VideoFile]) -> list[str]:
        return sorted({tag for file in files for tag in file.tags})

    def _get_selected_files(self) -> list[VideoFile]:
        selected_files: list[VideoFile] = []
        for index in self.file_list.selectionModel().selectedRows():
            file = index.data(Qt.ItemDataRole.DisplayRole.UserRole)
            if file is not None and file not in selected_files:
                selected_files.append(file)
        return selected_files

    def _apply_tag_to_selected_files(self, tag: str, add_tag: bool):
        selected_files = self._get_selected_files()
        if not selected_files:
            return

        for file in selected_files:
            if add_tag:
                self.database.set_tag(file.id, tag)
                file.tags.add(tag)
            else:
                self.database.remove_tag(file.id, tag)
                file.tags.discard(tag)
            self.file_list_model.on_file_modified(file)

        if self.selected_file is not None and self.selected_file in selected_files:
            self._emit_selected_file_modified()

    def _apply_rating_to_selected_files(self, rating: int | None):
        selected_files = self._get_selected_files()
        if not selected_files:
            return

        for file in selected_files:
            self.database.set_rating(file.id, rating)
            file.rating = rating
            self.file_list_model.on_file_modified(file)

        if self.selected_file is not None and self.selected_file in selected_files:
            self._emit_selected_file_modified()

    def show_file_list_context_menu(self, pos):
        if self.file_list_header.underMouse():
            self.file_list_header_context_menu.exec(self.file_list.viewport().mapToGlobal(pos))
            return

        selected_files = self._get_selected_files()
        menu = QMenu(self)

        tag_all_action = QAction('Tag all', self)
        tag_all_action.setEnabled(bool(selected_files))
        tag_all_submenu = QMenu(self)
        tag_all_action.setMenu(tag_all_submenu)
        for tag in sorted(self.tag_list_model.tag_names):
            tag_action = QAction(tag, self)
            tag_action.triggered.connect(lambda checked=False, tag=tag: self._apply_tag_to_selected_files(tag, True))
            tag_all_submenu.addAction(tag_action)
        menu.addAction(tag_all_action)

        untag_all_action = QAction('Untag all', self)
        untag_all_action.setEnabled(bool(selected_files))
        untag_all_submenu = QMenu(self)
        untag_all_action.setMenu(untag_all_submenu)
        for tag in sorted(self.get_available_tags_for_files(selected_files)):
            tag_action = QAction(tag, self)
            tag_action.triggered.connect(lambda checked=False, tag=tag: self._apply_tag_to_selected_files(tag, False))
            untag_all_submenu.addAction(tag_action)
        menu.addAction(untag_all_action)

        menu.addSeparator()

        rate_all_action = QAction('Rate all', self)
        rate_all_action.setEnabled(bool(selected_files))
        rate_all_submenu = QMenu(self)
        rate_all_action.setMenu(rate_all_submenu)
        for rating in [None, 1, 2, 3, 4, 5]:
            label = 'Clear' if rating is None else f'{rating} star' + ('' if rating == 1 else 's')
            rating_action = QAction(label, self)
            rating_action.triggered.connect(lambda checked=False, rating=rating: self._apply_rating_to_selected_files(rating))
            rate_all_submenu.addAction(rating_action)
        menu.addAction(rate_all_action)

        menu.addSeparator()

        copy_tags_action = QAction('Copy Tags', self)
        copy_tags_action.setEnabled(bool(selected_files))
        copy_tags_action.triggered.connect(self.copy_tags)
        menu.addAction(copy_tags_action)

        paste_tags_action = QAction('Paste Tags', self)
        paste_tags_action.setEnabled(bool(selected_files) and bool(self.copied_tags))
        paste_tags_action.triggered.connect(self.paste_tags)
        menu.addAction(paste_tags_action)

        clear_tags_action = QAction('Clear Tags', self)
        clear_tags_action.setEnabled(any(file.tags for file in selected_files))
        clear_tags_action.triggered.connect(self.clear_tags)
        menu.addAction(clear_tags_action)

        menu.exec(self.file_list.viewport().mapToGlobal(pos))

    def toggle_column_visibility(self, column, visible):
        self.file_list.setColumnHidden(column, not visible)
        for action in self.file_list_header_context_menu.actions():
            self.database.set_setting(f'column_visibility_{action.text()}', str(action.isChecked()))

    def close_event(self, event):
        self.vlc.close()
        event.accept()

    def backup_database(self):
        data = {'Files': self.file_list_model.files, 'Settings': self.database.get_settings()}

        Path('.backup').mkdir(exist_ok=True)
        with open(f'.backup/{datetime.now().isoformat()}.json', 'w', encoding='utf-8') as f:
            f.write(jsonpickle.encode(data, unpicklable=False, indent=4))

    def update_file_list_status(self):
        self.file_list_status_label.setText(f'Showing {self.file_list_filter_model.rowCount()} '
                                            f'of {self.file_list_model.rowCount()} files')

    def set_selected_file(self, file: VideoFile):
        if self.selected_file != file:
            if file is not None:
                self.file_path_text.setText(file.path)
                self.tag_list_model.current_file = file
                selected_files = self._get_selected_files()
                ratings = {selected_file.rating for selected_file in selected_files}
                self.rating_widget.rating = file.rating if len(ratings) <= 1 else None
                self.tag_list.setEnabled(True)
                self.add_tag_edit.setEnabled(True)
                self.rating_widget.setEnabled(True)
            else:
                self.file_path_text.clear()
                self.tag_list_model.current_file = None
                self.rating_widget.rating = None
                self.tag_list.setEnabled(False)
                self.add_tag_edit.setEnabled(False)
                self.rating_widget.setEnabled(False)

            self.selected_file = file
            self.selected_file_changed.emit(file)
