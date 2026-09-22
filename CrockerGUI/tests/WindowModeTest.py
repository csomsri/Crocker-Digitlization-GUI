"""Exercise popup mouse selection and screen-filling/windowed transitions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QMessageBox, QToolTip, QWidget, QVBoxLayout
from python.app.Display.WindowMode import set_decorated, set_screen_filling
from python.app.widgets.ScreenSafeComboBox import ScreenSafeComboBox


app = QApplication.instance() or QApplication([])
app.setStyle("Fusion")
native_windows = sys.platform == "win32" and app.platformName() == "windows"
if native_windows:
    import ctypes
    from ctypes import wintypes

    get_style = ctypes.windll.user32.GetWindowLongW
    get_style.argtypes = (wintypes.HWND, ctypes.c_int)
    get_style.restype = wintypes.LONG


class WindowEvents(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.disruptions = []
        parent.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Hide, QEvent.WindowStateChange):
            self.disruptions.append(event.type())
        return False


window = QMainWindow()
events = WindowEvents(window)
combo = ScreenSafeComboBox()
combo.addItems(["Simulation / dry run", "Approved hardware profile"])
page = QWidget()
layout = QVBoxLayout(page)
layout.addWidget(combo)
layout.addStretch()
window.setCentralWidget(page)
try:
    for _ in range(3):
        set_screen_filling(window, app.primaryScreen())
        window.raise_()
        window.activateWindow()
        QTest.qWait(200)
        if native_windows:
            assert get_style(int(window.winId()), -16) & 0x00800000, "Missing DWM border"
            if _ == 0:
                # Real charts use QOpenGLWidget; adding one after show can
                # recreate the HWND and must preserve the compositing fix.
                chart = QOpenGLWidget(page)
                chart.setMinimumSize(160, 100)
                layout.addWidget(chart)
                refresh = QTimer(chart)
                refresh.timeout.connect(chart.update)
                refresh.start(16)
                QTest.qWait(200)
                assert chart.isValid(), "Native OpenGL context unavailable"
                assert get_style(int(window.winId()), -16) & 0x00800000
        assert window.geometry() == app.primaryScreen().geometry()
        assert not window.isFullScreen() and not window.isMinimized()
        events.disruptions.clear()
        geometry = window.geometry()
        hwnd = window.winId()
        for row in (1, 0):
            QTest.mouseClick(combo, Qt.LeftButton)
            QTest.qWait(300)
            view = combo._inline_menu
            assert view is not None and not view.isWindow()
            assert view.isVisible()
            point = view.visualRect(combo.model().index(row, 0)).center()
            QTest.mouseMove(view.viewport(), point)
            QTest.qWait(150)
            QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=point, delay=100)
            QTest.qWait(100)
            assert combo.currentIndex() == row
            assert combo._inline_menu is None
            assert window.isVisible() and not window.isMinimized()
        # Exercise native transient windows too, not just the inline dropdown.
        QToolTip.showText(combo.mapToGlobal(QPoint(5, 5)), "Live chart tooltip", combo)
        QTest.qWait(150)
        assert QToolTip.isVisible()
        if native_windows:
            assert window.isActiveWindow(), "Tooltip stole activation"
        QToolTip.hideText()
        menu = QMenu(window)
        action = menu.addAction("Popup action")
        triggered = []
        action.triggered.connect(lambda: triggered.append(True))
        menu.popup(combo.mapToGlobal(QPoint(0, combo.height())))
        QTest.qWait(100)
        QTest.mouseClick(menu, Qt.LeftButton, pos=menu.actionGeometry(action).center())
        assert triggered == [True]
        dialog = QMessageBox(QMessageBox.Information, "Popup test", "Chart stays visible", QMessageBox.Ok, window)
        dialog.open()
        QTest.qWait(100)
        assert dialog.isVisible() and window.isVisible()
        QTest.mouseClick(dialog.button(QMessageBox.Ok), Qt.LeftButton)
        QTest.qWait(100)
        assert not dialog.isVisible()
        assert window.geometry() == geometry and window.winId() == hwnd
        assert not events.disruptions, events.disruptions
        if native_windows:
            assert get_style(int(window.winId()), -16) & 0x00800000
        menu.deleteLater()
        dialog.deleteLater()
        set_decorated(window)
        QTest.qWait(200)
        assert not (window.windowFlags() & Qt.FramelessWindowHint)
        combo.showPopup()
        QTest.qWait(100)
        assert combo._inline_menu is not None and combo._inline_menu.isVisible()
        assert not combo._inline_menu.isWindow()
        combo.hidePopup()
    print("Screen-filling dropdowns, tooltips, menus, dialogs, and windowed transitions passed")
finally:
    window.close()
