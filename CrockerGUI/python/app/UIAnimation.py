from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QPushButton,
    QStackedWidget,
    QWidget,
)


class UIAnimationController(QObject):
    """Small, centralized motion polish for the Qt UI."""

    def __init__(self, stack: QStackedWidget, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.stack = stack
        self._fade_animation: QPropertyAnimation | None = None
        self.stack.currentChanged.connect(self._fade_current_page)

    def attach_to(self, root: QWidget) -> None:
        root.installEventFilter(self)
        self._attach_subtree(root)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API name
        event_type = event.type()
        if event_type == QEvent.ChildAdded and isinstance(watched, QWidget):
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
        for button in root.findChildren(QPushButton):
            self._prepare_button(button)

    def _prepare_button(self, button: QPushButton) -> None:
        if button.property("motionPolish"):
            return
        button.setProperty("motionPolish", True)
        button.installEventFilter(self)
        self._set_button_state(button, hover=False, pressed=False)

    def _set_button_state(self, button: QPushButton, *, hover: bool, pressed: bool) -> None:
        button.setProperty("motionHover", hover)
        button.setProperty("motionPressed", pressed)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _fade_current_page(self) -> None:
        page = self.stack.currentWidget()
        if page is None:
            return

        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.0)
        page.setGraphicsEffect(effect)

        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(220)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.finished.connect(lambda page=page: page.setGraphicsEffect(None))
        self._fade_animation = animation
        animation.start()
