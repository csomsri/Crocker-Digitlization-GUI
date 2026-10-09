"""Persistent hosts for the application's existing page instances."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QLabel, QPushButton
from python.app.widgets.AppDialogs import AppDialog
from python.app.Display.WindowMode import fit_decorated_window


class PageWindow(QMainWindow):
    def __init__(self, owner, name, page):
        super().__init__(owner, Qt.Window)
        self.owner, self.page_name, self.page = owner, name, page
        self.setWindowTitle(f"{name} — Crocker Digitalization")
        self.setMinimumSize(320, 240)
        self.setStyleSheet(owner.styleSheet())
        self.attach_page(page)
        menu = self.menuBar().addMenu("Workspace")
        menu.addAction("Home", owner.show_home)
        menu.addAction("Bring all windows forward", owner.bring_page_windows_forward)
        menu.addAction("Tile windows", owner.tile_page_windows)
        menu.addAction("Reset this window position", self.reset_position)
        self.reset_position()
        saved = owner._settings.value(f"workspace/{name}/geometry")
        if saved:
            self.restoreGeometry(saved)
        self.ensure_on_screen()

    def attach_page(self, page):
        self.setCentralWidget(page)
        # QStackedWidget.removeWidget explicitly hides its page. Reparenting it
        # alone preserves that state, leaving the new window's content blank.
        page.show()

    def reset_position(self):
        screen = self.owner.screen()
        if screen:
            fit_decorated_window(self, screen, self.owner._window_resolution_size())

    def ensure_on_screen(self):
        if self.isMaximized():
            return
        from PySide6.QtWidgets import QApplication
        if not any(screen.availableGeometry().contains(self.frameGeometry())
                   for screen in QApplication.screens()):
            self.reset_position()

    def closeEvent(self, event):
        # Closing a host must not destroy a shared page or its executor.
        active = any(getattr(self.page, key, False) for key in
                     ("pid_enabled", "tuning_session_active", "_sequence_running"))
        if active and not self.owner._recording_closing:
            dialog = AppDialog(self)
            dialog.setWindowTitle("Control is running")
            layout = QVBoxLayout(dialog)
            label = QLabel("This page has an active operation. Keeping it running hides the window; reopen it from Home.")
            label.setWordWrap(True)
            layout.addWidget(label)
            keep = QPushButton("Keep running and hide")
            keep.clicked.connect(dialog.accept)
            layout.addWidget(keep)
            stop = QPushButton("Stop control and hide")
            def stop_and_hide():
                navigation = getattr(self.page, 'cruise_navigation', None)
                if navigation is not None:
                    navigation.stop()
                elif hasattr(self.page, '_stop_tuning_session'):
                    self.page._stop_tuning_session()
                if (getattr(self.page, '_cruise_stop_failed', False) or
                    any(getattr(self.page, key, False) for key in
                        ('pid_enabled', 'tuning_session_active', '_sequence_running'))):
                    label.setText('Stop has not been confirmed. Keep the window open to inspect and retry.')
                    return
                dialog.accept()
            stop.clicked.connect(stop_and_hide)
            layout.addWidget(stop)
            cancel = QPushButton("Keep window open")
            cancel.clicked.connect(dialog.reject)
            layout.addWidget(cancel)
            result = dialog.exec()
            dialog.deleteLater()
            if result != AppDialog.Accepted:
                event.ignore()
                return
        self.owner._settings.setValue(f"workspace/{self.page_name}/geometry", self.saveGeometry())
        for child in self.page.findChildren(AppDialog):
            child.hide()
        event.accept()
