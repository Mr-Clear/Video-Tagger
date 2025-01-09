import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Tuple

from PySide6.QtCore import QSortFilterProxyModel

from VideoFile import VideoFile
from Ui.FileListModel import FileListModel


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
        self._current_file: VideoFile | None = None
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
    def current_file(self, file: VideoFile | None):
        self._current_file = file

    def set_current_file(self, file: VideoFile | None):
        self.current_file = file
