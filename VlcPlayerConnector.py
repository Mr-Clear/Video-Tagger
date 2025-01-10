from PySide6.QtCore import QObject, QProcess


class VlcPlayerConnector(QObject):
    def __init__(self):
        super().__init__()
        self.create_vlc_instance()

    # noinspection PyAttributeOutsideInit
    def create_vlc_instance(self):
        self.vlc_process = QProcess()
        self.vlc_process.setProgram("vlc")
        self.vlc_process.setArguments(["--extraintf", "rc"])
        self.vlc_process.start()
        self.vlc_process.waitForStarted()
        self._read_stdout()

    def _read_stdout(self):
        data = b''
        while True:
            self.vlc_process.waitForReadyRead()
            data += self.vlc_process.readAllStandardOutput().data()
            if data.endswith(b'> ') or self.vlc_process.state() == QProcess.ProcessState.NotRunning:
                return data[:-2].strip()

    def send(self, command):
        self.vlc_process.write(f'{command}\n'.encode())
        self.vlc_process.waitForBytesWritten()
        return self._read_stdout()

    def play_video(self, video_path):
        self.send('clear')
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

    def close(self):
        self.send('quit')
        self.vlc_process.waitForFinished()
