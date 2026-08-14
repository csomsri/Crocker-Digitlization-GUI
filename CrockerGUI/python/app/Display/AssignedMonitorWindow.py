from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QMargins, QRect, Qt
from PySide6.QtWidgets import QApplication, QFrame, QMainWindow, QScrollArea, QSizePolicy

if TYPE_CHECKING:
    from python.app.MainWindow import MainWindow


def screen_key(screen) -> str:
    geometry = screen.geometry()
    return (
        f"{screen.name()}|"
        f"{geometry.x()},{geometry.y()},"
        f"{geometry.width()}x{geometry.height()}"
    )


class AssignedMonitorWindow(QMainWindow):
    """Hosts one assigned application page on an auxiliary monitor."""

    def __init__(self, owner: MainWindow, screen_id: str, screen_name: str) -> None:
        super().__init__()
        self.owner = owner
        self.screen_id = screen_id
        self.screen_name = screen_name
        self.page_name = ""
        self.setWindowTitle(f"Crocker Display - {screen_name}")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def apply_display_mode(
        self,
        mode: str,
        window_resolution: tuple[int, int] | None = None,
    ) -> None:
        flags = self.windowFlags()
        desired_flags = flags
        desired_flags &= ~Qt.WindowType.FramelessWindowHint
        if desired_flags != flags:
            self.setWindowFlags(desired_flags)

        screen = self._assigned_screen()
        if screen is not None:
            handle = self.windowHandle()
            if handle is not None:
                handle.setScreen(screen)
        if mode == "Windowed":
            if screen is not None:
                self._place_windowed(screen, window_resolution)
            if self.isFullScreen() or self.isMaximized() or not self.isVisible():
                self.setWindowState(Qt.WindowState.WindowNoState)
                self.showNormal()
        else:
            if screen is not None:
                self._place_fullscreen(screen)
            elif not self.isFullScreen():
                self.showFullScreen()

    def _place_windowed(self, screen, window_resolution: tuple[int, int] | None) -> None:
        geometry = self._safe_screen_rect(screen, available=True)
        margins = self._frame_margins()
        requested_width, requested_height = window_resolution or (1280, 820)
        width = min(requested_width, max(1, geometry.width() - margins.left() - margins.right()))
        height = min(requested_height, max(1, geometry.height() - margins.top() - margins.bottom()))
        self.resize(width, height)
        self.move(
            geometry.x() + int((geometry.width() - width) / 2),
            geometry.y() + int((geometry.height() - height) / 2),
        )

    def _place_fullscreen(self, screen) -> None:
        was_visible = self.isVisible()
        if was_visible and (self.isFullScreen() or self.isMaximized()):
            self.setWindowState(Qt.WindowState.WindowNoState)
            self.showNormal()
        geometry = self._safe_screen_rect(screen, available=False)
        self.setGeometry(geometry)
        self.move(geometry.topLeft())
        self.showFullScreen()

    def _frame_margins(self) -> QMargins:
        handle = self.windowHandle()
        if handle is None:
            return QMargins()
        return handle.frameMargins()

    def _safe_screen_rect(self, screen, available: bool) -> QRect:
        base = screen.availableGeometry() if available else screen.geometry()
        physical = screen.geometry()
        width = min(base.width(), physical.width())
        height = min(base.height(), physical.height())
        if width > 1 and width % 2:
            width -= 1
        if height > 1 and height % 2:
            height -= 1
        return QRect(base.x(), base.y(), max(1, width), max(1, height))

    def _assigned_screen(self):
        for screen in QApplication.screens():
            if screen_key(screen) == self.screen_id:
                return screen
        return self.screen()

    def set_page(self, page_name: str) -> None:
        if page_name == self.page_name and self.centralWidget() is not None:
            return
        self.setStyleSheet(self.owner.styleSheet())
        old_page = self.takeCentralWidget()
        if old_page is not None:
            old_page.deleteLater()
        page = self.owner.create_assigned_page(page_name, self)
        page.setStyleSheet(self.owner.styleSheet())
        scroll_area = QScrollArea()
        scroll_area.setObjectName("assignedPageScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll_area.setStyleSheet(self.owner.styleSheet())
        scroll_area.setWidget(page)
        self.setCentralWidget(scroll_area)
        self.page_name = page_name
        self.owner._refresh_settings_monitors()
        self.updateGeometry()
        self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
