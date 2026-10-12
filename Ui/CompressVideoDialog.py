import os
from dataclasses import dataclass, field, replace
from enum import Enum

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QProcess, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QMenu, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QProgressBar, QLabel)

from Ui.MediaProbe import MediaProbe, format_size, probe_video_height, summarize_metadata
from VideoFile import VideoFile

# format name -> (extension, video codec, audio codec)
FORMATS = {
    'MP4 (H.264)': ('mp4', 'libx264', 'aac'),
    'MP4 (H.265)': ('mp4', 'libx265', 'aac'),
    'MKV (H.265)': ('mkv', 'libx265', 'aac'),
    'WebM (VP9)': ('webm', 'libvpx-vp9', 'libopus'),
}

# label -> target height (None keeps the original)
RESOLUTIONS = {
    'Original': None,
    '2160p': 2160,
    '1440p': 1440,
    '1080p': 1080,
    '720p': 720,
    '480p': 480,
    '360p': 360,
}

PRESETS = ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow']


class JobState(Enum):
    PENDING = 'Pending'
    QUEUED = 'Queued'
    RUNNING = 'Running'
    DONE = 'Done'
    FAILED = 'Failed'
    CANCELLED = 'Cancelled'


@dataclass
class CompressionOptions:
    format_name: str
    height: int | None
    crf: int
    preset: str
    audio_bitrate_kbps: int


@dataclass
class CompressionJob:
    source: str
    target: str
    duration: float | None
    options: CompressionOptions
    source_size: int | None = None
    compressed_size: int | None = None
    state: JobState = JobState.PENDING
    progress: int = 0
    error: str = ''
    row_widgets: dict = field(default_factory=dict)


def build_ffmpeg_args(job: CompressionJob, source_height: int | None) -> list[str]:
    ext, vcodec, acodec = FORMATS[job.options.format_name]
    args = ['-hide_banner', '-nostdin', '-y', '-progress', 'pipe:1', '-nostats', '-i', job.source,
            '-c:v', vcodec, '-crf', str(job.options.crf)]
    if vcodec == 'libvpx-vp9':
        args += ['-b:v', '0']
    elif vcodec in ('libx264', 'libx265'):
        args += ['-preset', job.options.preset]
    if job.options.height is not None and (source_height is None or source_height > job.options.height):
        args += ['-vf', f'scale=-2:{job.options.height}']
    args += ['-c:a', acodec, '-b:a', f'{job.options.audio_bitrate_kbps}k']
    if ext == 'mp4':
        args += ['-movflags', '+faststart']
    args.append(job.target)
    return args


def unique_target_path(source: str, ext: str) -> str:
    base = os.path.splitext(source)[0] + '_compressed'
    candidate = f'{base}.{ext}'
    n = 2
    while os.path.exists(candidate):
        candidate = f'{base}_{n}.{ext}'
        n += 1
    return candidate


class CompressVideoDialog(QDialog):
    """Non-modal dialog with a persistent queue; jobs run one at a time in the background."""

    file_compressed = Signal(str)
    file_selected = Signal(object)
    file_activated = Signal(str)
    compressed_output_activated = Signal(str)
    compressed_output_selected = Signal(str)
    compressed_output_delete_requested = Signal(object)
    compressed_output_replace_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Compress Video')
        self.setMinimumSize(700, 500)

        self.jobs: list[CompressionJob] = []
        self.current_job: CompressionJob | None = None
        self.process: QProcess | None = None
        self._stdout_buffer = ''
        self._stderr_tail = ''
        self._probe: MediaProbe | None = None
        self._info_paths: list[str] = []
        self._info_cache: dict[str, dict[str, str]] = {}

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._loading_options = False

        self.format_combo = QComboBox()
        self.format_combo.addItems(list(FORMATS))
        self.format_combo.setCurrentText('MP4 (H.265)')
        self.format_combo.currentIndexChanged.connect(self._on_option_changed)
        form.addRow('Format:', self.format_combo)

        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(list(RESOLUTIONS))
        self.resolution_combo.currentIndexChanged.connect(self._on_option_changed)
        form.addRow('Resolution:', self.resolution_combo)

        self.crf_spin = QSpinBox()
        self.crf_spin.setRange(0, 51)
        self.crf_spin.setValue(26)
        self.crf_spin.valueChanged.connect(self._on_option_changed)
        self.crf_spin.setToolTip('Constant rate factor: lower is better quality and larger files.')
        form.addRow('Quality (CRF):', self.crf_spin)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems(PRESETS)
        self.preset_combo.setCurrentText('fast')
        self.preset_combo.currentIndexChanged.connect(self._on_option_changed)
        form.addRow('Speed preset:', self.preset_combo)

        self.audio_spin = QSpinBox()
        self.audio_spin.setRange(32, 512)
        self.audio_spin.setSingleStep(32)
        self.audio_spin.setValue(128)
        self.audio_spin.setSuffix(' kbit/s')
        self.audio_spin.valueChanged.connect(self._on_option_changed)
        form.addRow('Audio bitrate:', self.audio_spin)

        info_form = QFormLayout()
        self.info_labels: dict[str, QLabel] = {}
        for name in ('File size', 'Container', 'Duration', 'Resolution', 'Frame rate', 'Bitrate', 'Video', 'Audio'):
            label = QLabel('-')
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            info_form.addRow(f'{name}:', label)
            self.info_labels[name] = label
        self.info_group = QGroupBox('Current file')
        self.info_group.setLayout(info_form)

        top = QHBoxLayout()
        top.addLayout(form, 1)
        top.addWidget(self.info_group, 1)
        layout.addLayout(top)

        self.selection_label = QLabel()
        self.compress_button = QPushButton('Compress Pending')
        self.compress_button.clicked.connect(self._on_compress_clicked)
        row = QHBoxLayout()
        row.addWidget(self.selection_label, 1)
        row.addWidget(self.compress_button)
        layout.addLayout(row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ['File', 'File size', 'Compressed size', 'Settings', 'Status', 'Progress'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(5, 180)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.cellDoubleClicked.connect(self._on_file_activated)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        self.cancel_button = QPushButton('Cancel Selected')
        self.cancel_button.clicked.connect(self._cancel_selected)
        self.cancel_current_button = QPushButton('Cancel Current')
        self.cancel_current_button.clicked.connect(self._cancel_current)
        self.clear_button = QPushButton('Clear Finished')
        self.clear_button.clicked.connect(self._clear_finished)
        close_button = QPushButton('Close')
        close_button.clicked.connect(self.hide)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.cancel_current_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self._refresh_controls()

    def set_files(self, files: list[VideoFile]):
        """Adds the files as pending jobs with the current options and selects them."""
        active = {j.source for j in self.jobs if j.state in (JobState.PENDING, JobState.QUEUED, JobState.RUNNING)}
        options = self._options()
        new_rows = []
        for file in files:
            if file.path in active:
                continue
            active.add(file.path)
            job = CompressionJob(file.path, '', file.duration, replace(options))
            self.jobs.append(job)
            self._add_row(job)
            new_rows.append(len(self.jobs) - 1)
        if new_rows:
            selection = QItemSelection()
            model = self.table.model()
            for row in new_rows:
                selection.select(model.index(row, 0), model.index(row, model.columnCount() - 1))
            self.table.selectionModel().select(
                selection, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
        self._refresh_controls()

    def _selected_jobs(self) -> list[CompressionJob]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self.jobs[r] for r in rows]

    def _editable_selected_jobs(self) -> list[CompressionJob]:
        return [j for j in self._selected_jobs() if j.state == JobState.PENDING]

    def _refresh_controls(self):
        pending = sum(1 for j in self.jobs if j.state == JobState.PENDING)
        self.compress_button.setEnabled(pending > 0)
        self.selection_label.setText(f'{pending} pending file(s). Option changes apply to the selected pending files.')
        self.cancel_current_button.setEnabled(
            self.current_job is not None and self.current_job.state == JobState.RUNNING)
        editable = bool(self._editable_selected_jobs())
        for widget in (self.format_combo, self.resolution_combo, self.crf_spin, self.preset_combo, self.audio_spin):
            widget.setEnabled(editable or not self.jobs)

    def _on_selection_changed(self):
        selected = self._selected_jobs()
        self.file_selected.emit(selected[0].source if selected else None)
        jobs = self._editable_selected_jobs()
        if jobs:
            options = jobs[0].options
            self._loading_options = True
            self.format_combo.setCurrentText(options.format_name)
            self.resolution_combo.setCurrentIndex(list(RESOLUTIONS.values()).index(options.height))
            self.crf_spin.setValue(options.crf)
            self.preset_combo.setCurrentText(options.preset)
            self.audio_spin.setValue(options.audio_bitrate_kbps)
            self._loading_options = False
        self._refresh_controls()
        self._show_file_info()

    def _on_file_activated(self, row: int, _column: int):
        if 0 <= row < len(self.jobs):
            self.file_activated.emit(self.jobs[row].source)

    def _show_context_menu(self, position):
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        if not self.table.selectionModel().isRowSelected(index.row(), index.parent()):
            self.table.selectRow(index.row())
        job = self.jobs[index.row()]
        menu = QMenu(self.table)
        play_original_action = QAction('Play Original', menu)
        play_original_action.setEnabled(os.path.isfile(job.source))
        play_original_action.triggered.connect(lambda: self.file_activated.emit(job.source))
        menu.addAction(play_original_action)

        menu.addSeparator()

        play_action = QAction('Play Compressed Output', menu)
        output_exists = job.state == JobState.DONE and os.path.isfile(job.target)
        play_action.setEnabled(output_exists)
        play_action.triggered.connect(lambda: self.compressed_output_activated.emit(job.target))
        menu.addAction(play_action)

        select_action = QAction('Select Compressed', menu)
        select_action.setEnabled(output_exists)
        select_action.triggered.connect(lambda: self.compressed_output_selected.emit(job.target))
        menu.addAction(select_action)

        delete_action = QAction('Delete Compressed', menu)
        outputs = [j.target for j in self._selected_jobs() if j.state == JobState.DONE and os.path.isfile(j.target)]
        delete_action.setEnabled(bool(outputs))
        delete_action.triggered.connect(lambda: self.compressed_output_delete_requested.emit(outputs))
        menu.addAction(delete_action)

        replace_action = QAction('Replace Original', menu)
        replace_action.setEnabled(bool(outputs))
        replace_action.triggered.connect(lambda: self.compressed_output_replace_requested.emit(outputs))
        menu.addAction(replace_action)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _show_file_info(self):
        self._info_paths = list(dict.fromkeys(j.source for j in self._selected_jobs()))
        if self._probe is not None:
            self._probe.cancel()
            self._probe.deleteLater()
            self._probe = None
        self._probe_next()
        self._refresh_info()

    def _probe_next(self):
        path = next((p for p in self._info_paths if p not in self._info_cache), None)
        if path is None:
            return
        self._probe = MediaProbe(path, self)
        self._probe.failed.connect(lambda _message, path=path: self._on_probe_finished(path, None))
        self._probe.finished.connect(lambda _text, metadata, path=path: self._on_probe_finished(path, metadata))
        self._probe.start()

    def _on_probe_finished(self, path: str, metadata):
        info = summarize_metadata(metadata) if metadata else {}
        try:
            info['File size'] = format_size(os.path.getsize(path))
        except OSError:
            pass
        self._info_cache[path] = info
        if self._probe is not None:
            self._probe.deleteLater()
            self._probe = None
        self._probe_next()
        self._refresh_info()

    def _refresh_info(self):
        if not self._info_paths:
            self._set_info({})
        elif self._info_paths[0] in self._info_cache:
            self._set_info(self._info_cache[self._info_paths[0]], 'Unavailable')
        else:
            self._set_info({}, 'Reading...')

        biggest = None
        biggest_pixels = 0
        biggest_height = None
        for path in self._info_paths:
            resolution = self._info_cache.get(path, {}).get('Resolution')
            if resolution:
                width, _, height = resolution.partition(' x ')
                pixels = int(width) * int(height)
                if pixels > biggest_pixels:
                    biggest, biggest_pixels = resolution, pixels
                biggest_height = max(biggest_height or 0, int(height))
        original = f'Original ({biggest})' if biggest else 'Original'
        self.resolution_combo.setItemText(0, original)

        model = self.resolution_combo.model()
        for i, height in enumerate(RESOLUTIONS.values()):
            too_big = height is not None and biggest_height is not None and height > biggest_height
            model.item(i).setEnabled(not too_big)

    def _set_info(self, info: dict[str, str], placeholder: str = '-'):
        for name, label in self.info_labels.items():
            label.setText(info.get(name, placeholder))

    def _on_option_changed(self, *_):
        if self._loading_options:
            return
        options = self._options()
        for job in self._editable_selected_jobs():
            job.options = replace(options)
            self._update_row(job)

    def _options(self) -> CompressionOptions:
        return CompressionOptions(
            self.format_combo.currentText(),
            list(RESOLUTIONS.values())[self.resolution_combo.currentIndex()],
            self.crf_spin.value(),
            self.preset_combo.currentText(),
            self.audio_spin.value())

    def _on_compress_clicked(self):
        for job in self.jobs:
            if job.state == JobState.PENDING:
                job.state = JobState.QUEUED
                self._update_row(job)
        self._refresh_controls()
        self._start_next()

    def _add_row(self, job: CompressionJob):
        row = self.table.rowCount()
        self.table.insertRow(row)
        name_item = QTableWidgetItem(os.path.basename(job.source))
        name_item.setToolTip(job.source)
        self.table.setItem(row, 0, name_item)
        try:
            job.source_size = os.path.getsize(job.source)
        except OSError:
            job.source_size = None
        self.table.setItem(row, 1, QTableWidgetItem())
        self.table.setItem(row, 2, QTableWidgetItem())
        self.table.setItem(row, 3, QTableWidgetItem())
        self.table.setItem(row, 4, QTableWidgetItem())
        bar = QProgressBar()
        bar.setRange(0, 100)
        self.table.setCellWidget(row, 5, bar)
        job.row_widgets = {'name': name_item, 'bar': bar}
        self._update_row(job)

    def _row_of(self, job: CompressionJob) -> int:
        return self.jobs.index(job)

    def _update_row(self, job: CompressionJob):
        row = self._row_of(job)
        o = job.options
        resolution = next(k for k, v in RESOLUTIONS.items() if v == o.height)
        self.table.item(row, 1).setText(format_size(job.source_size) if job.source_size is not None else '-')
        self.table.item(row, 2).setText(
            format_size(job.compressed_size) if job.compressed_size is not None else '-')
        self.table.item(row, 3).setText(
            f'{o.format_name}, {resolution}, CRF {o.crf}, {o.preset}, {o.audio_bitrate_kbps}k')
        item = self.table.item(row, 4)
        item.setText(job.state.value)
        item.setToolTip(job.error)
        if job.target:
            self.table.item(row, 0).setToolTip(f'{job.source}\n-> {job.target}')
        job.row_widgets['bar'].setValue(job.progress)

    def _start_next(self):
        if self.process is not None:
            return
        job = next((j for j in self.jobs if j.state == JobState.QUEUED), None)
        if job is None:
            return
        self.current_job = job
        job.target = unique_target_path(job.source, FORMATS[job.options.format_name][0])
        job.state = JobState.RUNNING
        self._stdout_buffer = ''
        self._stderr_tail = ''
        self._update_row(job)

        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_error)
        self.process.start('ffmpeg', build_ffmpeg_args(job, probe_video_height(job.source)))

    def _on_stdout(self):
        job = self.current_job
        if job is None or self.process is None:
            return
        self._stdout_buffer += bytes(self.process.readAllStandardOutput().data()).decode(errors='replace')
        *lines, self._stdout_buffer = self._stdout_buffer.split('\n')
        for line in lines:
            key, _, value = line.strip().partition('=')
            if key == 'out_time_us' and job.duration and value.lstrip('-').isdigit():
                job.progress = max(0, min(99, int(int(value) / 1_000_000 / job.duration * 100)))
                job.row_widgets['bar'].setValue(job.progress)
            elif key == 'progress' and value == 'end' and job.duration is None:
                job.progress = 99

    def _on_stderr(self):
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardError().data()).decode(errors='replace')
        self._stderr_tail = (self._stderr_tail + text)[-2000:]

    def _on_error(self, error: QProcess.ProcessError):
        if error == QProcess.ProcessError.FailedToStart and self.current_job is not None:
            self._stderr_tail = 'Unable to start ffmpeg. Make sure it is installed and available on PATH.'
            self._finish_current(JobState.FAILED)

    def _on_finished(self, exit_code: int, _status):
        job = self.current_job
        if job is None:
            return
        if job.state == JobState.CANCELLED:
            self._finish_current(JobState.CANCELLED)
        elif exit_code == 0:
            self._finish_current(JobState.DONE)
        else:
            self._finish_current(JobState.FAILED)

    def _finish_current(self, state: JobState):
        job = self.current_job
        process = self.process
        self.current_job = None
        self.process = None
        if process is not None:
            process.blockSignals(True)
            process.deleteLater()
        if job is None:
            return
        job.state = state
        if state == JobState.DONE:
            job.progress = 100
            try:
                job.compressed_size = os.path.getsize(job.target)
            except OSError:
                job.compressed_size = None
        elif state in (JobState.FAILED, JobState.CANCELLED):
            job.error = self._stderr_tail.strip()
            if os.path.exists(job.target):
                try:
                    os.remove(job.target)
                except OSError:
                    pass
        self._update_row(job)
        if state == JobState.DONE:
            self.file_compressed.emit(job.target)
        self._start_next()

    def _cancel_selected(self):
        rows = {i.row() for i in self.table.selectionModel().selectedRows()}
        for row in rows:
            job = self.jobs[row]
            if job.state in (JobState.PENDING, JobState.QUEUED):
                job.state = JobState.CANCELLED
                self._update_row(job)
                self._refresh_controls()
            elif job.state == JobState.RUNNING and self.process is not None:
                self._cancel_current()

    def _cancel_current(self):
        if self.current_job is None or self.process is None:
            return
        self.current_job.state = JobState.CANCELLED
        self._refresh_controls()
        self.process.kill()

    def _clear_finished(self):
        for row in reversed(range(len(self.jobs))):
            if self.jobs[row].state in (JobState.DONE, JobState.FAILED, JobState.CANCELLED):
                self.table.removeRow(row)
                del self.jobs[row]

    def closeEvent(self, event):
        # Keep the queue running in the background.
        event.ignore()
        self.hide()
