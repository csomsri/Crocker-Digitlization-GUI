"""Window reuse, mode changes, close policy and persistent PID tab regression checks."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT/'Debug', ROOT/'Release', ROOT/'build'/'Debug', ROOT/'build'/'Release'):
    sys.path.insert(0, str(folder))

from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QWidget, QTableWidget
from python.app.MainWindow import MainWindow
from python.app.widgets.AppDialogs import AppDialog
from python.app.Automation.PidControlPage import PidControlPage
from python.app.Automation.HybridPIDPage import HybridPIDPage
from python.app.Configuration.RecallPage import RecallPage
from python.app.Monitoring.RfPowerMonitoringPage import RfPowerMonitoringPage
from python.app.theme import load_stylesheet, load_app_font
from python.app.Display.WindowMode import fit_decorated_window, set_decorated, set_screen_filling


class Host(MainWindow):
    """Navigation without production database writers or hardware services."""
    def __init__(self, settings_path):
        QMainWindow.__init__(self)
        self._settings = QSettings(settings_path, QSettings.IniFormat)
        self._display_mode = 'Windowed'
        self._window_resolution = '1280 x 820'
        self._page_windows = {}
        self._monitor_windows = {}
        self._recording_closing = False
        self._display_transition = 0
        self._windowed_geometry = None
        self._page_window_menu = self.menuBar().addMenu('Workspace')
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.pages = {name: QWidget() for name in ('Home', 'Automation', 'Monitoring', 'Manual Controls', 'Configuration', 'PID Control')}
        for page in self.pages.values():
            self.stack.addWidget(page)

    def _refresh_settings_monitors(self):
        pass

    def closeEvent(self, event):
        event.accept()


class WorkspaceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(load_stylesheet(load_app_font()))

    def test_real_detail_content_visible_after_detach_and_reopen(self):
        host = Host('unused-test-settings.ini')
        host._settings = MagicMock()
        host._settings.value.return_value = None
        host.show()
        try:
            for name, builder in (('Recall', RecallPage), ('RF Power Monitoring', RfPowerMonitoringPage)):
                with self.subTest(page=name):
                    page = builder(lambda: host.show_category('Configuration'))
                    host.pages[name] = page
                    host.stack.addWidget(page)
                    self.assertTrue(page.isHidden())
                    host.open_page(name)
                    self.app.processEvents()
                    window = host._page_windows[name]
                    self.assertTrue(page.isVisible())
                    self.assertTrue(page.header.isVisible())
                    self.assertTrue(page.scroll_area.isVisible())
                    self.assertGreater(page.scroll_area.viewport().width(), 0)
                    window.close()
                    host.open_page(name)
                    self.app.processEvents()
                    self.assertTrue(page.header.isVisible())
                    self.assertIs(window.centralWidget(), page)
        finally:
            for window in host._page_windows.values():
                window.close()
            host.close()
            host.deleteLater()
            self.app.processEvents()

    def test_decorated_transition_fits_screen_without_geometry_warning(self):
        from PySide6.QtCore import qInstallMessageHandler
        warnings = []
        previous = qInstallMessageHandler(lambda kind, context, message: warnings.append(message))
        window = QMainWindow()
        window.setMinimumSize(320, 240)
        screen = self.app.primaryScreen()
        try:
            for _ in range(3):
                set_screen_filling(window, screen)
                self.app.processEvents()
                set_decorated(window)
                fit_decorated_window(window, screen, (10000, 10000))
                QTest.qWait(30)
                self.assertTrue(screen.availableGeometry().contains(window.frameGeometry()),
                                (screen.availableGeometry(), window.frameGeometry()))
            self.assertFalse(any('Unable to set geometry' in message for message in warnings), warnings)
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()
            qInstallMessageHandler(previous)

    def test_hybrid_wrapped_tuner_refresh_and_navigation(self):
        page = HybridPIDPage(lambda: None, 'simulation')
        page.timer.stop()
        try:
            nav = page.cruise_navigation
            page._refresh_status()
            self.assertIs(nav.targets[nav.tuning_tab_index], page.tuner_page)
            nav.tabs.setCurrentIndex(nav.tuning_tab_index)
            self.assertIs(page.page_stack.currentWidget(), page.tuner_page)
            page.tuner_target.setValue(.37)
            for target in (page._advanced_control_page, page.results_page, page.tuner_page):
                nav.tabs.setCurrentIndex(nav.targets.index(target))
                page._refresh_status()
                self.assertIs(page.page_stack.currentWidget(), target)
                self.assertEqual(nav.tabs.currentIndex(), nav.targets.index(target))
            self.assertAlmostEqual(page.tuner_target.value(), .37)
            page.tuning_session_active = True
            nav.refresh()
            self.assertIn('Running', nav.tabs.tabText(nav.tuning_tab_index))
            self.assertIn('GA + BO', nav.tabs.tabText(nav.tuning_tab_index))
            page.tuning_session_active = False
            nav.refresh()
            self.assertNotIn('Running', nav.tabs.tabText(nav.tuning_tab_index))
            page._tick_feedback()
        finally:
            page.tuning_session_active = False
            page.stop_backend()
            page.close()
            page.deleteLater()
            self.app.processEvents()

    def test_reuse_close_and_mode_change(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
            host = Host(str(Path(folder)/'settings.ini'))
            host.show()
            host.open_page('Automation')
            host.open_page('PID Control')
            window = host._page_windows['PID Control']
            page = host.pages['PID Control']
            host.open_page('PID Control')
            self.assertEqual(len(host._page_windows), 1)
            self.assertIs(window.centralWidget(), page)
            self.assertTrue(page.isVisible(), 'Detail page stayed hidden after leaving the navigation stack')
            self.assertIs(host.stack.currentWidget(), host.pages['Automation'])
            for category in ('Monitoring', 'Manual Controls', 'Configuration', 'Automation'):
                host.show_category(category)
                self.assertIs(host.stack.currentWidget(), host.pages[category])
                self.assertEqual(len(host._page_windows), 1)
            page.pid_enabled = True
            with patch.object(AppDialog, 'exec', return_value=AppDialog.Rejected):
                self.assertFalse(window.close())
                self.assertTrue(window.isVisible())
            with patch.object(AppDialog, 'exec', return_value=AppDialog.Accepted):
                self.assertTrue(window.close())
            self.assertTrue(page.pid_enabled)
            host.open_page('PID Control')
            self.assertIs(window.centralWidget(), page)
            self.assertTrue(page.isVisible(), 'Detail page stayed hidden after reopening')
            page.pid_enabled = False
            host.set_display_mode('Full Screen', save=False)
            self.app.processEvents()
            self.assertGreaterEqual(host.stack.indexOf(page), 0)
            self.assertIsNone(window.centralWidget())
            host.set_display_mode('Windowed', save=False)
            self.app.processEvents()
            self.assertIs(window.centralWidget(), page)
            self.assertTrue(window.isVisible())
            self.assertTrue(page.isVisible(), 'Detail page stayed hidden after a display-mode transition')
            host._recording_closing = True
            host.close()
            host.deleteLater()
            self.app.processEvents()

    def test_pid_tabs_preserve_inputs_and_fit(self):
        page = PidControlPage(lambda: None, 'simulation')
        page.timer.stop()
        try:
            page.show()
            nav = page.cruise_navigation
            nav.tabs.setCurrentIndex(nav.targets.index(page.tuner_page))
            page.tuner_target.setValue(.37)
            for target in (page._advanced_control_page, page.results_page, page.tuner_page):
                nav.tabs.setCurrentIndex(nav.targets.index(target))
                self.assertIs(page.page_stack.currentWidget(), target)
                self.assertFalse(page.pid_enabled)
            self.assertAlmostEqual(page.tuner_target.value(), .37)
            self.assertIsNotNone(page.results_page.findChild(QTableWidget))
            for width, height in ((480, 800), (800, 600), (1280, 820), (1920, 1080)):
                if self.app.platformName() == 'windows':
                    available = page.screen().availableGeometry()
                    width = min(width, available.width() - 32)
                    height = min(height, available.height() - 64)
                page.resize(width, height)
                for _ in range(12):
                    self.app.processEvents()
                self.assertEqual(page.width(), width)
                self.assertTrue(page.rect().contains(page.backend_status_panel.geometry()),
                                (width, height, page.rect(), page.backend_status_panel.geometry()))
            nav.tabs.setFocus()
            previous = nav.tabs.currentIndex()
            QTest.keyClick(nav.tabs, Qt.Key_Tab, Qt.ControlModifier)
            self.assertEqual(nav.tabs.currentIndex(), (previous+1) % nav.tabs.count())
        finally:
            page.stop_backend()
            page.close()
            page.deleteLater()
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
