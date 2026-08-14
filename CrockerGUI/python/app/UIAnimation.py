from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QListView,
    QPushButton,
    QStackedWidget,
    QWidget,
)


class UIAnimationController(QObject):
    """Small, centralized motion polish for the Qt UI."""

    def __init__(self, stack: QStackedWidget, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.stack = stack

    def attach_to(self, root: QWidget) -> None:
        root.installEventFilter(self)
        self._attach_subtree(root)
        self._attach_subtree(self.stack)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API name
        event_type = event.type()
        if event_type == QEvent.ChildAdded and isinstance(watched, QWidget):
            if self._is_app_widget(watched):
                self._attach_subtree(watched)
        if isinstance(watched, QPushButton):
            if event_type == QEvent.Enter:
                self._set_button_state(watched, hover=True, pressed=False)
            elif event_type == QEvent.Leave:
                self._set_button_state(watched, hover=False, pressed=False)
            elif event_type == QEvent.MouseButtonPress:
                self._set_button_state(watched, hover=True, pressed=True)
            elif event_type == QEvent.MouseButtonRelease:
                self._set_button_state(watched, hover=watched.underMouse(), pressed=False)
        return super().eventFilter(watched, event)

    def _attach_subtree(self, root: QWidget) -> None:
        if not self._is_app_widget(root):
            return
        if root.windowFlags() & Qt.WindowType.Popup:
            return
        for combo in root.findChildren(QComboBox):
            self._prepare_combo(combo)
        for button in root.findChildren(QPushButton):
            self._prepare_button(button)

    def _prepare_combo(self, combo: QComboBox) -> None:
        if not self._is_app_widget(combo):
            return
        if combo.property("stablePopup"):
            return
        combo.setProperty("stablePopup", True)
        combo.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        combo.setMaxVisibleItems(10)
        view = QListView(combo)
        view.setObjectName("comboPopupView")
        view.setUniformItemSizes(True)
        view.setMouseTracking(False)
        combo.setView(view)

    def _prepare_button(self, button: QPushButton) -> None:
        if not self._is_app_widget(button):
            return
        if button.property("motionPolish"):
            return
        button.setProperty("motionPolish", True)
        button.installEventFilter(self)
        self._set_button_state(button, hover=False, pressed=False)

    def _set_button_state(self, button: QPushButton, *, hover: bool, pressed: bool) -> None:
        if (
            button.property("motionHover") == hover
            and button.property("motionPressed") == pressed
        ):
            return
        button.setProperty("motionHover", hover)
        button.setProperty("motionPressed", pressed)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _is_app_widget(self, widget: QWidget) -> bool:
        app_window = self.stack.window()
        return (
            widget is app_window
            or widget is self.stack
            or self.stack.isAncestorOf(widget)
            or app_window.isAncestorOf(widget)
        )
