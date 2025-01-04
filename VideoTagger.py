#!/usr/bon/env python

import humanize
import sqlite3

from PySide6.QtCore import Qt, QMargins, QTimer, QSize, QRect, QProcess, Signal, QObject, QSortFilterProxyModel, QAbstractItemModel, QModelIndex
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QListView, QTableView, QMainWindow, QSizePolicy, QVBoxLayout, QHBoxLayout, QWidget, QSlider

from __feature__ import snake_case, true_property
from dataclasses import dataclass
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
        self.vlc_process.set_program("vlc")
        self.vlc_process.set_arguments(["--extraintf", "rc"])
        self.vlc_process.start()
        self.vlc_process.wait_for_started()
        self._read_stdout()

    def _read_stdout(self):
        data = b''
        while True:
            self.vlc_process.wait_for_ready_read()
            data += self.vlc_process.read_all_standard_output().data()
            if data.endswith(b'> ') or self.vlc_process.state() == QProcess.ProcessState.NotRunning:
                return data[:-2].strip()

    def send(self, command):
        self.vlc_process.write(f'{command}\n'.encode())
        self.vlc_process.wait_for_bytes_written()
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
        duration: float
        tags: set[str]

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
            duration FLOAT
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
        self.cursor.execute('SELECT path, size, date_created, duration FROM files WHERE id = ?', (file_id,))
        path, size, date_created, duration = self.cursor.fetchone()
        self.cursor.execute('SELECT name FROM tags INNER JOIN file_has_tag ON tags.id = file_has_tag.tag_id WHERE file_has_tag.file_id = ?', (file_id,))
        tags = {tag_row[0] for tag_row in self.cursor.fetchall()}
        return self.File(file_id, path, size, datetime.fromisoformat(date_created), duration, tags)

    def get_files(self) -> List[File]:
        self.cursor.execute('SELECT id FROM files ORDER BY path')
        file_ids = [row[0] for row in self.cursor.fetchall()]
        return [self.get_file(file_id) for file_id in file_ids]

    def get_files_with_tags(self, whitelist: Iterable[str], blacklist: Iterable[str]) -> List[File]:
        self.cursor.execute('SELECT id FROM files WHERE id IN (SELECT file_id FROM file_has_tag WHERE tag_id IN (SELECT id FROM tags WHERE name IN (?))) AND id NOT IN (SELECT file_id FROM file_has_tag WHERE tag_id IN (SELECT id FROM tags WHERE name IN (?)))', (whitelist, blacklist))
        file_ids = [row[0] for row in self.cursor.fetchall()]
        return [self.get_file(file_id) for file_id in file_ids]

    def add_file(self, path: str, size: int, date_created: datetime, duration: float|None = None) -> int:
        self.cursor.execute('INSERT INTO files (path, size, date_created, duration) VALUES (?, ?, ?, ?)', (path, size, date_created, duration))
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

    def remove_file(self, file_id: int):
        self.cursor.execute('DELETE FROM file_has_tag WHERE file_id = ?', (file_id,))
        self.cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
        self.conn.commit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.set_window_title("Video Tagger")
        self.geometry = QRect(100, 100, 800, 600)

        self.vlc = VlcPlayer()

        self.database = Database('VideoTagger.db')

        self._init_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_vlc_status)
        self.timer.start(1000)
    
    def _init_ui(self):
        self.central_widget = QWidget()
        self.layout = QHBoxLayout()
        self.central_widget.set_layout(self.layout)
        self.set_central_widget(self.central_widget)
        self.file_list = QTableView()
        self.file_list.selection_behavior = QTableView.SelectionBehavior.SelectRows
        self.file_list.selection_mode = QTableView.SelectionMode.SingleSelection
        self.file_list.horizontal_header().stretch_last_section = True
        self.file_list.vertical_header().hide()
        self.file_list.show_grid = False
        self.file_list.sections_clickable = True
        self.file_list.sorting_enabled = True
        self.layout.add_widget(self.file_list)
        self.load_files()

        self.tag_list = QListView()
        self.layout.add_widget(self.tag_list)
        self.load_tags()

        self.file_list.selection_model().selectionChanged.connect(self.on_file_selected)

        self.scan_button = QPushButton("Scan Directory")
        self.scan_button.clicked.connect(self.scan_directory)
        self.layout.add_widget(self.scan_button)
        
    def scan_directory(self):
        directory = QFileDialog.get_existing_directory(self, "Select Directory")
        if directory:
            self.scan_files(directory)
        
    def scan_files(self, directory):
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(('.mp4', '.avi', '.mkv')):
                    file_path = os.path.join(root, file)
                    size = os.path.getsize(file_path)
                    date_created = datetime.fromtimestamp(os.path.getctime(file_path))
                    #duration = self.get_video_duration(file_path)
                    self.database.add_file(file_path, size, date_created, None)
        self.load_files()

    def get_video_duration(self, file_path):
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return float(result.stdout)

    def load_files(self):
        files = self.database.get_files()
        model = FileListModel(files)
        proxy_model = FileSortFilterProxyModel()
        proxy_model.set_source_model(model)
        self.file_list.set_model(proxy_model)

    def load_tags(self):
        tags = self.database.get_tags()
        model = QStandardItemModel()
        for tag in tags:
            item = QStandardItem(tag)
            model.append_row(item)
        self.tag_list.set_model(model)

    def on_file_selected(self, selected, deselected):
        indexes = selected.indexes()
        if indexes:
            file_id = indexes[0].data(Qt.UserRole)
            file = self.database.get_file(file_id)
            self.vlc.play_video(file.path)

    def update_vlc_status(self):
        self.vlc.update_status()

    def close_event(self, event):
        self.vlc.close()
        event.accept()


class FileListModel(QAbstractItemModel):
    def __init__(self, files: List[Database.File]):
        super().__init__()
        self.files = files
        self.horizontal_header_labels = ['Name', 'Size', 'Created', 'Duration']

    def row_count(self, parent=QModelIndex()):
        return len(self.files)

    def column_count(self, parent=QModelIndex()):
        return len(self.horizontal_header_labels)

    def data(self, index, role):
        if not index.is_valid():
            return None
        file = self.files[index.row()]
        if role == Qt.DisplayRole:
            if index.column() == 0:
                return os.path.basename(file.path)
            elif index.column() == 1:
                return humanize.naturalsize(file.size)
            elif index.column() == 2:
                return file.date_created.strftime('%Y-%m-%d %H:%M:%S')
            elif index.column() == 3:
                return str(file.duration)
        elif role == Qt.UserRole:
            return file.id
        return None

    def header_data(self, section, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.horizontal_header_labels[section]
        return None

    def index(self, row, column, parent=QModelIndex()):
        if self.has_index(row, column, parent):
            return self.create_index(row, column)
        return QModelIndex()

    def parent(self, index):
        return QModelIndex()


class FileSortFilterProxyModel(QSortFilterProxyModel):
    def less_than(self, left, right):
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
