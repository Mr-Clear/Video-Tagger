from typing import List, Set, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette, QPainter, QMouseEvent
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QStyleOption, QStyle, QSpacerItem, QSizePolicy, QMenu


class TagWidget(QWidget):
    _remove_clicked = Signal(str)

    def __init__(self, tag_name: str):
        super().__init__()
        self.tag_name = tag_name
        self.layout = QHBoxLayout()
        self.layout.setContentsMargins(8, 4, 8, 4)
        self.setLayout(self.layout)

        self.label = QLabel(tag_name)
        self.layout.addWidget(self.label)

        self.button = QLabel('❌')
        self.button.setObjectName('button')
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.mousePressEvent = lambda _: self._remove_clicked.emit(tag_name)
        self.layout.addWidget(self.button)

    def paintEvent(self, _):
        opt = QStyleOption()
        opt.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, painter, self)

    def __repr__(self):
        return self.tag_name


class TagListWidget(QWidget):
    list_changed = Signal(set)

    def __init__(self, get_tags_fn: Callable[[], set[str]]):
        super().__init__()
        self.tags: Set[str] = set()
        self.widgets: List[TagWidget] = []
        self.get_tags_fn = get_tags_fn
        self.setObjectName('container')
        background_color = self.palette().color(QPalette.ColorRole.Base)
        label_color = self.palette().color(QPalette.ColorRole.Window)
        hover_color = self.palette().color(QPalette.ColorRole.Highlight)
        self.setStyleSheet(f'''
            TagListWidget {{
                background-color: {background_color.name()};
            }}
            TagWidget, QLabel[is_add_button="1"] {{
                background-color: {label_color.name()};
                border-radius: 8px;
                margin: 2px;
            }}
            QLabel {{
                background-color: {label_color.name()};
            }}
            QLabel:hover#button {{
                color: {hover_color.name()};
            }}
            ''')

        self.layout = QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.setLayout(self.layout)

        self.layout.addSpacerItem(QSpacerItem(8, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))

        add_button = QLabel('➕')
        add_button.setProperty('is_add_button', '1')
        add_button.setObjectName('button')
        add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        add_button.mousePressEvent = self.on_add_tag
        self.layout.addWidget(add_button)

        self.layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

    def on_add_tag(self, event: QMouseEvent):
        tags = sorted(self.get_tags_fn())
        menu = QMenu()
        if not tags:
            menu.addAction('No tags available').setEnabled(False)
        for tag in tags:
            if tag not in self.tags:
                action = menu.addAction(tag)
                action.triggered.connect(lambda _, t=tag: self.add_tag(t))
        menu.exec(event.globalPosition().toPoint())

    def _add_tag_widget(self, tag: str, index: int):
        widget = TagWidget(tag)
        widget._remove_clicked.connect(self.remove_tag)
        self.widgets.insert(index, widget)
        self.layout.insertWidget(index, widget)

    def _remove_tag_widget(self, tag: str):
        for widget in self.widgets:
            if widget.tag_name == tag:
                self.layout.removeWidget(widget)
                self.widgets.remove(widget)
                widget.deleteLater()
                self.list_changed.emit(self.tags)
                return

    def add_tag(self, tag: str):
        if tag in self.tags:
            return
        self.tags.add(tag)
        found = False
        index = 0
        for index, widget in enumerate(self.widgets):
            if widget.tag_name > tag:
                found = True
                break
        if not found:
            index = len(self.widgets)
        self._add_tag_widget(tag, index)
        self.list_changed.emit(self.tags)

    def remove_tag(self, tag: str):
        if tag not in self.tags:
            return
        self.tags.remove(tag)
        self._remove_tag_widget(tag)
        self.list_changed.emit(self.tags)

    def set_tags(self, tags: Set[str]):
        if tags == self.tags:
            return
        for tag in self.tags - tags:
            self.remove_tag(tag)
        for tag in tags - self.tags:
            self.add_tag(tag)
        self.list_changed.emit(self.tags)

    def paintEvent(self, _):
        opt = QStyleOption()
        opt.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, painter, self)
