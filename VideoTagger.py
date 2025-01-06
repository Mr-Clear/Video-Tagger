#!/usr/bin/env python

import humanize
import sqlite3

from PySide6.QtCore import Qt, QMargins, QTimer, QSize, QRect, QProcess, Signal, QObject, QSortFilterProxyModel, QAbstractTableModel, QModelIndex, QEvent, QPoint, QDir, QItemSelectionModel, QThread
from PySide6.QtGui import QStandardItemModel, QStandardItem, QMouseEvent, QAction
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QListView, QTableView, QMainWindow, QSizePolicy, QVBoxLayout, QHBoxLayout, QWidget, QSlider, QLineEdit, QStyledItemDelegate, QDialog, QTreeView, QFileSystemModel, QHeaderView, QMenu

from dataclasses import dataclass, field
from typing import Iterable, Set, List, Dict
import os
import subprocess
from PySide6.QtWidgets import QFileDialog
from datetime import datetime


class VlcPlayer(QObject):
    def __init__(self):
        super().__init__()
        self.create_vlc_instance()

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
    
    def get_video_time(self):
        self.send('get_time')
        return self.vlc_process.stdout.read()
    
    def close(self):
        self.send('quit')
        self.vlc_process.wait_for_finished()


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
        self.cursor.execute('SELECT name FROM tags INNER JOIN file_has_tag ON tags.id = file_has_tag.tag_id WHERE file_has_tag.file_id = ?', (file_id,))
        tags = {tag_row[0] for tag_row in self.cursor.fetchall()}
        return self.File(file_id, path, size, datetime.fromisoformat(date_modified), duration, rating, tags)

    def find_file(self, path: str) -> File|None:
        self.cursor.execute('SELECT id FROM files WHERE path = ?', (path,))
        file_id = self.cursor.fetchone()
        return self.get_file(file_id[0]) if file_id is not None else None

    def get_files(self) -> List[File]:
        self.cursor.execute('SELECT id FROM files ORDER BY path')
        file_ids = [row[0] for row in self.cursor.fetchall()]
        return [self.get_file(file_id) for file_id in file_ids]

    def get_files_with_tags(self, whitelist: Iterable[str], blacklist: Iterable[str]) -> List[File]:
        self.cursor.execute('SELECT id FROM files WHERE id IN (SELECT file_id FROM file_has_tag WHERE tag_id IN (SELECT id FROM tags WHERE name IN (?))) AND id NOT IN (SELECT file_id FROM file_has_tag WHERE tag_id IN (SELECT id FROM tags WHERE name IN (?)))', (whitelist, blacklist))
        file_ids = [row[0] for row in self.cursor.fetchall()]
        return [self.get_file(file_id) for file_id in file_ids]

    def add_file(self, file: File) -> int:
        self.cursor.execute('SELECT id FROM files WHERE path = ?', (file.path,))
        if self.cursor.fetchone() is not None:
            return -1  # File already exists
        self.cursor.execute('INSERT INTO files (path, size, date_modified, duration, rating) VALUES (?, ?, ?, ?, ?)', (file.path, file.size, file.date_modified.isoformat(), file.duration, file.rating))
        file_id = self.cursor.lastrowid
        for tag in file.tags:
            self.set_tag(file_id, tag)
        self.conn.commit()
        return file_id
    
    def get_tags(self) -> Dict[str, int]:
        self.cursor.execute('SELECT name, COUNT(file_has_tag.tag_id) FROM tags LEFT JOIN file_has_tag ON tags.id = file_has_tag.tag_id GROUP BY tags.id')
        return {row[0]: row[1] for row in self.cursor.fetchall()}

    def add_tag(self, tad_name: str):
        self.cursor.execute('INSERT INTO tags (name) VALUES (?)', (tad_name,))
        self.conn.commit()
    
    def set_tag(self, file_id: int, tag: str):
        self.cursor.execute('SELECT id FROM tags WHERE name = ?', (tag,))
        tag_id = self.cursor.fetchone()
        if tag_id is None:
            self.cursor.execute('INSERT INTO tags (name) VALUES (?)', (tag,))
            tag_id = self.cursor.lastrowid
        else:
            tag_id = tag_id[0]
        self.cursor.execute('SELECT 1 FROM file_has_tag WHERE file_id = ? AND tag_id = ?', (file_id, tag_id))
        if self.cursor.fetchone() is None:
            self.cursor.execute('INSERT INTO file_has_tag (file_id, tag_id) VALUES (?, ?)', (file_id, tag_id))
            self.conn.commit()
    
    def remove_tag(self, file_id: int, tag: str):
        self.cursor.execute('SELECT id FROM tags WHERE name = ?', (tag,))
        tag_id = self.cursor.fetchone()
        if tag_id is None:
            return
        tag_id = tag_id[0]
        self.cursor.execute('DELETE FROM file_has_tag WHERE file_id = ? AND tag_id = ?', (file_id, tag_id))
        self.conn.commit()
    
    def delete_tag(self, tag: str):
        self.cursor.execute('SELECT id FROM tags WHERE name = ?', (tag,))
        tag_id = self.cursor.fetchone()
        if tag_id is None:
            return
        tag_id = tag_id[0]
        self.cursor.execute('DELETE FROM file_has_tag WHERE tag_id = ?', (tag_id,))
        self.cursor.execute('DELETE FROM tags WHERE id = ?', (tag_id,))
        self.conn.commit()

    def set_rating(self, file_id: int, rating: int|None):
        self.cursor.execute('UPDATE files SET rating = ? WHERE id = ?', (rating, file_id))
        self.conn.commit()

    def remove_file(self, file_id: int):
        self.cursor.execute('DELETE FROM file_has_tag WHERE file_id = ?', (file_id,))
        self.cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
        self.conn.commit()

    def get_setting(self, key: str, default: str|None = None) -> str|None:
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

        self.file_list.setContextMenuPolicy(Qt.ActionsContextMenu)
        self.file_list_context_menu = QMenu(self)

        for i, header in list(enumerate(self.file_list_model.horizontal_header_labels))[1:]:
            action = QAction(header, self.file_list)
            column_visible = self.database.get_setting(f'column_visibility_{header}', str(True)) == 'True'
            action.setCheckable(True)
            action.setChecked(column_visible)
            self.file_list.setColumnHidden(i, not column_visible)
            action.toggled.connect(lambda checked, col=i: self.toggle_column_visibility(col, checked))
            self.file_list_context_menu.addAction(action)

        self.file_list.setContextMenuPolicy(Qt.CustomContextMenu)
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
        self.tag_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tag_list.customContextMenuRequested.connect(self.show_tag_list_context_menu)

        self.add_tag_layout = QHBoxLayout()
        self.right_layout.addLayout(self.add_tag_layout)
        self.add_tag_edit = QLineEdit()
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
        if dialog.result() == QDialog.Accepted:
            for file_path in dialog.found_files:
                try:
                    size = os.path.getsize(file_path)
                    date_modified = datetime.fromtimestamp(os.path.getmtime(file_path))
                    self.database.add_file(Database.File(None, file_path, size, date_modified))
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

    def get_video_duration(self, file_path):
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return float(result.stdout)

    def load_files(self):
        files = self.database.get_files()
        self.file_list_model = FileListModel(files)
        proxy_model = FileSortFilterProxyModel()
        proxy_model.setSourceModel(self.file_list_model)
        self.file_list.setModel(proxy_model)
        
        self.file_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.file_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.file_list.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.file_list.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.file_list.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.file_list.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    def load_tags(self):
        tags = self.database.get_tags()
        self.tag_list_model = TagListModel(tags)
        proxy_model = QSortFilterProxyModel()
        proxy_model.setSourceModel(self.tag_list_model)
        self.tag_list.setModel(proxy_model)

        self.tag_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tag_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tag_list.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
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

    def on_file_selected(self, selected, deselected):
        indexes = selected.indexes()
        if indexes:
            self.selected_file = indexes[0].data(Qt.UserRole)
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
            self.file_list_model.dataChanged.emit(self.file_list_model.index(index.row(), 0), self.file_list_model.index(index.row(), self.file_list_model.columnCount() - 1))

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
        file = self.files[index.row()]
        if role == Qt.DisplayRole:
            if index.column() == 0:
                return os.path.basename(file.path).split('.')[0]
            if index.column() == 1:
                if file.rating:
                    return '★' * file.rating + '☆' * (5 - file.rating)
                else:
                    return None
            elif index.column() == 2:
                return humanize.naturalsize(file.size)
            elif index.column() == 3:
                return file.date_modified.strftime('%Y-%m-%d %H:%M:%S')
            elif index.column() == 4:
                return str(file.duration)
        elif role == Qt.UserRole:
            return file
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.horizontal_header_labels[section]
        return None

class StarRatingWidget(QWidget):
    rating_changed = Signal(int)
    
    def __init__(self, font_size, parent=None):
        super().__init__(parent)
        self._rating: int|None = None
        self.hovered_star: int|None = None
        self.stars: List[QLabel] = []
        self.font_size: int = font_size
        self.init_ui()

    def star_mouse_event(self, i: int):
        def event(event: QMouseEvent):
            if event.type() == QEvent.Enter:
                self.hovered_star = i
                self._update()
            elif event.type() == QEvent.Leave:
                self.hovered_star = None
                self._update()
            elif event.type() == QEvent.MouseButtonPress:
                self._set_rating(i + 1)
        return event

    def init_ui(self):
        layout = QHBoxLayout()
        for i in range(5):
            star = QLabel()
            star.mousePressEvent = self.star_mouse_event(i)
            star.enterEvent = self.star_mouse_event(i)
            star.leaveEvent = self.star_mouse_event(i)
            star.setSizePolicy(QSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed))
            layout.addWidget(star)
            self.stars.append(star)
        self.setLayout(layout)
        self._update()

    def _set_rating(self, rating: int|None):
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
        self.star_rating_widget = StarRatingWidget(10, self.parent())
        
    def paint(self, painter, option, index):
        file: Database.File = index.data(Qt.UserRole)
        self.star_rating_widget.rating = file.rating
        self.star_rating_widget.setGeometry(option.rect)
        self.star_rating_widget.resize(option.rect.size())
        painter.save()
        painter.translate(option.rect.topLeft())
        self.star_rating_widget.render(painter, QPoint(0, 0))
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(100, 20)


class FileSortFilterProxyModel(QSortFilterProxyModel):
    def lessThan(self, left, right):
        if self.sortColumn() != 1:  # Not size column
            return super().lessThan(left, right)

        left_file = self.sourceModel().files[left.row()]
        right_file = self.sourceModel().files[right.row()]
    
        return left_file.size < right_file.size


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

    def data(self, index, role = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        tag_name = self.tag_names[index.row()]
        if role == Qt.DisplayRole:
            if index.column() == 1:
                return tag_name
            elif index.column() == 2:
                return str(self.tags[tag_name])
        elif role == Qt.CheckStateRole and index.column() == 0:
            return Qt.Checked if tag_name in self.checked_tags else Qt.Unchecked
        return None

    def setData(self, index, value, role):
        if role == Qt.CheckStateRole and index.column() == 0:
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
            return Qt.NoItemFlags
        if index.column() == 0:
            return Qt.ItemIsEnabled | Qt.ItemIsUserCheckable
        return Qt.ItemIsEnabled

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
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
    def current_file(self, file: Database.File|None):
        if file is None:
            self.checked_tags.clear()
        self._current_file = file
        self.checked_tags = file.tags
        self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))
    
    def set_tag(self, tag_name: str):
        if tag_name not in self.tags:
            self.beginInsertRows(QModelIndex(), self.rowCount(), self.rowCount())
            self.tags[tag_name] = 0
            self.tag_names.append(tag_name)
            self.endInsertRows()
        if self.current_file:
            if tag_name not in self.current_file.tags:
                self.tags[tag_name] += 1
                self.current_file.tags.add(tag_name)
                self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))



class AddFilesDialog(QDialog):
    default_filter = QDir.Dirs | QDir.NoDotAndDotDot

    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        self.found_files = set()

        self.setWindowTitle("Add Files")
        self.setGeometry(100, 100, 800, 600)

        self.init_ui()

    def init_ui(self):
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)


        # File type filter
        self.file_filter = QLineEdit(self.database.get_setting('scan_file_filter', '.mp4;.avi;.mkv;.mov;.wmv;.flv;.webm;.webp;.mpeg;.mpg;.m4v;.3gp;.vob;.ogv;.ogg;.mxf;.rm;.divx;.xvid'))
        self.file_filter.textChanged.connect(lambda text: self.database.set_setting('scan_file_filter', text))
        self.layout.addWidget(self.file_filter)

        self.file_system_view = QTreeView()
        self.file_system_view_model = QFileSystemModel()
        self.file_system_view.setModel(self.file_system_view_model)
        self.file_system_view_model.setRootPath(QDir.rootPath())
        self.file_system_view_model.setFilter(QDir.Dirs | QDir.NoDotAndDotDot | QDir.Hidden)
        for i in range(1, 4):
            self.file_system_view.hideColumn(i)
        last_used_folder = self.database.get_setting('last_scanned_folder', QDir.homePath())
        last_used_index = self.file_system_view_model.index(last_used_folder)
        self.file_system_view.scrollTo(last_used_index)
        self.file_system_view.selectionModel().setCurrentIndex(last_used_index, QItemSelectionModel.SelectionFlag.Select)
        self.file_system_view.setExpanded(last_used_index, True)
        self.file_system_view.setContextMenuPolicy(Qt.ActionsContextMenu)
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
        show = not self.file_system_view_model.filter() & QDir.Hidden
        self.show_hidden_files(show)
        self.database.set_setting('show_hidden_files', str(show))
    
    def show_hidden_files(self, show: bool):
        if show:
            self.file_system_view_model.setFilter(AddFilesDialog.default_filter | QDir.Hidden)
        else:
            self.file_system_view_model.setFilter(AddFilesDialog.default_filter)

    def scan_directory(self):
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
                return

            def run(self):
                self.scan()
                self.finished.emit()
        
        scan_root = self.file_system_view_model.filePath(self.file_system_view.currentIndex())
        self.database.set_setting('last_scanned_folder', scan_root)
        self.scan_directory_button.setEnabled(False)
        self.abort_scan_button.setEnabled(True)
        self.accept_button.setEnabled(False)
        self.status_label.setText("Scanning directory...")
        self.scan_worker = ScanWorker(scan_root, self.file_filter.text())
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
        self.scan_worker_thread.quit()
        self.scan_worker_thread.wait()
        self.status_label.setText("Scan aborted")
        

def resolve_symlink(path):
    if os.path.islink(path):
        return resolve_symlink(os.path.realpath(path))
    return path
        

def main():
    app = QApplication([])
    main_window = MainWindow()
    main_window.showMaximized()
    QApplication.exec()

if __name__ == '__main__':
    main()
