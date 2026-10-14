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
from python.app.WorkspaceShell import WorkspaceShell
from python.app.PageRegistry import PAGE_BUILDERS, DETAIL_BUILDERS
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

    def test_sidebar_navigation_reuses_controller_and_preserves_inputs(self):
        with patch.object(Host, '_refresh_settings_monitors'):
            host = Host('unused-test-settings.ini')
            host._settings = MagicMock()
            host._settings.value.return_value = None
            host.workspace_shell = WorkspaceShell(
                host.stack, PAGE_BUILDERS, DETAIL_BUILDERS,
                host.go_to_page, host.open_page_window, 'simulation',
            )
            host.setCentralWidget(host.workspace_shell)
            host.stack.currentChanged.connect(
                lambda: host.workspace_shell.set_current(host._current_page_name()))
            host.show()
            page = host.pages['PID Control']
            page.setProperty('enteredTarget', 0.37)
            page.pid_enabled = True
            try:
                host.open_page('PID Control')
                self.assertIs(host.stack.currentWidget(), page)
                self.assertEqual(len(host._page_windows), 0)
                host.open_page_window('PID Control')
                window = host._page_windows['PID Control']
                self.assertIs(window.centralWidget(), page)
                self.assertTrue(page.isVisible())
                host.open_page_window('PID Control')
                self.assertEqual(len(host._page_windows), 1)
                host.go_to_page('PID Control')
                self.assertIs(host.stack.currentWidget(), page)
                self.assertIsNone(window.centralWidget())
                self.assertFalse(window.isVisible())
                self.assertTrue(page.pid_enabled)
                self.assertEqual(page.property('enteredTarget'), 0.37)
                self.assertTrue(host.workspace_shell.buttons['PID Control'].isChecked())
                host.open_page_window('PID Control')
                self.assertIs(host._page_windows['PID Control'], window)
                self.assertIs(window.centralWidget(), page)
                host.set_display_mode('Full Screen', save=False)
                self.app.processEvents()
                self.assertIsNone(window.centralWidget())
                self.assertGreaterEqual(host.stack.indexOf(page), 0)
                host.set_display_mode('Windowed', save=False)
                self.app.processEvents()
                self.assertIs(window.centralWidget(), page)
                self.assertTrue(page.isVisible())
                self.assertTrue(page.pid_enabled)
            finally:
                host._recording_closing = True
                for window in host._page_windows.values():
                    window.close()
                host.close()
                host.deleteLater()
                self.app.processEvents()

    def test_explicit_windows_support_categories_and_multiple_pages(self):
        host = Host('unused-test-settings.ini')
        host._settings = MagicMock()
        host._settings.value.return_value = None
        try:
            host.open_page_window('Automation')
            host.open_page_window('PID Control')
            self.assertEqual(len(host._page_windows), 2)
            for name in ('Automation', 'PID Control'):
                self.assertIs(host._page_windows[name].centralWidget(), host.pages[name])
                self.assertTrue(host.pages[name].isVisible())
            host.go_to_page('Automation')
            host.bring_page_windows_forward()
            self.assertIs(host.stack.currentWidget(), host.pages['Automation'])
            self.assertIsNone(host._page_windows['Automation'].centralWidget())
        finally:
            host._recording_closing = True
            for window in host._page_windows.values():
                window.close()
            host.close()
            host.deleteLater()
            self.app.processEvents()

    def test_detached_category_links_and_back_stay_in_their_window(self):
        from python.app.Monitoring.MonitoringPage import MonitoringPage
        from PySide6.QtWidgets import QPushButton
        host = Host('unused-test-settings.ini')
        host._settings = MagicMock()
        host._settings.value.return_value = None
        category = MonitoringPage(
            lambda: host.navigate_from('Monitoring', 'Home'),
            lambda title, purpose: host.navigate_from('Monitoring', title))
        host.stack.removeWidget(host.pages['Monitoring'])
        host.pages['Monitoring'] = category
        host.stack.addWidget(category)
        detail = RfPowerMonitoringPage(lambda: host.navigate_from('RF Power Monitoring', 'Monitoring'))
        host.pages['RF Power Monitoring'] = detail
        host.stack.addWidget(detail)
        host.show()
        host.go_to_page('Home')
        try:
            host.open_page_window('Monitoring')
            window = host._page_windows['Monitoring']
            button = next(b for b in category.category_cards if b.title == 'RF Power Monitoring')
            button.click()
            self.assertIs(host.stack.currentWidget(), host.pages['Home'])
            self.assertIs(window.centralWidget(), detail)
            self.assertIs(host._page_windows['RF Power Monitoring'], window)
            self.assertEqual(window.page_name, 'RF Power Monitoring')
            self.assertNotIn('Monitoring', host._page_windows)
            detail.findChild(QPushButton, 'navBackButton').click()
            self.assertIs(window.centralWidget(), category)
            self.assertIs(host.stack.currentWidget(), host.pages['Home'])
            self.assertIs(host._page_windows['Monitoring'], window)
            button.click()
            host.go_to_page('RF Power Monitoring')
            self.assertIs(host.stack.currentWidget(), detail)
            self.assertIsNone(window.centralWidget())
            self.assertFalse(window.isVisible())
            host.go_to_page('Home')
            host.open_page_window('Monitoring')
            replacement = host._page_windows['Monitoring']
            button.click()
            self.assertIs(replacement.centralWidget(), detail)
            self.assertIs(host.stack.currentWidget(), host.pages['Home'])
            self.assertEqual(sum(action.data() == 'RF Power Monitoring'
                                 for action in host._page_window_menu.actions()), 1)
        finally:
            detail.timer.stop()
            host._recording_closing = True
            for window in host._page_windows.values():
                window.close()
            host.close()
            host.deleteLater()
            self.app.processEvents()

    def test_directory_categories_and_page_actions_are_independent(self):
        from PySide6.QtWidgets import QPushButton
        navigate, detach = MagicMock(), MagicMock()
        shell = WorkspaceShell(QStackedWidget(), PAGE_BUILDERS, DETAIL_BUILDERS,
                               navigate, detach, 'simulation')
        try:
            shell.resize(1280, 820)
            shell.show()
            self.app.processEvents()

            shell.category_buttons['Monitoring'].click()
            self.assertFalse(shell.category_contents['Monitoring'].isHidden())
            shell.buttons['PID Control'].click()
            navigate.assert_called_once_with('PID Control')
            detach.assert_not_called()
            button = next(b for b in shell.findChildren(QPushButton)
                          if b.accessibleName() == 'Open PID Control in a separate window')
            button.click()
            detach.assert_called_once_with('PID Control')
            shell.set_current('RF Power Monitoring')
            self.assertTrue(shell.buttons['RF Power Monitoring'].isChecked())
            self.assertTrue(shell.category_buttons['Monitoring'].isChecked())
            shell.resize(480, 800)
            self.app.processEvents()
            self.assertTrue(shell.sidebar.isHidden())
            shell.toggle_sidebar.click()
            self.assertFalse(shell.sidebar.isHidden())
            shell.edge_toggle.click()
            self.assertTrue(shell.sidebar.isHidden())
            self.assertEqual(shell.edge_toggle.text(), '›')
            shell.edge_toggle.click()
            self.assertFalse(shell.sidebar.isHidden())
            self.assertEqual(shell.edge_toggle.text(), '‹')
        finally:
            shell.close()
            shell.deleteLater()
            self.app.processEvents()

    def test_category_cards_keep_readable_height_after_style_polish(self):
        from python.app.Monitoring.MonitoringPage import MonitoringPage
        from python.app.UIAnimation import UIAnimationController
        stack = QStackedWidget()
        category = MonitoringPage(lambda: None, lambda *args: None)
        stack.addWidget(category)
        motion = UIAnimationController(stack, stack)
        motion.attach_to(stack)
        stack.resize(1280, 820)
        stack.show()
        self.app.processEvents()
        try:
            self.assertEqual(len(category.category_cards), 6)
            for card in category.category_cards:
                self.assertGreaterEqual(card.height(), 128)
                card.style().unpolish(card)
                card.style().polish(card)
            self.app.processEvents()
            self.assertTrue(all(card.height() >= 128 for card in category.category_cards))
        finally:
            stack.close()
            stack.deleteLater()
            self.app.processEvents()

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
