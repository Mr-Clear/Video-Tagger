from datetime import datetime

from PySide6.QtCore import QDateTime


def to_QDateTime(dt: datetime):
    if 1970 < dt.year < 2038:
        return QDateTime.fromMSecsSinceEpoch(int(dt.timestamp() * 1000))
    return QDateTime()


def to_datetime(dt: QDateTime):
    return datetime.fromtimestamp(dt.toMSecsSinceEpoch() / 1000.0)
