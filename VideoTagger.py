#!/usr/bon/env python

from PySide6.QtCore import Qt, QMargins, QTimer, QSize, QRect, QProcess, Signal, QObject
from PySide6.QtWidgets import (QApplication, QFrame, QLabel, QPushButton,
                               QMainWindow, QSizePolicy, QVBoxLayout, QHBoxLayout, QWidget, QSlider)

from __feature__ import snake_case, true_property

test_file = '../../Downloads/VID_20211022_164107296~3.mp4'

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.set_window_title("Video Tagger")
        self.geometry = QRect(100, 100, 800, 600)

        self.layout = QVBoxLayout()

        self.play_button = QPushButton("Test")
        self.layout.add_widget(self.play_button)

        self.central_widget = QWidget()
        self.central_widget.set_layout(self.layout)
        self.set_central_widget(self.central_widget)

        self.vlc = VlcPlayer()

        self.play_button.clicked.connect(lambda: self.vlc.play_video(test_file))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_vlc_status)
        self.timer.start(1000)

    def update_vlc_status(self):
        self.vlc.update_status()

    def close_event(self, event):
        self.vlc.close()
        event.accept()


class VlcPlayer(QObject):
    def __init__(self):
        super().__init__()
        self.create_vlc_instance()

    def create_vlc_instance(self):
        self.vlc_process = QProcess()
        self.vlc_process.set_program("vlc")
        self.vlc_process.set_arguments(["--extraintf", "rc"])
        self.vlc_process.start()
        self.vlc_process.wait_for_started()
        self._read_stdout()

    def _read_stdout(self):
        data = b''
        while True:
            self.vlc_process.wait_for_ready_read()
            data += self.vlc_process.read_all_standard_output().data()
            if data.endswith(b'> ') or self.vlc_process.state() == QProcess.ProcessState.NotRunning:
                return data[:-2].strip()

    def send(self, command):
        self.vlc_process.write(f'{command}\n'.encode())
        self.vlc_process.wait_for_bytes_written()
        #return self._read_stdout()

    def play_video(self, video_path):
        self.send(f'add {video_path}')
        self.send(f'play')

    def pause_video(self):
        self.send('pause')
    
    def stop_video(self):
        self.send('stop')

    def update_status(self):
        self.send('status')
        self.send('get_time')

    def seek_video(self, time):
        self.send(f'seek {time}')
    
    def get_video_time(self):
        self.send('get_time')
        return self.vlc_process.stdout.read()
    
    def close(self):
        self.send('quit')
        self.vlc_process.wait_for_finished()

def main():
    app = QApplication([])
    main_window = MainWindow()
    main_window.show()
    QApplication.exec()

if __name__ == '__main__':
    main()
