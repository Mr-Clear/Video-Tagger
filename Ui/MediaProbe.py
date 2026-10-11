import json
import subprocess
from fractions import Fraction

from PySide6.QtCore import QObject, QProcess, Signal


def probe_video_height(file_path: str) -> int | None:
    """Synchronously reads the height of the first video stream."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=height',
             '-of', 'csv=p=0', file_path],
            capture_output=True, text=True, timeout=30)
        return int(result.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class MediaProbe(QObject):
    """Runs ffprobe asynchronously on a file."""

    # Text for display (stdout plus stderr) and parsed metadata (None if invalid).
    finished = Signal(str, object)
    failed = Signal(str)

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self._output = bytearray()
        self._error_output = bytearray()

        self._process = QProcess(self)
        self._process.setProgram('ffprobe')
        self._process.setArguments(['-v', 'error', '-of', 'json', '-show_format', '-show_streams', file_path])
        self._process.readyReadStandardOutput.connect(self._read_output)
        self._process.readyReadStandardError.connect(self._read_error)
        self._process.errorOccurred.connect(self._on_error)
        self._process.finished.connect(self._on_finished)

    def start(self):
        self._process.start()

    def cancel(self):
        self.blockSignals(True)
        self._process.blockSignals(True)
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._process.waitForFinished(1000)

    def _read_output(self):
        self._output.extend(bytes(self._process.readAllStandardOutput()))

    def _read_error(self):
        self._error_output.extend(bytes(self._process.readAllStandardError()))

    def _on_error(self, _error):
        if self._process.error() == QProcess.ProcessError.FailedToStart:
            self.failed.emit('Unable to read media metadata. Make sure ffprobe is installed and available on PATH.')

    def _on_finished(self, _exit_code, _exit_status):
        self._read_output()
        self._read_error()
        output = bytes(self._output).decode(errors='replace')
        error_output = bytes(self._error_output).decode(errors='replace')
        displayed = f'{output}\n\n{error_output}'.strip() if error_output else output
        try:
            metadata = json.loads(output)
        except json.JSONDecodeError:
            metadata = None
        self.finished.emit(displayed, metadata)


def summarize_metadata(metadata: dict) -> dict[str, str]:
    """Maps ffprobe JSON to display values keyed by label; unavailable values are omitted."""
    result: dict[str, str] = {}
    format_data = metadata.get('format', {})
    format_name = format_data.get('format_name')
    if format_name:
        long_name = format_data.get('format_long_name')
        result['Container'] = f'{format_name} ({long_name})' if long_name else format_name
    if format_data.get('duration') is not None:
        result['Duration'] = format_duration(format_data['duration'])
    if format_data.get('start_time') is not None:
        result['Start time'] = format_data['start_time']
    if format_data.get('bit_rate') is not None:
        result['Bitrate'] = format_bitrate(format_data['bit_rate'])

    streams = metadata.get('streams', [])
    video = next((s for s in streams if s.get('codec_type') == 'video'), None)
    audio = next((s for s in streams if s.get('codec_type') == 'audio'), None)
    if video:
        result['Video'] = video.get('codec_long_name', video.get('codec_name', 'Unknown'))
        if video.get('width') and video.get('height'):
            result['Resolution'] = f"{video['width']} x {video['height']}"
        frame_rate = format_frame_rate(video.get('avg_frame_rate'))
        if frame_rate:
            result['Frame rate'] = frame_rate
    if audio:
        details = [audio.get('codec_long_name', audio.get('codec_name', 'Unknown'))]
        if audio.get('sample_rate'):
            details.append(f"{audio['sample_rate']} Hz")
        if audio.get('channel_layout'):
            details.append(audio['channel_layout'])
        result['Audio'] = ', '.join(details)
    return result


def format_size(size: int) -> str:
    units = ('B', 'KiB', 'MiB', 'GiB', 'TiB')
    size_value = float(size)
    for unit in units:
        if size_value < 1024 or unit == units[-1]:
            return f'{size_value:.1f} {unit}' if unit != 'B' else f'{size} B'
        size_value /= 1024
    return f'{size} B'


def format_duration(duration: str) -> str:
    try:
        seconds = float(duration)
    except (TypeError, ValueError):
        return str(duration)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{int(hours):02}:{int(minutes):02}:{seconds:06.3f}'


def format_bitrate(bitrate: str) -> str:
    try:
        bitrate_value = float(bitrate)
    except (TypeError, ValueError):
        return str(bitrate)
    if bitrate_value >= 1_000_000:
        return f'{bitrate_value / 1_000_000:.2f} Mb/s'
    return f'{bitrate_value / 1_000:.0f} kb/s'


def format_frame_rate(frame_rate: str | None) -> str | None:
    if not frame_rate or frame_rate in ('0/0', 'N/A'):
        return None
    try:
        value = float(Fraction(frame_rate))
    except (ValueError, ZeroDivisionError):
        return frame_rate
    return f'{value:.3f} fps'
