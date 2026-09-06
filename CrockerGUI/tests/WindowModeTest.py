"""Exercise popup mouse selection and screen-filling/windowed transitions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QMainWindow, QWidget, QVBoxLayout
from python.app.Display.WindowMode import set_decorated, set_screen_filling
from python.app.widgets.ScreenSafeComboBox import ScreenSafeComboBox


app = QApplication.instance() or QApplication([])
app.setStyle("Fusion")
window = QMainWindow()
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
        assert window.geometry() == app.primaryScreen().geometry()
        assert not window.isFullScreen() and not window.isMinimized()
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
        set_decorated(window)
        QTest.qWait(200)
        assert not (window.windowFlags() & Qt.FramelessWindowHint)
        combo.showPopup()
        QTest.qWait(100)
        assert combo._inline_menu is None and combo.view().isVisible()
        combo.hidePopup()
    print("Screen-filling popup selection and windowed transitions passed")
finally:
    window.close()
