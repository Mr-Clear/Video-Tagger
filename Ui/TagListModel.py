from typing import Dict

from PySide6.QtCore import QAbstractTableModel, Signal, QModelIndex, Qt

from VideoFile import VideoFile


class TagListModel(QAbstractTableModel):
    tag_set = Signal(int, str)
    tag_removed = Signal(int, str)

    def __init__(self, tags: Dict[str, int]):
        super().__init__()
        self.tags = tags
        self.tag_names = list(tags.keys())
        self.checked_tags = set()
        self._current_file: VideoFile | None = None

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
                return self.tags[tag_name]
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
    def current_file(self, file: VideoFile | None):
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
