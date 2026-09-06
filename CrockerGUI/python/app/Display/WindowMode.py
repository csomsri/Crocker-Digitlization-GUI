"""Screen-filling desktop windows that retain normal Qt popup activation."""

from PySide6.QtCore import Qt


def set_screen_filling(window, screen) -> None:
    # Qt's native fullscreen state can lose activation when a transient popup
    # opens on Windows. Use a normal frameless window covering the monitor.
    flags = window.windowFlags() | Qt.WindowType.FramelessWindowHint
    if window.windowFlags() != flags:
        window.setWindowFlags(flags)
    window.setWindowState(Qt.WindowState.WindowNoState)
    if screen is not None:
        window.setGeometry(screen.geometry())
    window.show()


def set_decorated(window) -> None:
    flags = window.windowFlags() & ~Qt.WindowType.FramelessWindowHint
    if window.windowFlags() != flags:
        window.setWindowFlags(flags)
    window.setWindowState(Qt.WindowState.WindowNoState)
    window.showNormal()
