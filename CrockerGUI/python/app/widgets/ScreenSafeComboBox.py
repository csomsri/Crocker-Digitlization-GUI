"""Dropdowns that do not create native popup windows in screen-filling mode."""

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtWidgets import QApplication, QComboBox, QListView, QWidget
from python.app.theme import load_dropdown_stylesheet, load_dropdown_control_stylesheet


class ScreenSafeComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._inline_menu = None
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(load_dropdown_control_stylesheet())

    def _style_menu(self, menu):
        menu.setFont(self.font())
        menu.setStyleSheet(load_dropdown_stylesheet())
        menu.setMouseTracking(True)
        menu.setCursor(Qt.PointingHandCursor)

    def showPopup(self):
        host = self.window()
        if not (host.isFullScreen() or host.windowFlags() & Qt.FramelessWindowHint):
            self._style_menu(self.view())
            return super().showPopup()
        if self._inline_menu is not None or not self.count():
            return
        # A child widget stays in the owner's native window and cannot trigger
        # a fullscreen activation change or be stacked behind its owner.
        menu = QListView(host)
        self._inline_menu = menu
        menu.setObjectName("screenSafeComboMenu")
        self._style_menu(menu)
        menu.setModel(self.model())
        menu.setRootIndex(self.rootModelIndex())
        menu.setModelColumn(self.modelColumn())
        menu.setEditTriggers(QListView.NoEditTriggers)
        menu.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        menu.setCurrentIndex(self.model().index(self.currentIndex(), self.modelColumn(), self.rootModelIndex()))
        menu.clicked.connect(self._choose)
        origin = self.mapTo(host, QPoint(0, 0))
        below = host.height() - origin.y() - self.height()
        above = origin.y()
        desired = max(30, menu.sizeHintForRow(0)) * min(self.count(), self.maxVisibleItems()) + 12
        height = min(desired, max(below, above))
        width = min(host.width(), max(self.width(), menu.sizeHintForColumn(self.modelColumn()) + 32))
        y = origin.y() + self.height() if below >= min(desired, above) else origin.y() - height
        menu.setGeometry(max(0, min(origin.x(), host.width() - width)), max(0, y), width, height)
        QApplication.instance().installEventFilter(self)
        menu.show()
        menu.raise_()
        menu.scrollTo(menu.currentIndex())
        menu.setFocus(Qt.PopupFocusReason)

    def _choose(self, index):
        if not index.isValid() or not index.flags() & Qt.ItemIsEnabled or not index.flags() & Qt.ItemIsSelectable:
            return
        self.setCurrentIndex(index.row())
        self.hidePopup()
        self.activated.emit(index.row())
        self.textActivated.emit(self.currentText())

    def hidePopup(self):
        menu = self._inline_menu
        if menu is not None:
            self._inline_menu = None
            QApplication.instance().removeEventFilter(self)
            menu.hide()
            menu.deleteLater()
            self.setFocus(Qt.PopupFocusReason)
        super().hidePopup()

    def eventFilter(self, watched, event):
        menu = self._inline_menu
        if menu is not None:
            if event.type() == QEvent.KeyPress and isinstance(watched, QWidget) and (watched is menu or menu.isAncestorOf(watched)):
                if event.key() == Qt.Key_Escape:
                    self.hidePopup()
                    return True
                if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                    self._choose(menu.currentIndex())
                    return True
            if event.type() == QEvent.MouseButtonPress:
                if not menu.rect().contains(menu.mapFromGlobal(event.globalPosition().toPoint())):
                    on_combo = self.rect().contains(self.mapFromGlobal(event.globalPosition().toPoint()))
                    self.hidePopup()
                    return on_combo
            if watched is self.window() and event.type() in (QEvent.Resize, QEvent.Hide, QEvent.WindowDeactivate):
                self.hidePopup()
        return super().eventFilter(watched, event)
