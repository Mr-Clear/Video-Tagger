#!/usr/bin/env python

import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, List, Dict, Tuple

import humanfriendly
from PySide6.QtCore import Qt, QTimer, QSize, QProcess, Signal, QObject, QSortFilterProxyModel, QAbstractTableModel, \
    QModelIndex, QEvent, QPoint, QDir, QItemSelectionModel, QThread, QDateTime
from PySide6.QtGui import QMouseEvent, QAction, QValidator
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTableView, QMainWindow, QSizePolicy, QVBoxLayout, \
    QHBoxLayout, QWidget, QLineEdit, QStyledItemDelegate, QDialog, QTreeView, QFileSystemModel, QHeaderView, QMenu, \
    QSpinBox, QDateTimeEdit, QToolButton


class VlcPlayer(QObject):
    def __init__(self):
        super().__init__()
        self.create_vlc_instance()

    # noinspection PyAttributeOutsideInit
    def create_vlc_instance(self):
        self.vlc_process = QProcess()
        self.vlc_process.setProgram("vlc")
        self.vlc_process.setArguments(["--extraintf", "rc"])
        self.vlc_process.start()
        self.vlc_process.waitForStarted()
        self._read_stdout()

    def _read_stdout(self):
        data = b''
        while True:
            self.vlc_process.waitForReadyRead()
            data += self.vlc_process.readAllStandardOutput().data()
            if data.endswith(b'> ') or self.vlc_process.state() == QProcess.ProcessState.NotRunning:
                return data[:-2].strip()

    def send(self, command):
        self.vlc_process.write(f'{command}\n'.encode())
        self.vlc_process.waitForBytesWritten()
        return self._read_stdout()

    def play_video(self, video_path):
        self.send(f'add {video_path}')
        self.send(f'play')

    def pause_video(self):
        self.send('pause')
    
    def stop_video(self):
        self.send('stop')

    def update_status(self):
        self.send('status')
        self.send('get_time')

    def seek_video(self, time):
        self.send(f'seek {time}')
    
    def close(self):
        self.send('quit')
        self.vlc_process.waitForFinished()


class Database:
    @dataclass
    class File:
        id: int
        path: str
        size: int
        date_modified: datetime
        duration: float | None = None
        rating: int | None = None
        tags: set[str] = field(default_factory=set)
        
        @property
        def name(self):
            return os.path.basename(self.path)

        @property
        def name_prefix(self):
            return self.name.split('.')[0]

        @property
        def extension(self):
            return os.path.splitext(self.path)[1]

    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()

        self.create_tables()

    def create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            size INTEGER NOT NULL,
            date_modified TIMESTAMP NOT NULL,
            duration FLOAT,
            rating INTEGER DEFAULT NULL
            )''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_has_tag (
                file_id INTEGER NOT NULL REFERENCES files(id),
                tag_id INTEGER NOT NULL REFERENCES tags(id))''')
        self.cursor.execute('''CREATE INDEX IF NOT EXISTS idx_file_id ON file_has_tag(file_id)''')
        self.cursor.execute('''CREATE INDEX IF NOT EXISTS idx_tag_id ON file_has_tag(tag_id)''')
        self.conn.commit()

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT)''')
    
    def close(self):
        self.conn.close()
    
    def get_file(self, file_id: int) -> File:
        self.cursor.execute('SELECT path, size, date_modified, duration, rating FROM files WHERE id = ?', (file_id,))
        path, size, date_modified, duration, rating = self.cursor.fetchone()
        self.cursor.execute('SELECT name FROM tags INNER JOIN file_has_tag ON tags.id = file_has_tag.tag_id WHERE '
                            'file_has_tag.file_id = ?', (file_id,))
        tags = {tag_row[0] for tag_row in self.cursor.fetchall()}
        return self.File(file_id, path, size, datetime.fromisoformat(date_modified), duration, rating, tags)

    def find_file(self, path: str) -> File | None:
        self.cursor.execute('SELECT id FROM files WHERE path = ?', (path,))
        file_id = self.cursor.fetchone()
        return self.get_file(file_id[0]) if file_id is not None else None

    def get_files(self) -> List[File]:
        self.cursor.execute('SELECT id FROM files ORDER BY path')
        file_ids = [row[0] for row in self.cursor.fetchall()]
        return [self.get_file(file_id) for file_id in file_ids]

    def get_files_with_tags(self, whitelist: Iterable[str], blacklist: Iterable[str]) -> List[File]:
        self.cursor.execute('SELECT id FROM files '
                            ' WHERE id IN (SELECT file_id FROM file_has_tag '
                            '               WHERE tag_id IN (SELECT id FROM tags WHERE name IN (?))) '
                            '                 AND id NOT IN (SELECT file_id FROM file_has_tag '
                            '                                 WHERE tag_id IN (SELECT id FROM tags WHERE name IN (?)))',
                            (whitelist, blacklist))
        file_ids = [row[0] for row in self.cursor.fetchall()]
        return [self.get_file(file_id) for file_id in file_ids]

    def add_file(self, file: File) -> int:
        self.cursor.execute('SELECT id FROM files WHERE path = ?', (file.path,))
        if self.cursor.fetchone() is not None:
            return -1  # File already exists
        self.cursor.execute('INSERT INTO files (path, size, date_modified, duration, rating) VALUES (?, ?, ?, ?, ?)',
                            (file.path, file.size, file.date_modified.isoformat(), file.duration, file.rating))
        file_id = self.cursor.lastrowid
        for tag in file.tags:
            self.set_tag(file_id, tag)
        self.conn.commit()
        return file_id
    
    def get_tags(self) -> Dict[str, int]:
        self.cursor.execute('SELECT name, COUNT(file_has_tag.tag_id) '
                            '  FROM tags LEFT JOIN file_has_tag ON tags.id = file_has_tag.tag_id GROUP BY tags.id')
        return {row[0]: row[1] for row in self.cursor.fetchall()}

    def add_tag(self, tad_name: str):
        self.cursor.execute('INSERT INTO tags (name) VALUES (?)', (tad_name,))
        self.conn.commit()

    def get_tag_id(self, tag: str) -> int | None:
        self.cursor.execute('SELECT id FROM tags WHERE name = ?', (tag,))
        tag_id = self.cursor.fetchone()
        return tag_id[0] if tag_id is not None else None

    def set_tag(self, file_id: int, tag: str):
        tag_id = self.get_tag_id(tag)
        if tag_id is None:
            self.cursor.execute('INSERT INTO tags (name) VALUES (?)', (tag,))
            tag_id = self.cursor.lastrowid
        self.cursor.execute('SELECT 1 FROM file_has_tag WHERE file_id = ? AND tag_id = ?', (file_id, tag_id))
        if self.cursor.fetchone() is None:
            self.cursor.execute('INSERT INTO file_has_tag (file_id, tag_id) VALUES (?, ?)', (file_id, tag_id))
            self.conn.commit()
    
    def remove_tag(self, file_id: int, tag: str):
        tag_id = self.get_tag_id(tag)
        if tag_id is None:
            return
        self.cursor.execute('DELETE FROM file_has_tag WHERE file_id = ? AND tag_id = ?', (file_id, tag_id))
        self.conn.commit()
    
    def delete_tag(self, tag: str):
        tag_id = self.get_tag_id(tag)
        if tag_id is None:
            return
        self.cursor.execute('DELETE FROM file_has_tag WHERE tag_id = ?', (tag_id,))
        self.cursor.execute('DELETE FROM tags WHERE id = ?', (tag_id,))
        self.conn.commit()

    def set_rating(self, file_id: int, rating: int | None):
        self.cursor.execute('UPDATE files SET rating = ? WHERE id = ?', (rating, file_id))
        self.conn.commit()

    def remove_file(self, file_id: int):
        self.cursor.execute('DELETE FROM file_has_tag WHERE file_id = ?', (file_id,))
        self.cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
        self.conn.commit()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        self.cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
        result = self.cursor.fetchone()
        return result[0] if result is not None else default
    
    def set_setting(self, key: str, value: str):
        self.cursor.execute('REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        self.conn.commit()

    def remove_setting(self, key: str):
        self.cursor.execute('DELETE FROM settings WHERE key = ?', (key,))
        self.conn.commit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.selected_file: Database.File | None = None

        self.setWindowTitle("Video Tagger")
        self.setGeometry(100, 100, 800, 600)

        self.vlc = VlcPlayer()

        self.database = Database('VideoTagger.db')

        self.file_list_model: FileListModel = FileListModel([])
        self.file_list_filter_model: FileSortFilterProxyModel = FileSortFilterProxyModel()
        self.tag_list_model: TagListModel = TagListModel({})

        self._init_ui()

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
        self.left_layout.addWidget(self.file_list)
        self.load_files()
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

        self.add_files_button = QPushButton("Add Files")
        self.add_files_button.clicked.connect(self.show_add_files_dialog)
        self.left_layout.addWidget(self.add_files_button)

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
                    self.database.add_file(Database.File(-1, file_path, size, date_modified))
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
        self.file_list_model = FileListModel(files)
        self.file_list_filter_model = FileSortFilterProxyModel()
        self.file_list_filter_model.setSourceModel(self.file_list_model)
        self.file_list.setModel(self.file_list_filter_model)
        
        self.file_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.file_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.file_list.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.file_list.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.file_list.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.file_list.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        self.filter_widget.filter_changed.connect(self.file_list_filter_model.set_filter)

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


class FileListModel(QAbstractTableModel):
    def __init__(self, files: List[Database.File]):
        super().__init__()
        self.files = files
        self.horizontal_header_labels = ['Name', 'Rating', 'Size', 'Modified', 'Duration']

    def rowCount(self, parent=QModelIndex()):
        return len(self.files)

    def columnCount(self, parent=QModelIndex()):
        return len(self.horizontal_header_labels)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        file_object = self.files[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return os.path.basename(file_object.path).split('.')[0]
            if index.column() == 1:
                if file_object.rating:
                    return '★' * file_object.rating + '☆' * (5 - file_object.rating)
                else:
                    return None
            elif index.column() == 2:
                return humanfriendly.format_size(file_object.size)
            elif index.column() == 3:
                return file_object.date_modified.strftime('%Y-%m-%d %H:%M:%S')
            elif index.column() == 4:
                return str(file_object.duration)
        elif role == Qt.ItemDataRole.DisplayRole.UserRole:
            return file_object
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.horizontal_header_labels[section]
        return None


class StarRatingWidget(QWidget):
    rating_changed = Signal(int)
    
    def __init__(self, font_size, parent=None):
        super().__init__(parent)
        self._rating: int | None = None
        self.hovered_star: int | None = None
        self.stars: List[QLabel] = []
        self.font_size: int = font_size
        self.init_ui()

    def star_mouse_event(self, i: int):
        def event(event: QMouseEvent):
            if event.type() == QEvent.Type.Enter:
                self.hovered_star = i
                self._update()
            elif event.type() == QEvent.Type.Leave:
                self.hovered_star = None
                self._update()
            elif event.type() == QEvent.Type.MouseButtonPress:
                self._set_rating(i + 1)
        return event

    def init_ui(self):
        layout = QHBoxLayout()
        for i in range(5):
            star = QLabel()
            star.mousePressEvent = self.star_mouse_event(i)
            star.enterEvent = self.star_mouse_event(i)
            star.leaveEvent = self.star_mouse_event(i)
            star.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed))
            layout.addWidget(star)
            self.stars.append(star)
        self.setLayout(layout)
        self._update()

    def _set_rating(self, rating: int | None):
        if rating != self._rating:
            self._rating = rating
            self._update()
            self.rating_changed.emit(rating)
    
    def _update(self):
        for i, star in enumerate(self.stars):
            rating = self._rating if self._rating is not None else 0
            if i < rating:
                star.setText('★')
            else:
                star.setText('☆')

            if self._rating is None:
                color = 'gray'
                weight = 'normal'
            elif i == self.hovered_star:
                color = 'blue'
                weight = 'bold'
            else:
                color = 'yellow'
                weight = 'normal'

            star.setStyleSheet(f'font-size: {self.font_size}px; color: {color}; font-weight: {weight}')

    @property
    def rating(self):
        return self._rating

    @rating.setter
    def rating(self, rating):
        self._rating = rating
        self._update()


class StarRatingDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.star_rating_widget = StarRatingWidget(10, parent)
        
    def paint(self, painter, option, index):
        file_object: Database.File = index.data(Qt.ItemDataRole.DisplayRole.UserRole)
        self.star_rating_widget.rating = file_object.rating
        self.star_rating_widget.setGeometry(option.rect)
        self.star_rating_widget.resize(option.rect.size())
        painter.save()
        painter.translate(option.rect.topLeft())
        self.star_rating_widget.render(painter, QPoint(0, 0))
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(100, 20)


@dataclass
class FileFilter:
    name_regex: str = ''
    name_regex_case_sensitive: bool = False
    path: str = ''
    rating: Tuple[int, int] = (0, 5)
    tags_whitelist: set[str] = field(default_factory=set)
    tags_blacklist: set[str] = field(default_factory=set)
    size: Tuple[int, int] = (0, sys.maxsize)
    date: Tuple[datetime, datetime] = (datetime.min, datetime.max)


class FileSortFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_file: Database.File | None = None
        self._filter = FileFilter()
        self._re = re.compile('')

    def sourceModel(self) -> FileListModel:
        if isinstance(super().sourceModel(), FileListModel):
            # noinspection PyTypeChecker
            return super().sourceModel()
        return FileListModel([])

    def lessThan(self, left, right):
        if self.sortColumn() != 1:  # Not size column
            return super().lessThan(left, right)

        left_file = self.sourceModel().files[left.row()]
        right_file = self.sourceModel().files[right.row()]
    
        return left_file.size < right_file.size

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        file_object = model.files[source_row]

        if file_object == self._current_file:
            return True

        if self._re.search(file_object.name_prefix) is None:
            return False
        if self._filter.path and not file_object.path.startswith(self._filter.path):
            return False
        rating = file_object.rating or 0
        if rating < self._filter.rating[0] or rating > self._filter.rating[1]:
            return False
        if self._filter.tags_whitelist and not self._filter.tags_whitelist.issubset(file_object.tags):
            return False
        if self._filter.tags_blacklist and self._filter.tags_blacklist.intersection(file_object.tags):
            return False
        if file_object.size < self._filter.size[0] or file_object.size > self._filter.size[1]:
            return False
        if file_object.date_modified < self._filter.date[0] or file_object.date_modified > self._filter.date[1]:
            return False
        return True

    @property
    def filter(self):
        return self._filter

    @filter.setter
    def filter(self, f: FileFilter):
        self._filter = f
        self._re = re.compile(f.name_regex, re.IGNORECASE if not f.name_regex_case_sensitive else re.NOFLAG)
        self.invalidateFilter()

    def set_filter(self, f: FileFilter):
        self.filter = f

    @property
    def current_file(self):
        return self._current_file

    @current_file.setter
    def current_file(self, file: Database.File | None):
        self._current_file = file

    def set_current_file(self, file: Database.File | None):
        self.current_file = file


class TagListModel(QAbstractTableModel):
    tag_set = Signal(int, str)
    tag_removed = Signal(int, str)

    def __init__(self, tags: Dict[str, int]):
        super().__init__()
        self.tags = tags
        self.tag_names = list(tags.keys())
        self.checked_tags = set()
        self._current_file: Database.File | None = None

    def rowCount(self, parent=QModelIndex()):
        return len(self.tags)

    def columnCount(self, parent=QModelIndex()):
        return 3  # Checkbox, Tag Name, Tag Count

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        tag_name = self.tag_names[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 1:
                return tag_name
            elif index.column() == 2:
                return str(self.tags[tag_name])
        elif role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            return Qt.CheckState.Checked if tag_name in self.checked_tags else Qt.CheckState.Unchecked
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            tag_name = self.tag_names[index.row()]
            if value == Qt.CheckState.Checked.value:
                self.checked_tags.add(tag_name)
                self.tags[tag_name] += 1
                self.tag_set.emit(self.current_file.id, tag_name)
            else:
                self.checked_tags.remove(tag_name)
                self.tags[tag_name] -= 1
                self.tag_removed.emit(self.current_file.id, tag_name)
            self.dataChanged.emit(index, index.sibling(index.row(), self.columnCount() - 1))
            return True
        return False

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if index.column() == 0:
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
        return Qt.ItemFlag.ItemIsEnabled

    def headerData(self, section, orientation, role=Qt.ItemDataRole.EditRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section == 0:
                return "☑"
            elif section == 1:
                return "Name"
            elif section == 2:
                return "∑"
        return None

    @property
    def current_file(self):
        return self._current_file

    @current_file.setter
    def current_file(self, file: Database.File | None):
        if file is not None:
            self.checked_tags = file.tags
        self._current_file = file
        self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))
    
    def set_tag(self, tag_name: str):
        if tag_name not in self.tags:
            self.beginInsertRows(QModelIndex(), self.rowCount(), self.rowCount())
            self.tags[tag_name] = 0
            self.tag_names.append(tag_name)
            self.endInsertRows()
        if self.current_file and tag_name not in self.current_file.tags:
            self.tags[tag_name] += 1
            self.current_file.tags.add(tag_name)
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))


class FilterWidget(QWidget):
    filter_changed = Signal(FileFilter)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter = FileFilter()
        self.init_ui()

    # noinspection PyAttributeOutsideInit
    def init_ui(self):
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.name_regex_layout = QHBoxLayout()
        self.layout.addLayout(self.name_regex_layout)

        self.name_regex_edit = QLineEdit()
        self.name_regex_edit.setText(self._filter.name_regex)
        self.name_regex_edit.setPlaceholderText('Name Regex')
        self.name_regex_edit.returnPressed.connect(lambda: self.set_name_regex(self.name_regex_edit.text()))
        self.name_regex_layout.addWidget(self.name_regex_edit)

        self.name_regex_case_sensitive_button = QToolButton()
        self.name_regex_case_sensitive_button.setCheckable(True)
        self.name_regex_case_sensitive_button.setChecked(self._filter.name_regex_case_sensitive)
        self.name_regex_case_sensitive_button.setText('Aa')
        self.name_regex_case_sensitive_button.toggled.connect(self.set_name_regex_case_sensitive)
        self.name_regex_case_sensitive_button.setToolTip('Case Sensitive')
        self.name_regex_layout.addWidget(self.name_regex_case_sensitive_button)

        self.path_edit = QLineEdit()
        self.path_edit.setText(self._filter.path)
        self.path_edit.setPlaceholderText('Path')
        self.path_edit.returnPressed.connect(lambda: self.set_path(self.path_edit.text()))
        self.layout.addWidget(self.path_edit)

        self.rating_layout = QHBoxLayout()
        self.layout.addLayout(self.rating_layout)
        self.rating_min_edit = QSpinBox()
        self.rating_min_edit.setRange(0, 5)
        self.rating_min_edit.setValue(self._filter.rating[0])
        self.rating_min_edit.valueChanged.connect(lambda: self.set_min_rating(self.rating_min_edit.value()))
        self.rating_layout.addWidget(self.rating_min_edit)

        self.rating_max_edit = QSpinBox()
        self.rating_max_edit.setRange(0, 5)
        self.rating_max_edit.setValue(self._filter.rating[1])
        self.rating_max_edit.valueChanged.connect(lambda: self.set_max_rating(self.rating_max_edit.value()))
        self.rating_layout.addWidget(self.rating_max_edit)
        
        self.tags_whitelist_edit = QLineEdit()
        self.tags_whitelist_edit.setText('|'.join(self._filter.tags_whitelist))
        self.tags_whitelist_edit.setPlaceholderText('Tags Whitelist')
        self.tags_whitelist_edit.returnPressed.connect(lambda: self.set_tags_whitelist(self.tags_whitelist_edit.text()))
        self.layout.addWidget(self.tags_whitelist_edit)

        self.tags_blacklist_edit = QLineEdit()
        self.tags_blacklist_edit.setText('|'.join(self._filter.tags_blacklist))
        self.tags_blacklist_edit.setPlaceholderText('Tags Blacklist')
        self.tags_blacklist_edit.returnPressed.connect(lambda: self.set_tags_blacklist(self.tags_blacklist_edit.text()))
        self.layout.addWidget(self.tags_blacklist_edit)

        self.size_layout = QHBoxLayout()
        self.layout.addLayout(self.size_layout)

        self.size_label = QLabel('Size from')
        self.size_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed))
        self.size_layout.addWidget(self.size_label)

        self.size_min_edit = QLineEdit()
        self.size_min_edit.setText(humanfriendly.format_size(self._filter.size[0]))
        self.size_min_edit.setPlaceholderText('Min size')
        self.size_min_edit.setValidator(HumanReadableSizeValidator())
        self.size_min_edit.returnPressed.connect(
            lambda: self.set_min_size(humanfriendly.parse_size(self.size_min_edit.text())))
        self.size_layout.addWidget(self.size_min_edit)

        self.size_to_label = QLabel('to')
        self.size_to_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed))
        self.size_layout.addWidget(self.size_to_label)

        self.size_max_edit = QLineEdit()
        self.size_max_edit.setText(humanfriendly.format_size(self._filter.size[1]))
        self.size_max_edit.setPlaceholderText('Max size')
        self.size_max_edit.setValidator(HumanReadableSizeValidator())
        self.size_max_edit.returnPressed.connect(
            lambda: self.set_max_size(humanfriendly.parse_size(self.size_max_edit.text())))
        self.size_layout.addWidget(self.size_max_edit)

        self.date_layout = QHBoxLayout()
        self.layout.addLayout(self.date_layout)

        self.date_label = QLabel('Date from')
        self.date_layout.addWidget(self.date_label)
        self.date_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed))

        self.date_min_edit = QDateTimeEdit()
        self.date_min_edit.setDateTime(to_QDateTime(self._filter.date[0]))
        self.date_min_edit.setDisplayFormat('yyyy-MM-dd HH:mm:ss')
        self.date_min_edit.setCalendarPopup(True)
        self.date_min_edit.dateTimeChanged.connect(
            lambda: self.set_min_date(to_datetime(self.date_min_edit.dateTime())))
        self.date_layout.addWidget(self.date_min_edit)

        self.date_to_label = QLabel('to')
        self.date_layout.addWidget(self.date_to_label)
        self.date_to_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed))

        self.date_max_edit = QDateTimeEdit()
        self.date_max_edit.setDateTime(to_QDateTime(self._filter.date[1]))
        self.date_max_edit.setDisplayFormat('yyyy-MM-dd HH:mm:ss')
        self.date_max_edit.setCalendarPopup(True)
        self.date_max_edit.dateTimeChanged.connect(self.set_max_date)
        self.date_layout.addWidget(self.date_max_edit)

    def make_tag_list(self, text: str) -> set[str]:
        # noinspection PyUnresolvedReferences
        tags = self.parent().parent().tag_list_model.tag_names
        ret = set()
        for tag in text.split('|'):
            tag = tag.strip()
            found = False
            for t in tags:
                if t.lower() == tag.lower():
                    ret.add(t)
                    found = True
            if not found and tag:
                ret.add(tag)
        return ret
    
    @property
    def filter(self) -> FileFilter:
        return self._filter

    @filter.setter
    def filter(self, f: FileFilter):
        self.name_regex = f.name_regex
        self.path = f.path
        self.max_rating = f.rating[0]
        self.min_rating = f.rating[1]
        self.tags_whitelist = f.tags_whitelist
        self.tags_blacklist = f.tags_blacklist
        self.min_size = f.size[0]
        self.max_size = f.size[1]
        self.min_date = f.date[0]
        self.max_date = f.date[1]

    @property
    def name_regex(self) -> str:
        return self._filter.name_regex

    @name_regex.setter
    def name_regex(self, name_regex: str):
        if name_regex != self._filter.name_regex:
            self._filter.name_regex = name_regex
            self.name_regex_edit.setText(name_regex)
            self.filter_changed.emit(self._filter)

    def set_name_regex(self, name_regex: str):
        self.name_regex = name_regex

    @property
    def name_regex_case_sensitive(self) -> bool:
        return self._filter.name_regex_case_sensitive

    @name_regex_case_sensitive.setter
    def name_regex_case_sensitive(self, name_regex_case_sensitive: bool):
        if name_regex_case_sensitive != self._filter.name_regex_case_sensitive:
            self._filter.name_regex_case_sensitive = name_regex_case_sensitive
            self.name_regex_case_sensitive_button.setChecked(self._filter.name_regex_case_sensitive)
            self.filter_changed.emit(self._filter)

    def set_name_regex_case_sensitive(self, name_regex_case_sensitive: bool):
        self.name_regex_case_sensitive = name_regex_case_sensitive

    @property
    def path(self) -> str:
        return self._filter.path

    @path.setter
    def path(self, path: str):
        if path != self._filter.path:
            self._filter.path = path
            self.path_edit.setText(path)
            self.filter_changed.emit(self._filter)

    def set_path(self, path: str):
        self.path = path

    @property
    def rating(self) -> Tuple[int, int]:
        return self._filter.rating

    @rating.setter
    def rating(self, rating: Tuple[int, int]):
        self.min_rating = rating[0]
        self.max_rating = rating[1]

    def set_rating(self, rating: Tuple[int, int]):
        self.rating = rating

    @property
    def min_rating(self) -> int:
        return self._filter.rating[0]

    @min_rating.setter
    def min_rating(self, min_rating: int):
        if min_rating != self._filter.rating[0]:
            self._filter.rating = (min_rating, self._filter.rating[1])
            self.rating_min_edit.setValue(min_rating)
            self.filter_changed.emit(self._filter)

    def set_min_rating(self, min_rating: int):
        self.min_rating = min_rating
    
    @property
    def max_rating(self) -> int:
        return self._filter.rating[1]

    @max_rating.setter
    def max_rating(self, max_rating: int):
        if max_rating != self._filter.rating[1]:
            self._filter.rating = (self._filter.rating[0], max_rating)
            self.rating_max_edit.setValue(max_rating)
            self.filter_changed.emit(self._filter)

    def set_max_rating(self, max_rating: int):
        self.max_rating = max_rating

    @property
    def tags_whitelist(self) -> set[str]:
        return self._filter.tags_whitelist

    @tags_whitelist.setter
    def tags_whitelist(self, tags_whitelist: set[str]):
        self._filter.tags_whitelist = tags_whitelist
        self.tags_whitelist_edit.setText(' | '.join(tags_whitelist))
        self.filter_changed.emit(self._filter)

    def set_tags_whitelist(self, tags_whitelist: str):
        self.tags_whitelist = self.make_tag_list(tags_whitelist)

    @property
    def tags_blacklist(self) -> set[str]:
        return self._filter.tags_blacklist

    @tags_blacklist.setter
    def tags_blacklist(self, tags_blacklist: set[str]):
        self._filter.tags_blacklist = tags_blacklist
        self.tags_blacklist_edit.setText(' | '.join(tags_blacklist))
        self.filter_changed.emit(self._filter)

    def set_tags_blacklist(self, tags_blacklist: str):
        self.tags_blacklist = self.make_tag_list(tags_blacklist)

    @property
    def size(self) -> Tuple[int, int]:
        return self._filter.size

    @size.setter
    def size(self, size: Tuple[int, int]):
        self.min_size = size[0]
        self.max_size = size[1]

    def set_size(self, size: Tuple[int, int]):
        self.size = size

    @property
    def min_size(self):
        return self._filter.size[0]

    @min_size.setter
    def min_size(self, min_size: int):
        if min_size != self._filter.size[0]:
            self._filter.size = (min_size, self._filter.size[1])
            self.size_min_edit.setText(humanfriendly.format_size(min_size))
            self.filter_changed.emit(self._filter)

    def set_min_size(self, min_size: int):
        self.min_size = min_size

    @property
    def max_size(self) -> int:
        return self._filter.size[1]

    @max_size.setter
    def max_size(self, max_size: int):
        if max_size != self._filter.size[1]:
            self._filter.size = (self._filter.size[0], max_size)
            self.size_max_edit.setText(humanfriendly.format_size(max_size))
            self.filter_changed.emit(self._filter)

    def set_max_size(self, max_size: int):
        self.max_size = max_size

    @property
    def date(self) -> Tuple[datetime, datetime]:
        return self._filter.date

    @date.setter
    def date(self, date: Tuple[datetime, datetime]):
        self.min_date = date[0]
        self.max_date = date[1]

    def set_date(self, date: Tuple[datetime, datetime]):
        self.date = date

    @property
    def min_date(self) -> datetime:
        return self._filter.date[0]

    @min_date.setter
    def min_date(self, min_date: datetime):
        if min_date != self._filter.date[0]:
            self._filter.date = (min_date, self._filter.date[1])
            self.date_min_edit.setDateTime(to_QDateTime(min_date))
            self.filter_changed.emit(self._filter)

    def set_min_date(self, min_date: datetime):
        self.min_date = min_date

    @property
    def max_date(self) -> datetime:
        return self._filter.date[1]

    @max_date.setter
    def max_date(self, max_date: datetime):
        if max_date != self._filter.date[1]:
            self._filter.date = (self._filter.date[0], max_date)
            self.date_max_edit.setDateTime(to_QDateTime(max_date))
            self.filter_changed.emit(self._filter)

    def set_max_date(self, max_date: datetime):
        self.max_date = max_date


class HumanReadableSizeValidator(QValidator):
    def __init__(self, parent=None):
        super().__init__(parent)

    def validate(self, input_str, pos):
        try:
            humanfriendly.parse_size(input_str)
            return QValidator.State.Acceptable, input_str, pos
        except humanfriendly.InvalidSize:
            return QValidator.State.Invalid, input_str, pos

    def fixup(self, input_str):
        try:
            return humanfriendly.parse_size(input_str)
        except humanfriendly.InvalidSize:
            return ''


class AddFilesDialog(QDialog):
    default_filter = QDir.Filter.Dirs | QDir.Filter.NoDotAndDotDot

    class ScanWorker(QObject):
        file_found = Signal(str)
        finished = Signal()

        def __init__(self, directory, file_filter):
            super().__init__()
            self.directory = directory
            self.file_filter = file_filter
            self.abort_scan = False

        def scan(self):
            for root, _, files in os.walk(self.directory):
                for file in files:
                    if self.abort_scan:
                        return
                    if file.endswith(tuple(self.file_filter.split(';'))):
                        try:
                            file_path = resolve_symlink(os.path.join(root, file))
                            self.file_found.emit(file_path)
                        except Exception as e:
                            print(e)

        def run(self):
            self.scan()
            self.finished.emit()

    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        self.found_files = set()

        self.setWindowTitle("Add Files")
        self.setGeometry(100, 100, 800, 600)

        self.init_ui()

        self.scan_worker: AddFilesDialog.ScanWorker | None = None
        self.scan_worker_thread: QThread | None = None

    # noinspection PyAttributeOutsideInit
    def init_ui(self):
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        filters = '.mp4;.avi;.mkv;.mov;.wmv;.flv;.webm;.webp;.mpeg;.mpg;.m4v;.3gp;.vob;.ogv;.ogg;.mxf;.rm;.divx;.xvid'
        self.file_filter = QLineEdit(self.database.get_setting('scan_file_filter', filters))
        self.file_filter.textChanged.connect(lambda text: self.database.set_setting('scan_file_filter', text))
        self.layout.addWidget(self.file_filter)

        self.file_system_view = QTreeView()
        self.file_system_view_model = QFileSystemModel()
        self.file_system_view.setModel(self.file_system_view_model)
        self.file_system_view_model.setRootPath(QDir.rootPath())
        self.file_system_view_model.setFilter(QDir.Filter.Dirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden)
        for i in range(1, 4):
            self.file_system_view.hideColumn(i)
        last_used_folder = self.database.get_setting('last_scanned_folder', QDir.homePath())
        last_used_index = self.file_system_view_model.index(last_used_folder)
        self.file_system_view.scrollTo(last_used_index)
        self.file_system_view.selectionModel().setCurrentIndex(last_used_index,
                                                               QItemSelectionModel.SelectionFlag.Select)
        self.file_system_view.setExpanded(last_used_index, True)
        self.file_system_view.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        toggle_hidden_action = QAction("Toggle Hidden Files", self)
        toggle_hidden_action.setShortcut("Ctrl+H")
        toggle_hidden_action.triggered.connect(self.toggle_hidden_files)
        self.addAction(toggle_hidden_action)
        self.show_hidden_files(self.database.get_setting('show_hidden_files', str(False)) == 'True')
        self.layout.addWidget(self.file_system_view)

        self.bottom_layout = QHBoxLayout()
        self.layout.addLayout(self.bottom_layout)

        self.scan_directory_button = QPushButton("Scan Directory")
        self.scan_directory_button.clicked.connect(self.scan_directory)
        self.bottom_layout.addWidget(self.scan_directory_button)

        self.abort_scan_button = QPushButton("Abort Scan")
        self.abort_scan_button.setEnabled(False)
        self.abort_scan_button.clicked.connect(self.abort_scan)
        self.bottom_layout.addWidget(self.abort_scan_button)

        self.status_label = QLabel()
        self.bottom_layout.addWidget(self.status_label)

        self.accept_button = QPushButton("Accept")
        self.accept_button.clicked.connect(self.accept)
        self.bottom_layout.addWidget(self.accept_button)

    def toggle_hidden_files(self):
        show = not self.file_system_view_model.filter() & QDir.Filter.Hidden
        self.show_hidden_files(show)
        self.database.set_setting('show_hidden_files', str(show))
    
    def show_hidden_files(self, show: bool):
        if show:
            self.file_system_view_model.setFilter(AddFilesDialog.default_filter | QDir.Filter.Hidden)
        else:
            self.file_system_view_model.setFilter(AddFilesDialog.default_filter)

    def scan_directory(self):
        scan_root = self.file_system_view_model.filePath(self.file_system_view.currentIndex())
        self.database.set_setting('last_scanned_folder', scan_root)
        self.scan_directory_button.setEnabled(False)
        self.abort_scan_button.setEnabled(True)
        self.accept_button.setEnabled(False)
        self.status_label.setText("Scanning directory...")
        self.scan_worker = AddFilesDialog.ScanWorker(scan_root, self.file_filter.text())
        self.scan_worker.file_found.connect(self.on_file_found)
        self.scan_worker.finished.connect(self.on_finished)
        self.scan_worker_thread = QThread()
        self.scan_worker.moveToThread(self.scan_worker_thread)
        self.scan_worker_thread.started.connect(self.scan_worker.run)
        self.scan_worker_thread.start()
    
    def on_file_found(self, file_path):
        self.found_files.add(file_path)
        self.status_label.setText(f"Found {len(self.found_files)} files")
    
    def on_finished(self):
        self.status_label.setText(f"{len(self.found_files)} files found")
        self.scan_directory_button.setEnabled(True)
        self.abort_scan_button.setEnabled(False)
        self.accept_button.setEnabled(True)

    def abort_scan(self):
        if self.scan_worker:
            self.scan_worker.abort_scan = True
            self.scan_worker_thread.quit()
            self.scan_worker_thread.wait()
        self.status_label.setText("Scan aborted")


def resolve_symlink(path):
    if os.path.islink(path):
        return resolve_symlink(os.path.realpath(path))
    return path


# noinspection PyPep8Naming
def to_QDateTime(dt: datetime):
    if 1970 < dt.year < 2038:
        return QDateTime.fromMSecsSinceEpoch(int(dt.timestamp() * 1000))
    return QDateTime()


def to_datetime(dt: QDateTime):
    return datetime.fromtimestamp(dt.toMSecsSinceEpoch() / 1000.0)


def main():
    app = QApplication([])
    main_window = MainWindow()
    main_window.showMaximized()
    app.exec()


if __name__ == '__main__':
    main()
