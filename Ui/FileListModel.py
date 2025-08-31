from typing import List

import humanfriendly
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QFont

from VideoFile import VideoFile


class FileListModel(QAbstractTableModel):
    def __init__(self, files: List[VideoFile]):
        super().__init__()
        self.files = files
        self.horizontal_header_labels = ['Name', 'Rating', 'Tags', 'Size', 'Modified', 'Duration']
        self._current_playing: VideoFile | None = None

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
                return file_object.name_prefix
            if index.column() == 1:
                if file_object.rating:
                    return '★' * file_object.rating + '☆' * (5 - file_object.rating)
                else:
                    return None
            elif index.column() == 2:
                return len(file_object.tags)
            elif index.column() == 3:
                return humanfriendly.format_size(file_object.size)
            elif index.column() == 4:
                return file_object.date_modified.strftime('%Y-%m-%d %H:%M:%S')
            elif index.column() == 5:
                return str(file_object.duration)
        elif role == Qt.ItemDataRole.FontRole:
            if file_object == self._current_playing:
                font = QFont()
                font.setBold(True)
                font.setItalic(True)
                return font
            return None
        elif role == Qt.ItemDataRole.DisplayRole.UserRole:
            return file_object
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.horizontal_header_labels[section]
        return None

    def set_files(self, files: List[VideoFile]):
        self.beginResetModel()
        self.files = files
        self.endResetModel()

    def on_file_modified(self, file: VideoFile):
        index = self.index(self.files.index(file), 0)
        if index and index.isValid():
            self.dataChanged.emit(self.index(index.row(), 0),
                                  self.index(index.row(), self.columnCount() - 1))

    def on_tag_renamed(self, old_name: str, new_name: str):
        for file in self.files:
            if old_name in file.tags:
                file.tags.remove(old_name)
                file.tags.add(new_name)
        self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))

    @property
    def playing_file(self):
        return self._current_playing

    @playing_file.setter
    def playing_file(self, file: VideoFile | None):
        last_playing = self._current_playing
        self._current_playing = file
        if last_playing:
            self.on_file_modified(last_playing)
        if file:
            self.on_file_modified(file)

    def set_playing_file(self, file: VideoFile | None):
        self.playing_file = file
