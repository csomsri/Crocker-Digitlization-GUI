"""Layouts that adapt to their available logical (DPI independent) width."""

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QBoxLayout


class ResponsiveRow(QBoxLayout):
    """Keep a row horizontal when it fits; stack its items otherwise.

    The minimum width describes the stacked arrangement so a parent layout
    can actually shrink far enough to trigger reflow. Item minimum sizes keep
    controls readable; page scrolling handles heights below that readable size.
    """

    def __init__(self, parent=None):
        super().__init__(QBoxLayout.LeftToRight, parent)

    def _items(self):
        return [self.itemAt(i) for i in range(self.count())
                if not self.itemAt(i).isEmpty()]

    def minimumSize(self):
        items = self._items()
        margins = self.contentsMargins()
        return QSize(
            max((item.minimumSize().width() for item in items), default=0)
            + margins.left() + margins.right(),
            super().minimumSize().height(),
        )

    def setGeometry(self, rect):
        items = self._items()
        margins = self.contentsMargins()
        required = sum(item.minimumSize().width() for item in items)
        required += max(0, len(items) - 1) * max(0, self.spacing())
        required += margins.left() + margins.right()
        direction = (QBoxLayout.TopToBottom if rect.width() < required
                     else QBoxLayout.LeftToRight)
        if self.direction() != direction:
            self.setDirection(direction)
        super().setGeometry(rect)
