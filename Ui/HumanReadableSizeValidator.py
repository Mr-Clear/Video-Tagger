import humanfriendly
from PySide6.QtGui import QValidator


class HumanReadableSizeValidator(QValidator):
    def __init__(self, parent=None):
        super().__init__(parent)

    def validate(self, input_str, pos):
        try:
            humanfriendly.parse_size(input_str)
            return QValidator.State.Acceptable, input_str, pos
        except humanfriendly.InvalidSize:
            return QValidator.State.Invalid, input_str, pos

    def fixup(self, input_str):
        try:
            return humanfriendly.parse_size(input_str)
        except humanfriendly.InvalidSize:
            return ''
