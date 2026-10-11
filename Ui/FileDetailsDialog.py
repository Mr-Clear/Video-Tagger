import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFormLayout, QLabel, QPlainTextEdit, QVBoxLayout

from Ui.MediaProbe import MediaProbe, format_size, summarize_metadata


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
            ('File size', format_size(os.path.getsize(file_path))),
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

        self.probe = MediaProbe(file_path, self)
        self.probe.failed.connect(self.status_label.setText)
        self.probe.finished.connect(self._probe_finished)
        self.probe.start()

    def _probe_finished(self, displayed_output: str, metadata):
        self.output_text.setPlainText(displayed_output)
        if metadata is None:
            self.status_label.setText('ffprobe returned invalid metadata for this file.')
            return
        for label, value in summarize_metadata(metadata).items():
            self.details[label].setText(value)
        self.status_label.setText('Metadata loaded.')

    def closeEvent(self, event):
        self.probe.cancel()
        super().closeEvent(event)
