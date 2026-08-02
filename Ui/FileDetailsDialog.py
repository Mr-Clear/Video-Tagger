import os
import json
from fractions import Fraction

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import QDialog, QFormLayout, QLabel, QPlainTextEdit, QVBoxLayout


class FileDetailsDialog(QDialog):
    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)

        self.file_path = file_path
        self.setWindowTitle(f'File details - {file_path}')
        self.resize(900, 700)

        self.details = {}
        details_layout = QFormLayout()
        for label, value in (
            ('File path', file_path),
            ('File size', self._format_size(os.path.getsize(file_path))),
            ('Container', 'Reading...'),
            ('Duration', 'Reading...'),
            ('Resolution', 'Reading...'),
            ('Frame rate', 'Reading...'),
            ('Bitrate', 'Reading...'),
            ('Video', 'Reading...'),
            ('Audio', 'Reading...'),
            ('Start time', 'Reading...'),
        ):
            value_label = QLabel(value)
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            details_layout.addRow(f'{label}:', value_label)
            self.details[label] = value_label

        self.status_label = QLabel('Reading media metadata...')
        self.status_label.setWordWrap(True)

        self.output_text = QPlainTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output_text.setPlaceholderText('ffprobe output will appear here.')

        layout = QVBoxLayout(self)
        layout.addLayout(details_layout)
        layout.addWidget(self.status_label)
        layout.addWidget(QLabel('FFmpeg metadata output (ffprobe):'))
        layout.addWidget(self.output_text)

        self.output = bytearray()
        self.error_output = bytearray()

        self.process = QProcess(self)
        self.process.setProgram('ffprobe')
        self.process.setArguments([
            '-v', 'error',
            '-of', 'json',
            '-show_format',
            '-show_streams',
            self.file_path,
        ])
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.readyReadStandardError.connect(self._read_error)
        self.process.errorOccurred.connect(self._process_error)
        self.process.finished.connect(self._process_finished)
        self.process.start()

    def _read_output(self):
        self.output.extend(bytes(self.process.readAllStandardOutput()))

    def _read_error(self):
        self.error_output.extend(bytes(self.process.readAllStandardError()))

    def _process_error(self, _error):
        if self.process.error() == QProcess.ProcessError.FailedToStart:
            self.status_label.setText(
                'Unable to read media metadata. Make sure ffprobe is installed and available on PATH.'
            )

    def _process_finished(self, _exit_code, _exit_status):
        self._read_output()
        self._read_error()
        output = bytes(self.output).decode(errors='replace')
        error_output = bytes(self.error_output).decode(errors='replace')
        displayed_output = output
        if error_output:
            displayed_output = f'{output}\n\n{error_output}'.strip()
        self.output_text.setPlainText(displayed_output)
        try:
            metadata = json.loads(output)
        except json.JSONDecodeError:
            self.status_label.setText('ffprobe returned invalid metadata for this file.')
            return

        format_data = metadata.get('format', {})
        format_name = format_data.get('format_name')
        format_long_name = format_data.get('format_long_name')
        if format_name:
            container = format_name
            if format_long_name:
                container = f'{format_name} ({format_long_name})'
            self.details['Container'].setText(container)
        if format_data.get('duration') is not None:
            self.details['Duration'].setText(self._format_duration(format_data['duration']))
        if format_data.get('start_time') is not None:
            self.details['Start time'].setText(format_data['start_time'])
        if format_data.get('bit_rate') is not None:
            self.details['Bitrate'].setText(self._format_bitrate(format_data['bit_rate']))

        streams = metadata.get('streams', [])
        video_stream = next((stream for stream in streams if stream.get('codec_type') == 'video'), None)
        audio_stream = next((stream for stream in streams if stream.get('codec_type') == 'audio'), None)
        if video_stream:
            self.details['Video'].setText(video_stream.get('codec_long_name', video_stream.get('codec_name', 'Unknown')))
            width = video_stream.get('width')
            height = video_stream.get('height')
            if width and height:
                self.details['Resolution'].setText(f'{width} x {height}')
            frame_rate = self._format_frame_rate(video_stream.get('avg_frame_rate'))
            if frame_rate:
                self.details['Frame rate'].setText(frame_rate)
        if audio_stream:
            audio_details = [audio_stream.get('codec_long_name', audio_stream.get('codec_name', 'Unknown'))]
            sample_rate = audio_stream.get('sample_rate')
            if sample_rate:
                audio_details.append(f'{sample_rate} Hz')
            channel_layout = audio_stream.get('channel_layout')
            if channel_layout:
                audio_details.append(channel_layout)
            self.details['Audio'].setText(', '.join(audio_details))

        self.status_label.setText('Metadata loaded.')

    @staticmethod
    def _format_size(size: int) -> str:
        units = ('B', 'KiB', 'MiB', 'GiB', 'TiB')
        size_value = float(size)
        for unit in units:
            if size_value < 1024 or unit == units[-1]:
                return f'{size_value:.1f} {unit}' if unit != 'B' else f'{size} B'
            size_value /= 1024
        return f'{size} B'

    @staticmethod
    def _format_duration(duration: str) -> str:
        try:
            seconds = float(duration)
        except (TypeError, ValueError):
            return str(duration)
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f'{int(hours):02}:{int(minutes):02}:{seconds:06.3f}'

    @staticmethod
    def _format_bitrate(bitrate: str) -> str:
        try:
            bitrate_value = float(bitrate)
        except (TypeError, ValueError):
            return str(bitrate)
        if bitrate_value >= 1_000_000:
            return f'{bitrate_value / 1_000_000:.2f} Mb/s'
        return f'{bitrate_value / 1_000:.0f} kb/s'

    @staticmethod
    def _format_frame_rate(frame_rate: str | None) -> str | None:
        if not frame_rate or frame_rate in ('0/0', 'N/A'):
            return None
        try:
            value = float(Fraction(frame_rate))
        except (ValueError, ZeroDivisionError):
            return frame_rate
        return f'{value:.3f} fps'

    def closeEvent(self, event):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)
        super().closeEvent(event)
