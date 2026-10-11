import subprocess
from typing import List

import humanfriendly
from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QObject,
                            QRunnable, Qt, QThreadPool, Signal, Slot)
from PySide6.QtGui import QFont

from VideoFile import VideoFile


class DurationProbeSignals(QObject):
    finished = Signal(str, object)


class DurationProbe(QRunnable):
    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path
        self.signals = DurationProbeSignals()

    def run(self):
        duration = None
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', self.file_path],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            duration = float(result.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        self.signals.finished.emit(self.file_path, duration)


class FileListModel(QAbstractTableModel):
    duration_loaded = Signal(VideoFile)

    def __init__(self, files: List[VideoFile]):
        super().__init__()
        self.files = files
        self.horizontal_header_labels = ['Name', 'Rating', 'Tags', 'Size', 'Modified', 'Duration', 'Bitrate']
        self._current_playing: VideoFile | None = None
        self._duration_pool = QThreadPool(self)
        self._duration_pool.setMaxThreadCount(1)
        self._duration_running = set()
        self._duration_attempted = set()
        self._visible_paths = set()

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
                if file_object.duration is not None:
                    return self._format_duration(file_object.duration)
                if file_object.path in self._duration_running:
                    return 'Reading...'
                return ''
            elif index.column() == 6:
                bitrate = file_object.bitrate
                if bitrate is None:
                    return ''
                if bitrate >= 1_000_000:
                    return f'{bitrate / 1_000_000:.2f} Mb/s'
                return f'{bitrate / 1_000:.0f} kb/s'
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

    def add_file(self, file: VideoFile):
        row = len(self.files)
        self.beginInsertRows(QModelIndex(), row, row)
        self.files.append(file)
        self.endInsertRows()

    def remove_file(self, file: VideoFile):
        row = self.files.index(file)
        self.beginRemoveRows(QModelIndex(), row, row)
        self.files.pop(row)
        self.endRemoveRows()

    def request_visible_durations(self, files: list[VideoFile]):
        self._visible_paths = {file.path for file in files}
        self._start_duration_probes()

    def queue_remaining_durations(self):
        self._start_duration_probes()

    def _next_duration_path(self):
        candidates = [file for file in self.files if file.path in self._visible_paths]
        candidates.extend(file for file in self.files if file.path not in self._visible_paths)
        for file in candidates:
            if (file.duration is None and file.path not in self._duration_attempted and
                    file.path not in self._duration_running):
                return file.path
        return None

    def _start_duration_probes(self):
        if self._duration_running:
            return
        file_path = self._next_duration_path()
        if file_path is None:
            return
        self._duration_running.add(file_path)
        self._emit_duration_changed(file_path)
        probe = DurationProbe(file_path)
        probe.signals.finished.connect(self._on_duration_loaded)
        self._duration_pool.start(probe)

    @staticmethod
    def _format_duration(duration: float) -> str:
        hours, remainder = divmod(duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f'{int(hours):02}:{int(minutes):02}:{int(seconds):02}'

    def _emit_duration_changed(self, file_path: str):
        file = next((file for file in self.files if file.path == file_path), None)
        if file is not None:
            row = self.files.index(file)
            self.dataChanged.emit(self.index(row, 5), self.index(row, 6), [Qt.ItemDataRole.DisplayRole])

    @Slot(str, object)
    def _on_duration_loaded(self, file_path: str, duration: float | None):
        self._duration_running.discard(file_path)
        self._duration_attempted.add(file_path)
        file = next((file for file in self.files if file.path == file_path), None)
        if file is not None:
            if duration is not None:
                file.duration = duration
            self._emit_duration_changed(file_path)
            if duration is not None:
                self.duration_loaded.emit(file)
        self._start_duration_probes()

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
