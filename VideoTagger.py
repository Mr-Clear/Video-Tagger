#!/usr/bon/env python

import humanize
import sqlite3

from PySide6.QtCore import Qt, QMargins, QTimer, QSize, QRect, QProcess, Signal, QObject, QSortFilterProxyModel, QAbstractItemModel, QModelIndex, QEvent, QPoint
from PySide6.QtGui import QStandardItemModel, QStandardItem, QMouseEvent
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QListView, QTableView, QMainWindow, QSizePolicy, QVBoxLayout, QHBoxLayout, QWidget, QSlider, QLineEdit, QStyledItemDelegate

from dataclasses import dataclass, field
from typing import Iterable, Set, List
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
        date_created: datetime
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
            date_created TIMESTAMP NOT NULL,
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
    
    def close(self):
        self.conn.close()
    
    def get_file(self, file_id: int) -> File:
        self.cursor.execute('SELECT path, size, date_created, duration, rating FROM files WHERE id = ?', (file_id,))
        path, size, date_created, duration, rating = self.cursor.fetchone()
        self.cursor.execute('SELECT name FROM tags INNER JOIN file_has_tag ON tags.id = file_has_tag.tag_id WHERE file_has_tag.file_id = ?', (file_id,))
        tags = {tag_row[0] for tag_row in self.cursor.fetchall()}
        return self.File(file_id, path, size, datetime.fromisoformat(date_created), duration, rating, tags)

    def get_files(self) -> List[File]:
        self.cursor.execute('SELECT id FROM files ORDER BY path')
        file_ids = [row[0] for row in self.cursor.fetchall()]
        return [self.get_file(file_id) for file_id in file_ids]

    def get_files_with_tags(self, whitelist: Iterable[str], blacklist: Iterable[str]) -> List[File]:
        self.cursor.execute('SELECT id FROM files WHERE id IN (SELECT file_id FROM file_has_tag WHERE tag_id IN (SELECT id FROM tags WHERE name IN (?))) AND id NOT IN (SELECT file_id FROM file_has_tag WHERE tag_id IN (SELECT id FROM tags WHERE name IN (?)))', (whitelist, blacklist))
        file_ids = [row[0] for row in self.cursor.fetchall()]
        return [self.get_file(file_id) for file_id in file_ids]

    def add_file(self, path: str, size: int, date_created: datetime, duration: float | None = None, rating: int | None = None) -> int:
        self.cursor.execute('INSERT INTO files (path, size, date_created, duration, rating) VALUES (?, ?, ?, ?, ?)', (path, size, date_created, duration, rating))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def get_tags(self) -> list[str]:
        self.cursor.execute('SELECT name FROM tags ORDER BY name')
        return [row[0] for row in self.cursor.fetchall()]
    
    def set_tag(self, file_id: int, tag: str):
        self.cursor.execute('SELECT id FROM tags WHERE name = ?', (tag,))
        tag_id = self.cursor.fetchone()
        if tag_id is None:
            self.cursor.execute('INSERT INTO tags (name) VALUES (?)', (tag,))
            tag_id = self.cursor.lastrowid
        else:
            tag_id = tag_id[0]
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

    def set_rating(self, file_id: int, rating: int|None):
        self.cursor.execute('UPDATE files SET rating = ? WHERE id = ?', (rating, file_id))
        self.conn.commit()

    def remove_file(self, file_id: int):
        self.cursor.execute('DELETE FROM file_has_tag WHERE file_id = ?', (file_id,))
        self.cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
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
        self.file_list.horizontalHeader().setStretchLastSection = True
        self.file_list.verticalHeader().hide()
        self.file_list.show_grid = False
        self.file_list.sections_clickable = True
        self.file_list.sorting_enabled = True
        self.left_layout.addWidget(self.file_list)
        self.load_files()
        self.file_list.selectionModel().selectionChanged.connect(self.on_file_selected)
        self.file_list.setItemDelegateForColumn(1, StarRatingDelegate(self.file_list))

        self.scan_button = QPushButton("Scan Directory")
        self.scan_button.clicked.connect(self.scan_directory)
        self.left_layout.addWidget(self.scan_button)

        self.right_layout = QVBoxLayout()
        self.main_layout.addLayout(self.right_layout)

        self.tag_list = QTableView()
        self.right_layout.addWidget(self.tag_list)
        self.load_tags()

        self.add_tag_layout = QHBoxLayout()
        self.right_layout.addLayout(self.add_tag_layout)
        self.add_tag_edit = QLineEdit()
        self.add_tag_layout.addWidget(self.add_tag_edit)
        self.add_tag_button = QPushButton("Add")
        self.add_tag_button.clicked.connect(self.add_tag)
        self.add_tag_layout.addWidget(self.add_tag_button)

        self.rating_widget = StarRatingWidget(20, None, self)
        self.rating_widget.rating_changed.connect(self.set_rating)
        self.right_layout.addWidget(self.rating_widget)

    def scan_directory(self):
        directory = QFileDialog.get_existing_directory(self, "Select Directory")
        if directory:
            self.scan_files(directory)
    
    def add_tag(self):
        if self.selected_file is not None:
            tag = self.add_tag_edit.text()
            self.database.set_tag(self.selected_file.id, tag)
            self.add_tag_edit.clear()
    
        
    def scan_files(self, directory):
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(('.mp4', '.avi', '.mkv')):
                    file_path = os.path.join(root, file)
                    size = os.path.getsize(file_path)
                    date_created = datetime.fromtimestamp(os.path.getctime(file_path))
                    self.database.add_file(file_path, size, date_created, None)
        self.load_files()

    def get_video_duration(self, file_path):
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return float(result.stdout)

    def load_files(self):
        files = self.database.get_files()
        self.file_list_model = FileListModel(files)
        proxy_model = FileSortFilterProxyModel()
        proxy_model.setSourceModel(self.file_list_model)
        self.file_list.setModel(proxy_model)

    def load_tags(self):
        tags = self.database.get_tags()
        model = QStandardItemModel()
        for tag in tags:
            item = QStandardItem(tag)
            model.append_row(item)
        self.tag_list.setModel(model)

    def on_file_selected(self, selected, deselected):
        indexes = selected.indexes()
        if indexes:
            self.selected_file = self.file_list_model.files[indexes[0].row()]
            self.vlc.play_video(self.selected_file.path)
            self.rating_widget.rating = self.selected_file.rating
        else:
            self.selected_file = None
            self.rating_widget.rating = None

    def update_vlc_status(self):
        self.vlc.update_status()

    def set_rating(self, rating):
        if self.selected_file is not None:
            self.database.set_rating(self.selected_file.id, rating)
            self.selected_file.rating = rating
            self.on_current_file_modified()

    def on_current_file_modified(self):
        index = self.file_list.selectionModel().selection().indexes()[0]
        if index and index.isValid():
            self.file_list_model.dataChanged.emit(self.file_list_model.index(index.row(), 0), self.file_list_model.index(index.row(), self.file_list_model.columnCount() - 1))

    def close_event(self, event):
        self.vlc.close()
        event.accept()


class FileListModel(QAbstractItemModel):
    def __init__(self, files: List[Database.File]):
        super().__init__()
        self.files = files
        self.horizontal_header_labels = ['Name', 'Rating', 'Size', 'Created', 'Duration']

    def rowCount(self, parent=QModelIndex()):
        return len(self.files)

    def columnCount(self, parent=QModelIndex()):
        return len(self.horizontal_header_labels)

    def data(self, index, role):
        if not index.isValid():
            return None
        file = self.files[index.row()]
        if role == Qt.DisplayRole:
            if index.column() == 0:
                return os.path.basename(file.path).split('.')[0]
            if index.column() == 1:
                return None if file.rating is None else str(file.rating)
            elif index.column() == 2:
                return humanize.naturalsize(file.size)
            elif index.column() == 3:
                return file.date_created.strftime('%Y-%m-%d %H:%M:%S')
            elif index.column() == 4:
                return str(file.duration)
        elif role == Qt.UserRole:
            return file
        return None

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.horizontal_header_labels[section]
        return None

    def index(self, row, column, parent=QModelIndex()):
        if self.hasIndex(row, column, parent):
            return self.createIndex(row, column)
        return QModelIndex()

    def parent(self, index):
        return QModelIndex()

class StarRatingWidget(QWidget):
    rating_changed = Signal(int)
    
    def __init__(self, font_size, rating: int|None, parent=None):
        super().__init__(parent)
        self._rating = rating
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
        
    def paint(self, painter, option, index):
        file: Database.File = index.data(Qt.UserRole)
        star_rating_widget = StarRatingWidget(10, file.rating, self.parent())
        star_rating_widget.setGeometry(option.rect)
        star_rating_widget.render(painter, self.parent().mapTo(self.parent().window(), option.rect.topLeft()) + QPoint(0, 26))
        #star_rating_widget.render(painter, option.rect.topLeft())

class FileSortFilterProxyModel(QSortFilterProxyModel):
    def lessThan(self, left, right):
        if self.sort_column() != 1:  # Not size column
            return super().less_than(left, right)

        left_file = self.source_model.files[left.row()]
        right_file = self.source_model.files[right.row()]
    
        return left_file.size < right_file.size


def main():
    app = QApplication([])
    main_window = MainWindow()
    main_window.show()
    QApplication.exec()

if __name__ == '__main__':
    main()
