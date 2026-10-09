"""Screen-filling desktop windows that retain normal Qt popup activation."""

import ctypes
import sys

from PySide6.QtCore import QEvent, QObject, Qt, QMargins, QRect
from PySide6.QtGui import QGuiApplication


class _CompositedScreenWindow(QObject):
    """Keep Windows from treating a monitor-sized GL surface as exclusive."""

    def __init__(self, window):
        super().__init__(window)
        from ctypes import wintypes

        self.enabled = True
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        # GWL_STYLE is a 32-bit LONG even when HWND is pointer-sized.
        self._get_style = self._user32.GetWindowLongW
        self._get_style.argtypes = (wintypes.HWND, ctypes.c_int)
        self._get_style.restype = wintypes.LONG
        self._set_style = self._user32.SetWindowLongW
        self._set_style.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.LONG)
        self._set_style.restype = wintypes.LONG
        window.installEventFilter(self)

    def apply(self):
        window = self.parent()
        hwnd = window.internalWinId()
        if not self.enabled or not hwnd or not window.windowFlags() & Qt.FramelessWindowHint:
            return
        # Qt's documented workaround also covers QOpenGLWidget-backed windows:
        # https://doc.qt.io/qt-6/windows-issues.html#fullscreen-opengl-based-windows
        # A native border keeps DWM compositing popups/tooltips over the GL owner.
        # Merely avoiding showFullScreen() is insufficient for a monitor-sized
        # frameless window. Do not hide, reactivate, or resize it when popups open.
        style = self._get_style(hwnd, -16)  # GWL_STYLE
        if not style & 0x00800000:  # WS_BORDER
            ctypes.set_last_error(0)
            if not self._set_style(hwnd, -16, style | 0x00800000):
                error = ctypes.get_last_error()
                if error:
                    raise ctypes.WinError(error)

    def eventFilter(self, watched, event):
        # Adding the first GL chart can recreate the native window. Qt can also
        # reset its native style during a display-mode transition.
        if event.type() in (QEvent.WinIdChange, QEvent.Show, QEvent.WindowStateChange):
            self.apply()
        return super().eventFilter(watched, event)


def set_screen_filling(window, screen) -> None:
    guard = getattr(window, "_composited_screen_window", None)
    if sys.platform == "win32" and QGuiApplication.platformName() == "windows":
        if guard is None:
            guard = _CompositedScreenWindow(window)
            window._composited_screen_window = guard
        guard.enabled = True
    # Qt's native fullscreen state can lose activation when a transient popup
    # opens on Windows. Use a normal frameless window covering the monitor.
    flags = window.windowFlags() | Qt.WindowType.FramelessWindowHint
    if window.windowFlags() != flags:
        window.setWindowFlags(flags)
    window.setWindowState(Qt.WindowState.WindowNoState)
    if screen is not None:
        window.setGeometry(screen.geometry())
    window.show()
    if guard is not None:
        guard.apply()


def fit_decorated_window(window, screen, requested_size=None) -> None:
    """Fit the complete native frame using logical, DPI-independent coordinates."""
    if screen is None:
        return
    available = screen.availableGeometry()
    handle = window.windowHandle()
    margins = handle.frameMargins() if handle is not None else QMargins()
    # During a frameless transition Qt can still report the old zero margins.
    # Reserve room before showing the decorated HWND so Windows never receives
    # a monitor-sized client rectangle plus a title bar and resize borders.
    left, top, right, bottom = (max(16, margins.left()), max(48, margins.top()),
                               max(16, margins.right()), max(16, margins.bottom()))
    width, height = requested_size or (window.width(), window.height())
    width = min(width, max(1, available.width() - left - right))
    height = min(height, max(1, available.height() - top - bottom))
    x = available.x() + left + (available.width() - left - right - width) // 2
    y = available.y() + top + (available.height() - top - bottom - height) // 2
    window.setGeometry(QRect(x, y, width, height))


def set_decorated(window) -> None:
    guard = getattr(window, "_composited_screen_window", None)
    if guard is not None:
        guard.enabled = False
    flags = window.windowFlags() & ~Qt.WindowType.FramelessWindowHint
    if window.windowFlags() != flags:
        fit_decorated_window(window, window.screen() or QGuiApplication.primaryScreen())
        window.setWindowFlags(flags)
    window.setWindowState(Qt.WindowState.WindowNoState)
    fit_decorated_window(window, window.screen() or QGuiApplication.primaryScreen())
    window.showNormal()
