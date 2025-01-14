from datetime import datetime
from typing import Tuple, Dict, Callable

import humanfriendly
from PySide6.QtCore import Signal, QTemporaryFile, QPropertyAnimation, QAbstractAnimation, QEasingCurve
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QHBoxLayout, QLineEdit, QToolButton, QSpinBox, QLabel, \
    QSizePolicy, QDateTimeEdit

from Ui.FileSortFilterProxyModel import FileFilter
from Ui.HumanReadableSizeValidator import HumanReadableSizeValidator
from Ui.TagListWidget import TagListWidget
from Ui.Tools import to_QDateTime, to_datetime


class FilterWidget(QGroupBox):
    filter_changed = Signal(FileFilter)

    def __init__(self, expanded: bool, title: str, get_tags_fn: Callable[[], set[str]], parent=None):
        super().__init__(parent)
        self.get_tags_fn = get_tags_fn
        self._filter = FileFilter()
        self.icon_keep_alive: Dict[QIcon.ThemeIcon, QTemporaryFile | None] = {}
        self.collapse_animation: QPropertyAnimation | None = None
        self.init_ui(expanded, title)

    # noinspection PyAttributeOutsideInit
    def init_ui(self, expanded: bool, title: str):
        self.setTitle(title)
        self.setCheckable(True)

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.name_regex_layout = QHBoxLayout()
        self.layout.addLayout(self.name_regex_layout)

        self.name_regex_edit = QLineEdit()
        self.name_regex_edit.setText(self._filter.name_regex)
        self.name_regex_edit.setPlaceholderText('Name Regex')
        self.name_regex_edit.returnPressed.connect(lambda: self.set_name_regex(self.name_regex_edit.text()))
        self.name_regex_layout.addWidget(self.name_regex_edit)

        self.name_regex_case_sensitive_button = QToolButton()
        self.name_regex_case_sensitive_button.setCheckable(True)
        self.name_regex_case_sensitive_button.setChecked(self._filter.name_regex_case_sensitive)
        self.name_regex_case_sensitive_button.setText('Aa')
        self.name_regex_case_sensitive_button.toggled.connect(self.set_name_regex_case_sensitive)
        self.name_regex_case_sensitive_button.setToolTip('Case Sensitive')
        self.name_regex_layout.addWidget(self.name_regex_case_sensitive_button)

        self.path_edit = QLineEdit()
        self.path_edit.setText(self._filter.path)
        self.path_edit.setPlaceholderText('Path')
        self.path_edit.returnPressed.connect(lambda: self.set_path(self.path_edit.text()))
        self.layout.addWidget(self.path_edit)

        self.rating_layout = QHBoxLayout()
        self.layout.addLayout(self.rating_layout)
        self.rating_min_edit = QSpinBox()
        self.rating_min_edit.setRange(0, 5)
        self.rating_min_edit.setValue(self._filter.rating[0])
        self.rating_min_edit.valueChanged.connect(lambda: self.set_min_rating(self.rating_min_edit.value()))
        self.rating_layout.addWidget(self.rating_min_edit)

        self.rating_max_edit = QSpinBox()
        self.rating_max_edit.setRange(0, 5)
        self.rating_max_edit.setValue(self._filter.rating[1])
        self.rating_max_edit.valueChanged.connect(lambda: self.set_max_rating(self.rating_max_edit.value()))
        self.rating_layout.addWidget(self.rating_max_edit)

        self.tags_whitelist_widget = TagListWidget(self.get_tags_fn)
        self.tags_whitelist_widget.set_tags(self._filter.tags_whitelist)
        self.tags_whitelist_widget.setToolTip('Tags Whitelist')
        self.tags_whitelist_widget.list_changed.connect(self.set_tags_whitelist)
        self.layout.addWidget(self.tags_whitelist_widget)

        self.tags_blacklist_widget = TagListWidget(self.get_tags_fn)
        self.tags_blacklist_widget.set_tags(self._filter.tags_whitelist)
        self.tags_blacklist_widget.setToolTip('Tags Blacklist')
        self.tags_blacklist_widget.list_changed.connect(self.set_tags_blacklist)
        self.layout.addWidget(self.tags_blacklist_widget)

        self.size_layout = QHBoxLayout()
        self.layout.addLayout(self.size_layout)

        self.size_label = QLabel('Size from')
        self.size_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed))
        self.size_layout.addWidget(self.size_label)

        self.size_min_edit = QLineEdit()
        self.size_min_edit.setText(humanfriendly.format_size(self._filter.size[0]))
        self.size_min_edit.setPlaceholderText('Min size')
        self.size_min_edit.setValidator(HumanReadableSizeValidator())
        self.size_min_edit.returnPressed.connect(
            lambda: self.set_min_size(humanfriendly.parse_size(self.size_min_edit.text())))
        self.size_layout.addWidget(self.size_min_edit)

        self.size_to_label = QLabel('to')
        self.size_to_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed))
        self.size_layout.addWidget(self.size_to_label)

        self.size_max_edit = QLineEdit()
        self.size_max_edit.setText(humanfriendly.format_size(self._filter.size[1]))
        self.size_max_edit.setPlaceholderText('Max size')
        self.size_max_edit.setValidator(HumanReadableSizeValidator())
        self.size_max_edit.returnPressed.connect(
            lambda: self.set_max_size(humanfriendly.parse_size(self.size_max_edit.text())))
        self.size_layout.addWidget(self.size_max_edit)

        self.date_layout = QHBoxLayout()
        self.layout.addLayout(self.date_layout)

        self.date_label = QLabel('Date from')
        self.date_layout.addWidget(self.date_label)
        self.date_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed))

        self.date_min_edit = QDateTimeEdit()
        self.date_min_edit.setDateTime(to_QDateTime(self._filter.date[0]))
        self.date_min_edit.setDisplayFormat('yyyy-MM-dd HH:mm:ss')
        self.date_min_edit.setCalendarPopup(True)
        self.date_min_edit.dateTimeChanged.connect(
            lambda: self.set_min_date(to_datetime(self.date_min_edit.dateTime())))
        self.date_layout.addWidget(self.date_min_edit)

        self.date_to_label = QLabel('to')
        self.date_layout.addWidget(self.date_to_label)
        self.date_to_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed))

        self.date_max_edit = QDateTimeEdit()
        self.date_max_edit.setDateTime(to_QDateTime(self._filter.date[1]))
        self.date_max_edit.setDisplayFormat('yyyy-MM-dd HH:mm:ss')
        self.date_max_edit.setCalendarPopup(True)
        self.date_max_edit.dateTimeChanged.connect(self.set_max_date)
        self.date_layout.addWidget(self.date_max_edit)

        self.setChecked(expanded)
        self.on_toggle(expanded)
        self.toggled.connect(self.on_toggle)

        self.setStyleSheet(f'''
            QGroupBox {{
                border: 1px solid gray;
                border-radius: 3px;
                margin-top: 0.5em;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding-left: 4px;
                padding-right: 8px;
                left: 2px;
            }}
            QGroupBox:flat {{
                border: none;
            }}
            QGroupBox::indicator::unchecked {{
                image: url({self.get_icon(QIcon.ThemeIcon.GoNext)});
            }}
            QGroupBox::indicator::checked {{
                image: url({self.get_icon(QIcon.ThemeIcon.GoDown)});
            }}
        ''')

    def get_icon(self, icon: QIcon.ThemeIcon) -> str:
        temp_file: QTemporaryFile | None = None
        if icon in self.icon_keep_alive:
            temp_file = self.icon_keep_alive[icon]
        else:
            q_icon = QIcon.fromTheme(icon)
            if not q_icon.isNull():
                temp_file = QTemporaryFile()
                if not temp_file.open():
                    temp_file = None
                else:
                    q_icon.pixmap(32).save(temp_file.fileName(), 'PNG')
            self.icon_keep_alive[icon] = temp_file
        return temp_file.fileName()

    def on_toggle(self, checked: bool):
        self.collapse_animation = QPropertyAnimation(self, b'maximumHeight')
        self.collapse_animation.setDuration(200)
        self.collapse_animation.setStartValue(20 if checked else self.sizeHint().height())
        self.collapse_animation.setEndValue(self.sizeHint().height() if checked else 20)
        self.collapse_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.collapse_animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self.collapse_animation.finished.connect(lambda: self.setFlat(not checked))

    @property
    def filter(self) -> FileFilter:
        return self._filter

    @filter.setter
    def filter(self, f: FileFilter):
        self.name_regex = f.name_regex
        self.path = f.path
        self.max_rating = f.rating[0]
        self.min_rating = f.rating[1]
        self.tags_whitelist = f.tags_whitelist
        self.tags_blacklist = f.tags_blacklist
        self.min_size = f.size[0]
        self.max_size = f.size[1]
        self.min_date = f.date[0]
        self.max_date = f.date[1]

    @property
    def name_regex(self) -> str:
        return self._filter.name_regex

    @name_regex.setter
    def name_regex(self, name_regex: str):
        if name_regex != self._filter.name_regex:
            self._filter.name_regex = name_regex
            self.name_regex_edit.setText(name_regex)
            self.filter_changed.emit(self._filter)

    def set_name_regex(self, name_regex: str):
        self.name_regex = name_regex

    @property
    def name_regex_case_sensitive(self) -> bool:
        return self._filter.name_regex_case_sensitive

    @name_regex_case_sensitive.setter
    def name_regex_case_sensitive(self, name_regex_case_sensitive: bool):
        if name_regex_case_sensitive != self._filter.name_regex_case_sensitive:
            self._filter.name_regex_case_sensitive = name_regex_case_sensitive
            self.name_regex_case_sensitive_button.setChecked(self._filter.name_regex_case_sensitive)
            self.filter_changed.emit(self._filter)

    def set_name_regex_case_sensitive(self, name_regex_case_sensitive: bool):
        self.name_regex_case_sensitive = name_regex_case_sensitive

    @property
    def path(self) -> str:
        return self._filter.path

    @path.setter
    def path(self, path: str):
        if path != self._filter.path:
            self._filter.path = path
            self.path_edit.setText(path)
            self.filter_changed.emit(self._filter)

    def set_path(self, path: str):
        self.path = path

    @property
    def rating(self) -> Tuple[int, int]:
        return self._filter.rating

    @rating.setter
    def rating(self, rating: Tuple[int, int]):
        self.min_rating = rating[0]
        self.max_rating = rating[1]

    def set_rating(self, rating: Tuple[int, int]):
        self.rating = rating

    @property
    def min_rating(self) -> int:
        return self._filter.rating[0]

    @min_rating.setter
    def min_rating(self, min_rating: int):
        if min_rating != self._filter.rating[0]:
            self._filter.rating = (min_rating, self._filter.rating[1])
            self.rating_min_edit.setValue(min_rating)
            self.filter_changed.emit(self._filter)

    def set_min_rating(self, min_rating: int):
        self.min_rating = min_rating

    @property
    def max_rating(self) -> int:
        return self._filter.rating[1]

    @max_rating.setter
    def max_rating(self, max_rating: int):
        if max_rating != self._filter.rating[1]:
            self._filter.rating = (self._filter.rating[0], max_rating)
            self.rating_max_edit.setValue(max_rating)
            self.filter_changed.emit(self._filter)

    def set_max_rating(self, max_rating: int):
        self.max_rating = max_rating

    @property
    def tags_whitelist(self) -> set[str]:
        return self._filter.tags_whitelist

    @tags_whitelist.setter
    def tags_whitelist(self, tags_whitelist: set[str]):
        if self._filter.tags_whitelist != tags_whitelist:
            self._filter.tags_whitelist = set(tags_whitelist)
            self.tags_whitelist_widget.set_tags(tags_whitelist)
            self.filter_changed.emit(self._filter)

    def set_tags_whitelist(self, tags_whitelist: set[str]):
        self.tags_whitelist = tags_whitelist

    def tag_in_whitelist(self, tag: str) -> bool:
        return tag in self.tags_whitelist

    def set_tag_in_whitelist(self, tag: str, in_whitelist: bool):
        if in_whitelist != self.tag_in_whitelist(tag):
            if in_whitelist:
                self.tags_whitelist = self.tags_whitelist | {tag}
                self.set_tag_in_blacklist(tag, False)
            else:
                self.tags_whitelist = self.tags_whitelist - {tag}

    @property
    def tags_blacklist(self) -> set[str]:
        return self._filter.tags_blacklist

    @tags_blacklist.setter
    def tags_blacklist(self, tags_blacklist: set[str]):
        if self._filter.tags_blacklist != tags_blacklist:
            self._filter.tags_blacklist = set(tags_blacklist)
            self.tags_blacklist_widget.set_tags(tags_blacklist)
            self.filter_changed.emit(self._filter)

    def set_tags_blacklist(self, tags_blacklist: set[str]):
        self.tags_blacklist = tags_blacklist

    def tag_in_blacklist(self, tag: str) -> bool:
        return tag in self.tags_blacklist

    def set_tag_in_blacklist(self, tag: str, in_blacklist: bool):
        if in_blacklist != self.tag_in_blacklist(tag):
            if in_blacklist:
                self.tags_blacklist = self.tags_blacklist | {tag}
                self.set_tag_in_whitelist(tag, False)
            else:
                self.tags_blacklist = self.tags_blacklist - {tag}

    @property
    def size(self) -> Tuple[int, int]:
        return self._filter.size

    @size.setter
    def size(self, size: Tuple[int, int]):
        self.min_size = size[0]
        self.max_size = size[1]

    def set_size(self, size: Tuple[int, int]):
        self.size = size

    @property
    def min_size(self):
        return self._filter.size[0]

    @min_size.setter
    def min_size(self, min_size: int):
        if min_size != self._filter.size[0]:
            self._filter.size = (min_size, self._filter.size[1])
            self.size_min_edit.setText(humanfriendly.format_size(min_size))
            self.filter_changed.emit(self._filter)

    def set_min_size(self, min_size: int):
        self.min_size = min_size

    @property
    def max_size(self) -> int:
        return self._filter.size[1]

    @max_size.setter
    def max_size(self, max_size: int):
        if max_size != self._filter.size[1]:
            self._filter.size = (self._filter.size[0], max_size)
            self.size_max_edit.setText(humanfriendly.format_size(max_size))
            self.filter_changed.emit(self._filter)

    def set_max_size(self, max_size: int):
        self.max_size = max_size

    @property
    def date(self) -> Tuple[datetime, datetime]:
        return self._filter.date

    @date.setter
    def date(self, date: Tuple[datetime, datetime]):
        self.min_date = date[0]
        self.max_date = date[1]

    def set_date(self, date: Tuple[datetime, datetime]):
        self.date = date

    @property
    def min_date(self) -> datetime:
        return self._filter.date[0]

    @min_date.setter
    def min_date(self, min_date: datetime):
        if min_date != self._filter.date[0]:
            self._filter.date = (min_date, self._filter.date[1])
            self.date_min_edit.setDateTime(to_QDateTime(min_date))
            self.filter_changed.emit(self._filter)

    def set_min_date(self, min_date: datetime):
        self.min_date = min_date

    @property
    def max_date(self) -> datetime:
        return self._filter.date[1]

    @max_date.setter
    def max_date(self, max_date: datetime):
        if max_date != self._filter.date[1]:
            self._filter.date = (self._filter.date[0], max_date)
            self.date_max_edit.setDateTime(to_QDateTime(max_date))
            self.filter_changed.emit(self._filter)

    def set_max_date(self, max_date: datetime):
        self.max_date = max_date
