"""The hardware editor stays in its owner and retains modal keyboard behavior."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton
from python.app.Automation.HardwareProfileDialog import HardwareProfileDialog, PROFILE_PATH
from python.app.Display.WindowMode import set_screen_filling
from python.app.theme import load_stylesheet
from python.app.widgets.DialogOverlay import DialogOverlay


class Events(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.disruptions = []
        parent.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.WindowDeactivate, QEvent.Hide, QEvent.WindowStateChange):
            self.disruptions.append(event.type())
        return False


app = QApplication([])
app.setStyle('Fusion')
window = QMainWindow()
window.setStyleSheet(load_stylesheet('Segoe UI'))
launch = QPushButton('Edit hardware profile')
window.setCentralWidget(launch)
set_screen_filling(window, app.primaryScreen())
window.activateWindow()
launch.setFocus()
QTest.qWait(150)
events = Events(window)
original = PROFILE_PATH.read_bytes()
try:
    for close_with_escape in (False, True):
        dialog = HardwareProfileDialog(launch, [f'TC{i}' for i in range(1, 13)],
                                       initial_channel='TC10', can_save=lambda: False)
        overlay = DialogOverlay(dialog, launch)
        QTest.qWait(150)
        assert not dialog.isWindow() and dialog.window() is window
        assert not launch.isEnabled()
        assert overlay.geometry() == window.rect()
        assert overlay.rect().contains(dialog.geometry())
        for index in range(3):
            QTest.mouseClick(dialog.tabs.tabBar(), Qt.LeftButton,
                             pos=dialog.tabs.tabBar().tabRect(index).center())
            assert dialog.tabs.currentIndex() == index
        for _ in range(30):
            QTest.keyClick(app.focusWidget(), Qt.Key_Tab)
            assert dialog.isAncestorOf(app.focusWidget())
        dialog.tabs.setCurrentIndex(0)
        dialog.channel.showPopup()
        assert dialog.channel._inline_menu is not None
        QTest.keyClick(dialog.channel._inline_menu, Qt.Key_Escape)
        assert dialog.isVisible()
        dialog.save_profile()
        assert dialog.status.text().startswith('Not saved: Stop PID')
        assert PROFILE_PATH.read_bytes() == original
        if len(sys.argv) > 1:
            dialog.status.setText('Loaded: approved. Save defaults to draft.')
            dialog.grab().save(sys.argv[1])
        if close_with_escape:
            QTest.keyClick(dialog.name, Qt.Key_Escape)
        else:
            close = next(b for b in dialog.findChildren(QPushButton) if b.text() == 'Close')
            QTest.mouseClick(close, Qt.LeftButton)
        QTest.qWait(50)
        assert launch.isEnabled() and launch.hasFocus()
        assert not events.disruptions, events.disruptions
    print('Hardware profile overlay, tabs, focus, close, and save guard passed')
finally:
    window.close()
