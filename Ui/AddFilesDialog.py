import os

from PySide6.QtCore import QDir, QObject, Signal, QThread, QItemSelectionModel, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QTreeView, QFileSystemModel, QHBoxLayout, QPushButton, \
    QLabel

from Database import Database
from Tools import resolve_symlink


class AddFilesDialog(QDialog):
    default_filter = QDir.Filter.Dirs | QDir.Filter.NoDotAndDotDot

    class ScanWorker(QObject):
        file_found = Signal(str)
        finished = Signal()

        def __init__(self, directory, file_filter):
            super().__init__()
            self.directory = directory
            self.file_filter = file_filter
            self.abort_scan = False

        def scan(self):
            for root, _, files in os.walk(self.directory):
                for file in files:
                    if self.abort_scan:
                        return
                    if file.endswith(tuple(self.file_filter.split(';'))):
                        try:
                            file_path = resolve_symlink(os.path.join(root, file))
                            self.file_found.emit(file_path)
                        except Exception as e:
                            print(e)

        def run(self):
            self.scan()
            self.finished.emit()

    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        self.found_files = set()

        self.setWindowTitle("Add Files")
        self.setGeometry(100, 100, 800, 600)

        self.init_ui()

        self.scan_worker: AddFilesDialog.ScanWorker | None = None
        self.scan_worker_thread: QThread | None = None

    # noinspection PyAttributeOutsideInit
    def init_ui(self):
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        filters = '.mp4;.avi;.mkv;.mov;.wmv;.flv;.webm;.mpeg;.mpg;.m4v;.3gp;.vob;.ogv;.ogg;.mxf;.rm;.divx;.xvid'
        self.file_filter = QLineEdit(self.database.get_setting('scan_file_filter', filters))
        self.file_filter.textChanged.connect(lambda text: self.database.set_setting('scan_file_filter', text))
        self.layout.addWidget(self.file_filter)

        self.file_system_view = QTreeView()
        self.file_system_view_model = QFileSystemModel()
        self.file_system_view.setModel(self.file_system_view_model)
        self.file_system_view_model.setRootPath(QDir.rootPath())
        self.file_system_view_model.setFilter(QDir.Filter.Dirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden)
        for i in range(1, 4):
            self.file_system_view.hideColumn(i)
        last_used_folder = self.database.get_setting('last_scanned_folder', QDir.homePath())
        last_used_index = self.file_system_view_model.index(last_used_folder)
        self.file_system_view.scrollTo(last_used_index)
        self.file_system_view.selectionModel().setCurrentIndex(last_used_index,
                                                               QItemSelectionModel.SelectionFlag.Select)
        self.file_system_view.setExpanded(last_used_index, True)
        self.file_system_view.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        toggle_hidden_action = QAction("Toggle Hidden Files", self)
        toggle_hidden_action.setShortcut("Ctrl+H")
        toggle_hidden_action.triggered.connect(self.toggle_hidden_files)
        self.addAction(toggle_hidden_action)
        self.show_hidden_files(self.database.get_setting('show_hidden_files', str(False)) == 'True')
        self.layout.addWidget(self.file_system_view)

        self.bottom_layout = QHBoxLayout()
        self.layout.addLayout(self.bottom_layout)

        self.scan_directory_button = QPushButton("Scan Directory")
        self.scan_directory_button.clicked.connect(self.scan_directory)
        self.bottom_layout.addWidget(self.scan_directory_button)

        self.abort_scan_button = QPushButton("Abort Scan")
        self.abort_scan_button.setEnabled(False)
        self.abort_scan_button.clicked.connect(self.abort_scan)
        self.bottom_layout.addWidget(self.abort_scan_button)

        self.status_label = QLabel()
        self.bottom_layout.addWidget(self.status_label)

        self.accept_button = QPushButton("Accept")
        self.accept_button.clicked.connect(self.accept)
        self.bottom_layout.addWidget(self.accept_button)

    def toggle_hidden_files(self):
        show = not self.file_system_view_model.filter() & QDir.Filter.Hidden
        self.show_hidden_files(show)
        self.database.set_setting('show_hidden_files', str(show))

    def show_hidden_files(self, show: bool):
        if show:
            self.file_system_view_model.setFilter(AddFilesDialog.default_filter | QDir.Filter.Hidden)
        else:
            self.file_system_view_model.setFilter(AddFilesDialog.default_filter)

    def scan_directory(self):
        scan_root = self.file_system_view_model.filePath(self.file_system_view.currentIndex())
        self.database.set_setting('last_scanned_folder', scan_root)
        self.scan_directory_button.setEnabled(False)
        self.abort_scan_button.setEnabled(True)
        self.accept_button.setEnabled(False)
        self.status_label.setText("Scanning directory...")
        self.scan_worker = AddFilesDialog.ScanWorker(scan_root, self.file_filter.text())
        self.scan_worker.file_found.connect(self.on_file_found)
        self.scan_worker.finished.connect(self.on_finished)
        self.scan_worker_thread = QThread()
        self.scan_worker.moveToThread(self.scan_worker_thread)
        self.scan_worker_thread.started.connect(self.scan_worker.run)
        self.scan_worker_thread.start()

    def on_file_found(self, file_path):
        self.found_files.add(file_path)
        self.status_label.setText(f"Found {len(self.found_files)} files")

    def on_finished(self):
        self.status_label.setText(f"{len(self.found_files)} files found")
        self.scan_directory_button.setEnabled(True)
        self.abort_scan_button.setEnabled(False)
        self.accept_button.setEnabled(True)

    def abort_scan(self):
        if self.scan_worker:
            self.scan_worker.abort_scan = True
            self.scan_worker_thread.quit()
            self.scan_worker_thread.wait()
        self.status_label.setText("Scan aborted")
