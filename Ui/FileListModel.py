import os
from typing import List

import humanfriendly
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from VideoFile import VideoFile


class FileListModel(QAbstractTableModel):
    def __init__(self, files: List[VideoFile]):
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

    def set_files(self, files: List[VideoFile]):
        self.beginResetModel()
        self.files = files
        self.endResetModel()
