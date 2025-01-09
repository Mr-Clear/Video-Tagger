#!/usr/bin/env python

from PySide6.QtWidgets import QApplication
from Ui.MainWindow import MainWindow


def main():
    app = QApplication([])
    main_window = MainWindow()
    main_window.showMaximized()
    app.exec()


if __name__ == '__main__':
    main()
