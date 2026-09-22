"""Exercise settings clicks and F11 without starting hardware or recording."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import zmq  # Preload before PySide's import hook.
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow
from python.app.MainWindow import MainWindow
from python.app.Configuration.SettingsPage import SettingsPage


class DisplayHarness(MainWindow):
    def __init__(self, settings_path):
        QMainWindow.__init__(self)
        self._settings = QSettings(settings_path, QSettings.IniFormat)
        self._display_mode = "Windowed"
        self._window_resolution = "1280 x 820"
        self._windowed_geometry = None
        self._display_transition = 0
        self._monitor_windows = {}
        self.pages = {}
        page = SettingsPage(lambda: None, self.set_display_mode, self.set_window_resolution)
        self.pages["Settings"] = page
        self.setCentralWidget(page)
        self.shortcut = QShortcut(QKeySequence("F11"), self)
        self.shortcut.activated.connect(self.toggle_fullscreen)

    def closeEvent(self, event):
        QMainWindow.closeEvent(self, event)


class DisplaySettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_immediate_mode_clicks_and_keyboard_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            window = DisplayHarness(str(Path(directory) / "settings.ini"))
            window.show()
            window.activateWindow()
            QTest.qWait(50)
            page = window.pages["Settings"]
            try:
                for _ in range(3):
                    for mode in ("Full Screen", "Windowed", "Borderless Window", "Windowed"):
                        QTest.mouseClick(page.mode_buttons[mode], Qt.LeftButton)
                        QTest.qWait(30)
                        self.assertEqual(window._display_mode, mode)
                        self.assertEqual(bool(window.windowFlags() & Qt.FramelessWindowHint), mode != "Windowed")
                        self.assertTrue(window.isVisible())
                        self.assertEqual(window._settings.value("display/mode"), mode)
                        if mode != "Windowed":
                            self.assertEqual(window.geometry(), window.screen().geometry())
                    for expected in ("Full Screen", "Windowed"):
                        window.activateWindow()
                        page.mode_buttons["Windowed"].setFocus()
                        QTest.qWait(30)
                        QTest.keyClick(page.mode_buttons["Windowed"], Qt.Key_F11)
                        QTest.qWait(30)
                        self.assertEqual(window._display_mode, expected)
                        self.assertTrue(page.mode_buttons[expected].isChecked())
                    page._apply_settings()
                    self.app.processEvents()
                    self.assertEqual(window._display_mode, "Windowed")
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
