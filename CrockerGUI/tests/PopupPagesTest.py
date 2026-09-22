"""Open real control-page dialogs in simulation without issuing commands."""
import os
import sys
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt, QEvent, QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow
from python.app.Automation.PidControlPage import PidControlPage
from python.app.Automation.HybridPIDPage import HybridPIDPage
from python.app.Automation.GAPIDPage import GAPIDPage
from python.app.widgets.AppDialogs import AppDialog
from python.app.widgets.InlinePopups import install_popup_service
from python.app.Display.WindowMode import set_screen_filling
from python.app.theme import load_stylesheet

class WindowEvents(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.disruptions = []
        window.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.WindowDeactivate, QEvent.Hide, QEvent.WindowStateChange):
            self.disruptions.append(event.type())
        return False


QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
app = QApplication([])
app.setStyle('Fusion')
install_popup_service(app)
window = QMainWindow()
window.setStyleSheet(load_stylesheet('Segoe UI'))
events = WindowEvents(window)
set_screen_filling(window, app.primaryScreen())
try:
    count = 0
    for page_class in (PidControlPage, HybridPIDPage, GAPIDPage):
        page = page_class(lambda: None, backend_mode='simulation')
        window.setCentralWidget(page)
        QTest.qWait(100)
        dialogs = page.findChildren(AppDialog)
        if isinstance(page, PidControlPage):
            dialogs.append(page._build_metrics_dialog())
        for dialog in dialogs:
            for _ in range(2):
                events.disruptions.clear()
                dialog.show()
                QTest.qWait(60)
                assert not dialog.isWindow(), dialog.windowTitle()
                assert dialog.window() is window
                assert window.rect().contains(dialog._dialog_overlay.geometry())
                assert dialog.isEnabled()
                if len(sys.argv) > 1 and _ == 0:
                    directory = Path(sys.argv[1])
                    directory.mkdir(parents=True, exist_ok=True)
                    dialog.grab().save(str(directory / f'popup-{count}.png'))
                dialog.close()
                QTest.qWait(20)
                assert page.isEnabled()
                assert not events.disruptions, (dialog.windowTitle(), events.disruptions)
            count += 1
        page.stop_backend()
        window.takeCentralWidget()
        page.deleteLater()
    print(f'{count} real PID, hybrid, and GA dialogs opened and reopened successfully')
finally:
    window.close()
