"""Readable decimal formatting for operator-facing values."""
import math
from decimal import Decimal
from PySide6.QtWidgets import QDoubleSpinBox


class CompactDoubleSpinBox(QDoubleSpinBox):
    """Trim visual zero padding while retaining the editor's configured precision."""
    def textFromValue(self, value):
        text = super().textFromValue(value)
        decimal = self.locale().decimalPoint()
        return text.rstrip('0').rstrip(decimal) if decimal in text else text


def display_number(value, *, significant=6, grouping=True, max_decimals=6):
    if not math.isfinite(value):
        return 'Unavailable'
    if value == 0:
        return '0'
    if abs(value) < 10 ** -max_decimals:
        return '≈ 0'
    # Bound decimal expansion: simulated decay can produce tiny nonzero tails.
    number = Decimal(format(value, f'.{significant}g'))
    text = format(number, f',.{max_decimals}f' if grouping else f'.{max_decimals}f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text
