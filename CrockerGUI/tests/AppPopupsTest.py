"""In-window popup lifecycle, nested modality, file selection, and transient UI."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QDate, QEvent, QObject, QPoint, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QLabel, QCalendarWidget, QLineEdit
from python.app.widgets.AppDialogs import AppDialog, AppMessageBox, FilePicker
from python.app.widgets.InlinePopups import InlinePopup, ScreenSafeDateEdit, install_popup_service
from python.app.widgets.PidDialog import setup_pid_dialog
from python.app.Display.WindowMode import set_screen_filling, set_decorated


class PopupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        install_popup_service(cls.app)

    def setUp(self):
        self.window = QMainWindow()
        self.launch = QPushButton('Open')
        self.window.setCentralWidget(self.launch)
        set_screen_filling(self.window, self.app.primaryScreen())
        self.window.activateWindow()
        self.launch.setFocus()
        QTest.qWait(50)
        self.directory = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.directory.cleanup()

    def dialog(self, owner=None):
        dialog = AppDialog(owner or self.launch)
        dialog.resize(650, 450)
        layout = setup_pid_dialog(dialog, 'Settings', window_controls=False)
        button = QPushButton('Close')
        button.clicked.connect(dialog.reject)
        layout.addWidget(button)
        return dialog

    def test_windowed_resize(self):
        set_decorated(self.window)
        self.window.resize(1000, 700)
        dialog = self.dialog()
        dialog.show()
        self.window.resize(800, 600)
        self.app.processEvents()
        self.assertFalse(dialog.isWindow())
        self.assertEqual(dialog._dialog_overlay.geometry(), self.window.rect())
        self.assertTrue(dialog._dialog_overlay.rect().contains(dialog.geometry()))
        dialog.reject()

    def test_reopen_and_nested_focus(self):
        outer = self.dialog()
        for _ in range(3):
            outer.show()
            self.assertFalse(outer.isWindow())
            self.assertFalse(self.launch.isEnabled())
            first_overlay = outer._dialog_overlay
            inner = self.dialog(outer)
            inner.open()
            self.assertFalse(first_overlay.isEnabled())
            self.assertFalse(inner.isWindow())
            inner.reject()
            self.assertTrue(first_overlay.isEnabled())
            self.assertTrue(outer.isVisible())
            self.assertIs(inner.parentWidget(), outer)
            outer.close()
            self.assertTrue(self.launch.isEnabled())
            self.assertTrue(self.launch.hasFocus())
            self.assertIs(outer.parentWidget(), self.launch)

    def test_exec_and_safe_confirmation_default(self):
        dialog = self.dialog()
        QTimer.singleShot(30, dialog.accept)
        self.assertEqual(dialog.exec(), AppDialog.Accepted)
        box = AppMessageBox(AppMessageBox.Warning, 'Confirm', 'Apply the change?',
                            AppMessageBox.Yes | AppMessageBox.No, self.launch)
        box.setDefaultButton(AppMessageBox.No)
        box.open()
        self.assertFalse(box.isWindow())
        self.assertEqual(box.defaultButton(), box.button(AppMessageBox.No))
        self.assertEqual(self.app.focusWidget(), box.button(AppMessageBox.No))
        QTest.keyClick(self.app.focusWidget(), Qt.Key_Return)
        self.assertEqual(box.result(), AppMessageBox.No)
        self.assertTrue(self.launch.isEnabled())

    def test_file_open_save_and_overwrite_cancel(self):
        folder = Path(self.directory.name)
        source = folder / 'sample.csv'
        source.write_text('original')
        picker = FilePicker(self.launch, 'Open file', str(folder), 'CSV (*.csv)')
        picker.show()
        picker.filename.setText('missing.csv')
        picker.accept()
        self.assertTrue(picker.isVisible())
        picker.filename.setText(source.name)
        picker.accept()
        self.assertEqual(Path(picker.selected_path), source)
        save = FilePicker(self.launch, 'Save file', str(folder), 'CSV (*.csv)', save=True)
        save.show()
        save.filename.setText('new')
        save.accept()
        self.assertEqual(Path(save.selected_path), folder / 'new.csv')
        self.assertFalse((folder / 'new.csv').exists())
        save.show()
        save.filename.setText(source.name)
        def cancel_replace():
            box = next(b for b in self.window.findChildren(AppMessageBox) if b.isVisible())
            box.button(AppMessageBox.No).click()
        QTimer.singleShot(30, cancel_replace)
        save.accept()
        self.assertTrue(save.isVisible())
        self.assertEqual(source.read_text(), 'original')
        save.reject()
        self.assertTrue(self.launch.isEnabled())

    def test_finished_callback_can_close_owner(self):
        box = AppMessageBox(AppMessageBox.Warning, 'Recording incomplete', 'Test message',
                            AppMessageBox.Ok, self.window)
        results = []
        box.finished.connect(lambda result: (results.append(result), self.window.close()))
        box.open()
        box.button(AppMessageBox.Ok).click()
        self.assertEqual(results, [int(AppMessageBox.Ok)])
        self.assertFalse(self.window.isVisible())

    def test_owner_close_unblocks_modal_loop(self):
        dialog = self.dialog()
        QTimer.singleShot(30, self.window.close)
        self.assertEqual(dialog.exec(), AppDialog.Rejected)
        self.assertTrue(self.launch.isEnabled())

    def test_calendar_tooltip_and_text_menu_are_children(self):
        dialog = self.dialog()
        date = ScreenSafeDateEdit()
        date.setCalendarPopup(True)
        date.setDate(QDate(2026, 9, 22))
        dialog.layout().addWidget(date)
        dialog.show()
        QTest.mouseClick(date, Qt.LeftButton, pos=QPoint(date.width()-8, date.height()//2))
        popup = next(p for p in self.window.findChildren(InlinePopup) if p.isVisible())
        calendar = popup.findChild(QCalendarWidget)
        self.assertFalse(popup.isWindow())
        self.assertIsNone(self.app.activePopupWidget())
        calendar.clicked.emit(QDate(2026, 9, 23))
        self.assertEqual(date.date(), QDate(2026, 9, 23))
        QTest.keyClick(date, Qt.Key_F4)
        popup = next(p for p in self.window.findChildren(InlinePopup) if p.isVisible())
        QTest.keyClick(popup.findChild(QCalendarWidget), Qt.Key_Escape)
        self.assertTrue(dialog.isVisible())
        edit = date.findChild(QLineEdit)
        event = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(5, 5), edit.mapToGlobal(QPoint(5, 5)))
        self.app.sendEvent(edit, event)
        menu = next(p for p in self.window.findChildren(InlinePopup) if p.isVisible())
        self.assertFalse(menu.isWindow())
        self.assertIsNone(self.app.activePopupWidget())
        menu.dismiss()
        tip = install_popup_service()
        tip.show_tip(date.mapToGlobal(QPoint()), 'Help text', date)
        self.assertFalse(tip.label.isWindow())
        self.assertTrue(tip.label.isVisible())
        tip.hide_tip()
        dialog.reject()


if __name__ == '__main__':
    unittest.main()
