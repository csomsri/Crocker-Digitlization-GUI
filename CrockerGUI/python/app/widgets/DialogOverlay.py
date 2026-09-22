"""Modal editor hosted inside the main window, without a native popup."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout, QWidget
from shiboken6 import isValid


class DialogOverlay(QFrame):
    def __init__(self, dialog, owner, *, size=None, retain=False):
        host = owner.window()
        super().__init__(host)
        self.dialog = dialog
        dialog._dialog_overlay = self
        self._retain = retain
        self._original_parent = dialog.parentWidget()
        self._original_minimum = dialog.minimumSize()
        self._original_maximum = dialog.maximumSize()
        self._preferred_size = size or (740, 700)
        self._finished = False
        self._previous_focus = QApplication.focusWidget()
        self._disabled = [w for w in host.findChildren(QWidget, options=Qt.FindDirectChildrenOnly)
                          if w is not self and w is not dialog and w.isVisible() and w.isEnabled()]
        self.setObjectName('dialogOverlay')
        self.setStyleSheet('QFrame#dialogOverlay { background: rgba(3, 9, 18, 170); }')
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setGeometry(host.rect())
        dialog.setParent(self, Qt.Widget)
        dialog.setAttribute(Qt.WA_TranslucentBackground, False)
        dialog.setWindowModality(Qt.NonModal)
        title_bar = dialog.findChild(QFrame, 'dialogTitleBar')
        if title_bar is not None:
            title_bar.setToolTip('')
            from PySide6.QtWidgets import QPushButton
            for button in title_bar.findChildren(QPushButton):
                if button.accessibleName() in ('Minimize', 'Maximize / restore'):
                    button.hide()
        self._fit()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(dialog, 1, Qt.AlignCenter)
        for widget in self._disabled:
            widget.setEnabled(False)
        host.installEventFilter(self)
        QApplication.instance().installEventFilter(self)
        dialog.finished.connect(self._finish)
        self.show()
        QWidget.show(dialog)
        self.raise_()
        dialog.setFocus(Qt.OtherFocusReason)
        self._advance_focus(True)

    def _fit(self):
        width, height = self._preferred_size
        self.dialog.setFixedSize(min(width, max(1, self.width() - 48)),
                                 min(height, max(1, self.height() - 48)))

    def _advance_focus(self, forward):
        start = QApplication.focusWidget() or self.dialog
        candidate = start
        while True:
            candidate = candidate.nextInFocusChain() if forward else candidate.previousInFocusChain()
            if (self.dialog.isAncestorOf(candidate) and candidate.isVisible()
                    and candidate.isEnabled() and candidate.focusPolicy() & Qt.TabFocus):
                candidate.setFocus(Qt.TabFocusReason if forward else Qt.BacktabFocusReason)
                return
            if candidate is start:
                return

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.KeyPress and isinstance(watched, QWidget)
                and (watched is self.dialog or self.dialog.isAncestorOf(watched))
                and event.key() in (Qt.Key_Tab, Qt.Key_Backtab)):
            self._advance_focus(event.key() == Qt.Key_Tab and not event.modifiers() & Qt.ShiftModifier)
            return True
        if watched is self.parent() and event.type() == QEvent.Hide:
            self.dialog.reject()
        if watched is self.parent() and event.type() == QEvent.Resize:
            self.setGeometry(watched.rect())
            self._fit()
        return super().eventFilter(watched, event)

    def _finish(self, result=0):
        if self._finished:
            return
        self._finished = True
        self.dialog.finished.disconnect(self._finish)
        self.dialog._dialog_overlay = None
        if self._retain:
            QWidget.hide(self.dialog)
            self.dialog.setParent(self._original_parent, Qt.Dialog | Qt.FramelessWindowHint)
            self.dialog.setMinimumSize(self._original_minimum)
            self.dialog.setMaximumSize(self._original_maximum)
            self.dialog.resize(*self._preferred_size)
        QApplication.instance().removeEventFilter(self)
        self.parent().removeEventFilter(self)
        self.hide()
        for widget in self._disabled:
            if isValid(widget):
                widget.setEnabled(True)
        if self._previous_focus is not None and isValid(self._previous_focus):
            self._previous_focus.setFocus(Qt.OtherFocusReason)
        self.deleteLater()
