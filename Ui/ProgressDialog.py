import os

from PySide6.QtGui import QFont, QFontMetrics, Qt, Qt
from PySide6.QtWidgets import (QApplication, QDialog, QLabel, QProgressBar,
                               QPushButton, QVBoxLayout)


class ProgressDialog(QDialog):
    def __init__(self, title: str, max: int, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(400)

        self.cancelled = False

        self.setWindowTitle(title)
        self.setModal(True)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, max)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.message_label = QLabel("Starting...")
        layout.addWidget(self.message_label)

        self.button = QPushButton("Cancel", self)
        self.button.clicked.connect(self.cancel)

        layout.addWidget(self.button)

    def cancel(self):
        self.cancelled = True

    def set_progress(self, value: int, file_path: str = "") -> bool:
        self.progress_bar.setValue(value)
        self.message_label.setText(fit_path(file_path, self.width() - 20, self.message_label.font()))
        QApplication.processEvents()  # Ensure the UI updates immediately
        return self.cancelled

    def set_end(self, cancelled: bool):
        if cancelled:
            self.progress_bar.setEnabled(False)
            self.message_label.setText("Cancelled.")
        else:
            self.progress_bar.setValue(self.progress_bar.maximum())
            self.message_label.setText("Completed.")
        self.button.setText("Close")
        self.button.clicked.disconnect()
        self.button.clicked.connect(self.accept)
        QApplication.processEvents()  # Ensure the UI updates immediately

def fit_path(path: str, max_width: int, font: QFont) -> str:
    metrics = QFontMetrics(font)
    path_elements = path.split(os.sep)
    if metrics.horizontalAdvance(path) <= max_width:
        return path
    dots = False
    while len(path_elements) > 1:
        p = os.sep.join(path_elements)
        if metrics.horizontalAdvance(p) <= max_width:
            return p
        if not dots:
            path_elements[-2] = "…"
            dots = True
        else:
            path_elements.pop(-2)

    dots = False
    p = os.sep.join(path_elements)
    while metrics.horizontalAdvance(p) > max_width and len(path_elements[0]) > 3:
        if not dots:
            path_elements[0] = "…" + path_elements[0][1:]
            dots = True
        else:
            path_elements[0] = path_elements[0][:-1]
        p = os.sep.join(path_elements)
    return p
