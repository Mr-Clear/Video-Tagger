from typing import List

from PySide6.QtCore import Signal, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QSizePolicy


class StarRatingWidget(QWidget):
    rating_changed = Signal(int)

    def __init__(self, font_size, parent=None):
        super().__init__(parent)
        self._rating: int | None = None
        self.hovered_star: int | None = None
        self.stars: List[QLabel] = []
        self.font_size: int = font_size
        self.init_ui()

    def star_mouse_event(self, i: int):
        def event(event: QMouseEvent):
            if event.type() == QEvent.Type.Enter:
                self.hovered_star = i
                self._update()
            elif event.type() == QEvent.Type.Leave:
                self.hovered_star = None
                self._update()
            elif event.type() == QEvent.Type.MouseButtonPress:
                self._set_rating(i + 1)
        return event

    def init_ui(self):
        layout = QHBoxLayout()
        for i in range(5):
            star = QLabel()
            star.mousePressEvent = self.star_mouse_event(i)
            star.enterEvent = self.star_mouse_event(i)
            star.leaveEvent = self.star_mouse_event(i)
            star.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed))
            layout.addWidget(star)
            self.stars.append(star)
        self.setLayout(layout)
        self._update()

    def _set_rating(self, rating: int | None):
        if rating != self._rating:
            self._rating = rating
            self._update()
            self.rating_changed.emit(rating)

    def _update(self):
        for i, star in enumerate(self.stars):
            rating = self._rating if self._rating is not None else 0
            if i < rating:
                star.setText('★')
            else:
                star.setText('☆')

            if self._rating is None:
                color = 'gray'
                weight = 'normal'
            elif i == self.hovered_star:
                color = 'blue'
                weight = 'bold'
            else:
                color = 'yellow'
                weight = 'normal'

            star.setStyleSheet(f'font-size: {self.font_size}px; color: {color}; font-weight: {weight}')

    @property
    def rating(self):
        return self._rating

    @rating.setter
    def rating(self, rating):
        self._rating = rating
        self._update()
