import copy
import gzip
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

import jsonpickle
from PySide6.QtCore import (QByteArray, QFile, QModelIndex, QRegularExpression,
                            QSortFilterProxyModel, Qt, QTimer, Signal)
from PySide6.QtGui import QAction, QKeyEvent, QWindow
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QPushButton,
                               QSplitter, QTableView, QVBoxLayout, QWidget)

from Database import Database
from Ui.AddFilesDialog import AddFilesDialog
from Ui.CompressVideoDialog import CompressVideoDialog
from Ui.FileDetailsDialog import FileDetailsDialog
from Ui.FileListModel import FileListModel
from Ui.FileSortFilterProxyModel import FileSortFilterProxyModel
from Ui.FilterWidget import FilterWidget
from Ui.ProgressDialog import ProgressDialog
from Ui.StarRatingWidget import StarRatingWidget
from Ui.TagListModel import TagListModel
from VideoFile import VideoFile
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

        QTimer.singleShot(0, self.load_files)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_vlc_status)
        self.timer.start(1000)

        QApplication.instance().installEventFilter(self)

    def _init_ui(self):
        self.compress_dialog = CompressVideoDialog(self)
        self.compress_dialog.file_compressed.connect(self.on_file_compressed)

        self.central_widget = QWidget()
        self.main_layout = QHBoxLayout()
        self.central_widget.setLayout(self.main_layout)
        self.setCentralWidget(self.central_widget)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_layout.addWidget(self.splitter)

        left_widget = QWidget()
        self.left_layout = QVBoxLayout(left_widget)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.splitter.addWidget(left_widget)

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
        self.file_list_model.duration_loaded.connect(self.on_duration_loaded)
        self.file_list.setModel(self.file_list_filter_model)
        self.file_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # ResizeToContents sections are re-measured on every width change, which is very slow while dragging the
        # splitter. Measure once (debounced) when the contents change instead.
        self.file_columns_timer = self._create_fit_columns_timer(self.file_list, range(1, 7))
        for signal in (self.file_list_model.modelReset, self.file_list_model.rowsInserted,
                       self.file_list_model.rowsRemoved, self.file_list_model.dataChanged):
            signal.connect(lambda *_: self.file_columns_timer.start())
        self.file_list.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.filter_widget.filter_changed.connect(self.file_list_filter_model.set_filter)
        self.filter_widget.filter_changed.connect(self.prioritize_visible_durations)

        self.left_layout.addWidget(self.file_list)

        self.file_list.selectionModel().selectionChanged.connect(self.on_file_selected)
        self.file_list.selectionModel().selectionChanged.connect(self.on_file_selection_changed)
        self.file_list.doubleClicked.connect(self.play_selected_file)
        self.file_list.verticalScrollBar().valueChanged.connect(self.prioritize_visible_durations)
        self.file_list.verticalScrollBar().sliderMoved.connect(self.prioritize_visible_durations)
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

        self.database_layout.addStretch()
        self.verify_files_button = QPushButton("Verify Files")
        self.verify_files_button.clicked.connect(self.verify_files)
        self.database_layout.addWidget(self.verify_files_button)

        self.add_files_button = QPushButton("Add Files")
        self.add_files_button.clicked.connect(self.show_add_files_dialog)
        self.database_layout.addWidget(self.add_files_button)

        self.export_button = QPushButton("Export File List")
        self.export_button.clicked.connect(self.export_file_list)
        self.database_layout.addWidget(self.export_button)

        right_widget = QWidget()
        self.right_layout = QVBoxLayout(right_widget)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.splitter.addWidget(right_widget)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setOpaqueResize(False)
        splitter_state = self.database.get_setting('splitter_state')
        if splitter_state:
            self.splitter.restoreState(QByteArray.fromHex(splitter_state.encode()))
        # Debounced so dragging doesn't write to the database on every move event.
        self.splitter_save_timer = QTimer(self)
        self.splitter_save_timer.setSingleShot(True)
        self.splitter_save_timer.setInterval(500)
        self.splitter_save_timer.timeout.connect(
            lambda: self.database.set_setting('splitter_state', self.splitter.saveState().toHex().data().decode()))
        self.splitter.splitterMoved.connect(lambda *_: self.splitter_save_timer.start())

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

    def _create_fit_columns_timer(self, view: QTableView, columns) -> QTimer:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(200)
        timer.timeout.connect(lambda: [view.resizeColumnToContents(c) for c in columns])
        return timer

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

    def verify_files(self):
        count = self.file_list_filter_model.rowCount()
        progress_dialog = ProgressDialog("Verifying Files", count, self)
        progress_dialog.show()

        for row in range(count):
            index = self.file_list_filter_model.index(row, 0)
            file = index.data(Qt.ItemDataRole.DisplayRole.UserRole)
            if progress_dialog.set_progress(row + 1, file.path):
                progress_dialog.set_end(True)
                return
            if file is not None:
                if not os.path.exists(file.path):
                    self.database.set_size(file.id, -1)
                    file.size = -1
                    self.file_list_model.on_file_modified(file)
                else:
                    size = os.path.getsize(file.path)
                    if size != file.size:
                        self.database.set_size(file.id, size)
                        file.size = size
                        self.file_list_model.on_file_modified(file)
        progress_dialog.set_end(False)

    def show_compress_dialog(self):
        files = self._get_selected_files()
        if not files and self.selected_file is not None:
            files = [self.selected_file]
        self.compress_dialog.set_files(files)
        self.compress_dialog.show()
        self.compress_dialog.raise_()
        self.compress_dialog.activateWindow()

    def on_file_compressed(self, file_path: str):
        try:
            size = os.path.getsize(file_path)
            date_modified = datetime.fromtimestamp(os.path.getmtime(file_path))
        except OSError:
            return
        file_id = self.database.add_file(VideoFile(-1, file_path, size, date_modified))
        if file_id < 0:
            return
        self.file_list_model.add_file(self.database.get_file(file_id))
        # Widen the size/date filter so the new file isn't hidden by the ranges computed at load time.
        self.filter_widget.min_size = min(self.filter_widget.min_size, size)
        self.filter_widget.max_size = max(self.filter_widget.max_size, size)
        self.filter_widget.min_date = min(self.filter_widget.min_date, date_modified)
        self.filter_widget.max_date = max(self.filter_widget.max_date, date_modified)
        self.file_list_filter_model.sort(self.file_list_filter_model.sortColumn(),
                                         self.file_list_filter_model.sortOrder())
        self.file_list_model.queue_remaining_durations()

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

    def export_file_list(self):
        files = []
        if self.file_list.selectionModel().hasSelection():
            selected_indexes = self.file_list.selectionModel().selectedRows()
            files = [index.data(Qt.ItemDataRole.DisplayRole.UserRole) for index in selected_indexes]
        else:
            files = [self.file_list_filter_model.index(i, 0).data(Qt.ItemDataRole.DisplayRole.UserRole) for i in range(self.file_list_filter_model.rowCount())]
        if not files:
            QMessageBox.warning(self, "No Files", "There are no files to export.")
            return

        file_path, _ = QFileDialog.getSaveFileName(self, "Export File List")
        if file_path:
            with open(file_path, 'w') as f:
                for file in files:
                    f.write(f"{file.path}\n")

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
        QTimer.singleShot(0, self.start_duration_loading)

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

    def start_duration_loading(self):
        self.prioritize_visible_durations()
        self.file_list_model.queue_remaining_durations()

    def prioritize_visible_durations(self):
        visible_files = []
        first_row = max(self.file_list.rowAt(0), 0)
        last_row = self.file_list.rowAt(self.file_list.viewport().height() - 1)
        if last_row < 0:
            last_row = self.file_list_filter_model.rowCount() - 1
        for row in range(first_row, last_row + 1):
            source_index = self.file_list_filter_model.mapToSource(
                self.file_list_filter_model.index(row, 0))
            visible_files.append(source_index.data(Qt.ItemDataRole.UserRole))
        self.file_list_model.request_visible_durations([file for file in visible_files if file is not None])

    def on_duration_loaded(self, file: VideoFile):
        if file.duration is not None:
            print(f"Duration loaded for {file.path}: {file.duration} seconds")
            self.database.set_duration(file.id, file.duration)
        if self.file_list_filter_model.sortColumn() in (5, 6):
            self.file_list_filter_model.sort(self.file_list_filter_model.sortColumn(), self.file_list_filter_model.sortOrder())

    def load_tags(self):
        tags = self.database.get_tags()
        self.tag_list_model = TagListModel(tags)
        self.tag_list_filter_model = QSortFilterProxyModel()
        self.tag_list_filter_model.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.tag_list_filter_model.setFilterKeyColumn(1)
        self.tag_list_filter_model.setSourceModel(self.tag_list_model)
        self.tag_list.setModel(self.tag_list_filter_model)

        self.tag_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tag_columns_timer = self._create_fit_columns_timer(self.tag_list, (0, 2))
        for signal in (self.tag_list_model.modelReset, self.tag_list_model.rowsInserted,
                       self.tag_list_model.rowsRemoved, self.tag_list_model.dataChanged):
            signal.connect(lambda *_: self.tag_columns_timer.start())
        self.tag_columns_timer.start()
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

        menu.addSeparator()

        file_details_action = QAction('File details...', self)
        file_details_action.setEnabled(len(selected_files) == 1)
        file_details_action.triggered.connect(lambda: self.show_file_details(selected_files[0]))
        menu.addAction(file_details_action)

        compress_action = QAction('Compress Video...', self)
        compress_action.setEnabled(bool(selected_files))
        compress_action.triggered.connect(self.show_compress_dialog)
        menu.addAction(compress_action)

        replace_original_action = QAction('Replace Original', self)
        original = self._find_original(selected_files[0]) if len(selected_files) == 1 else None
        replace_original_action.setEnabled(original is not None)
        if original is not None:
            replace_original_action.triggered.connect(lambda: self.replace_original(selected_files[0], original))
        menu.addAction(replace_original_action)

        delete_action = QAction('Delete', self)
        delete_action.setEnabled(bool(selected_files))
        delete_action.triggered.connect(lambda: self.delete_files(selected_files))
        menu.addAction(delete_action)

        menu.exec(self.file_list.viewport().mapToGlobal(pos))

    def delete_files(self, files: list[VideoFile]):
        names = '\n'.join(file.name for file in files[:10])
        if len(files) > 10:
            names += f'\n... and {len(files) - 10} more'
        answer = QMessageBox.question(
            self, 'Delete', f'Move {len(files)} file(s) to the trash and remove them from the list?\n\n{names}',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return

        failed = []
        for file in files:
            # A file that is already gone from disk is still removed from the list.
            if os.path.exists(file.path) and not QFile.moveToTrash(file.path):
                failed.append(file.name)
                continue
            self.database.remove_file(file.id)
            self.file_list_model.remove_file(file)
        if failed:
            QMessageBox.warning(self, 'Delete', 'Could not delete:\n' + '\n'.join(failed))

    def _find_original(self, file: VideoFile) -> VideoFile | None:
        match = re.fullmatch(r'(.*)_compressed(?:_\d+)?', file.name_prefix)
        if match is None:
            return None
        directory = os.path.dirname(file.path)
        return next((f for f in self.file_list_model.files
                     if f is not file and os.path.dirname(f.path) == directory
                     and f.name_prefix == match.group(1) and os.path.exists(f.path)), None)

    def replace_original(self, compressed: VideoFile, original: VideoFile):
        new_path = os.path.join(os.path.dirname(original.path), original.name_prefix + compressed.extension)
        if new_path != original.path and os.path.exists(new_path):
            QMessageBox.warning(self, 'Replace Original', f'{new_path} already exists.')
            return
        answer = QMessageBox.question(
            self, 'Replace Original',
            f'Delete "{original.name}" and move "{compressed.name}" to "{os.path.basename(new_path)}"?\n'
            'Tags and rating of the original are kept.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            os.replace(compressed.path, new_path)
        except OSError as e:
            QMessageBox.warning(self, 'Replace Original', str(e))
            return
        if new_path != original.path:
            try:
                os.remove(original.path)
            except OSError as e:
                QMessageBox.warning(self, 'Replace Original', f'Could not delete the original file: {e}')

        size = os.path.getsize(new_path)
        date_modified = datetime.fromtimestamp(os.path.getmtime(new_path))
        self.database.remove_file(compressed.id)
        self.database.update_file_location(original.id, new_path, size, date_modified, compressed.duration)
        self.file_list_model.remove_file(compressed)
        original.path, original.size, original.date_modified = new_path, size, date_modified
        original.duration = compressed.duration
        self.file_list_model.on_file_modified(original)
        if self.selected_file is original:
            self._emit_selected_file_modified()

    def show_file_details(self, file: VideoFile):
        dialog = FileDetailsDialog(file.path, self)
        dialog.exec()

    def toggle_column_visibility(self, column, visible):
        self.file_list.setColumnHidden(column, not visible)
        for action in self.file_list_header_context_menu.actions():
            self.database.set_setting(f'column_visibility_{action.text()}', str(action.isChecked()))

    def close_event(self, event):
        self.vlc.close()
        event.accept()

    def backup_database(self):
        data = {
            'Files': copy.deepcopy(self.file_list_model.files),
            'Settings': dict(self.database.get_settings()),
        }
        backup_path = Path('.backup') / f'{datetime.now().isoformat()}.json.gz'
        threading.Thread(target=self._write_backup, args=(data, backup_path), daemon=True).start()

    @staticmethod
    def _write_backup(data, backup_path: Path):
        Path('.backup').mkdir(exist_ok=True)
        with gzip.open(backup_path, 'wt', encoding='utf-8') as f:
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
