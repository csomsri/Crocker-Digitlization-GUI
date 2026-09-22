"""Application dialogs presented inside their owning window."""
from pathlib import Path
import re

from PySide6.QtCore import QDir, QEventLoop, Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QMessageBox, QWidget, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTreeView, QFileSystemModel,
    QAbstractItemView, QSizeGrip, QDialogButtonBox, QStyle, QScrollArea, QTabWidget,
)
from shiboken6 import isValid
from python.app.widgets.DialogOverlay import DialogOverlay
from python.app.widgets.PidDialog import setup_pid_dialog
from python.app.widgets.ScreenSafeComboBox import ScreenSafeComboBox


class _OverlayPresentation:
    def show(self):
        overlay = getattr(self, '_dialog_overlay', None)
        if overlay is not None and isValid(overlay):
            overlay.raise_()
            return
        owner = self.parentWidget() or QApplication.activeWindow()
        if owner is None:
            raise RuntimeError('Application dialogs require an owning window')
        # Simple dialogs get the same surface as
        # settings panels. Existing themed dialogs retain their content layout.
        if not self.findChild(QWidget, 'dialogTitleBar'):
            content = QWidget()
            if self.layout() is not None:
                content.setLayout(self.layout())
            layout = setup_pid_dialog(self, self.windowTitle(), window_controls=False, resize_grip=False)
            layout.addWidget(content)
        for grip in self.findChildren(QSizeGrip):
            grip.hide()
        for scroll in self.findChildren(QScrollArea):
            if scroll.widget() is not None:
                scroll.widget().setProperty('dialogScrollContents', True)
        for tabs in self.findChildren(QTabWidget):
            tabs.setDocumentMode(True)
            tabs.tabBar().setExpanding(True)
        title = self.findChild(QWidget, 'dialogTitleBar')
        if title is not None:
            for label in title.findChildren(QLabel):
                label.setWordWrap(False)
        self.ensurePolished()
        explicit_size = self.testAttribute(Qt.WA_Resized)
        requested = self.size() if explicit_size else self.sizeHint()
        self._dialog_overlay = DialogOverlay(
            self, owner, size=(max(420 if explicit_size else 680, requested.width()), max(220, requested.height())), retain=True)

    def open(self):
        self.show()

    def exec(self):
        loop = QEventLoop(self)
        self.finished.connect(loop.quit)
        self.destroyed.connect(loop.quit)
        self.show()
        if self.isVisible():
            loop.exec()
        if not isValid(self):
            return QDialog.Rejected
        self.finished.disconnect(loop.quit)
        self.destroyed.disconnect(loop.quit)
        loop.deleteLater()
        return self.result()

    def done(self, result):
        # Restore the owner before application finished-handlers run (some
        # close the owner or open another dialog, notably recording shutdown).
        overlay = getattr(self, '_dialog_overlay', None)
        if overlay is not None and isValid(overlay):
            overlay._finish(result)
        super().done(result)

    def hide(self):
        overlay = getattr(self, '_dialog_overlay', None)
        if overlay is not None and isValid(overlay):
            overlay._finish()
        else:
            super().hide()

    def activateWindow(self):
        # Focus a control in the existing window; never activate a second HWND.
        overlay = getattr(self, '_dialog_overlay', None)
        if overlay is not None:
            overlay._advance_focus(True)


class AppDialog(_OverlayPresentation, QDialog):
    pass


class AppMessageBox(AppDialog):
    StandardButton = QMessageBox.StandardButton
    Warning, Information = QMessageBox.Warning, QMessageBox.Information
    Ok, Yes, No = QMessageBox.Ok, QMessageBox.Yes, QMessageBox.No
    Cancel, NoButton = QMessageBox.Cancel, QMessageBox.NoButton

    def __init__(self, icon, title, text, buttons=QMessageBox.Ok, parent=None):
        super().__init__(parent)
        self.resize(560, 260)
        layout = setup_pid_dialog(self, title, window_controls=False, resize_grip=False)
        message_body = QWidget()
        row = QHBoxLayout(message_body)
        row.setContentsMargins(0, 4, 0, 4)
        symbol = QLabel()
        standard_icon = QStyle.SP_MessageBoxWarning if icon == QMessageBox.Warning else QStyle.SP_MessageBoxInformation
        symbol.setPixmap(self.style().standardIcon(standard_icon).pixmap(32, 32))
        row.addWidget(symbol, 0, Qt.AlignTop)
        message = QLabel(text)
        message.setTextFormat(Qt.PlainText)
        message.setWordWrap(True)
        message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(message, 1, Qt.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(message_body)
        layout.addWidget(scroll, 1)
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton(int(buttons)))
        layout.addWidget(self._buttons)
        self._buttons.clicked.connect(lambda button: self.done(self._buttons.standardButton(button).value))
        self._default = None
        for button in self._buttons.buttons():
            button.setAutoDefault(False)
        for candidate in (self.No, self.Cancel, self.Ok, self.Yes):
            if self.button(candidate) is not None:
                self.setDefaultButton(candidate)
                break

    def show(self):
        super().show()
        if self._default is not None:
            self._default.setFocus(Qt.OtherFocusReason)

    def button(self, standard):
        return self._buttons.button(QDialogButtonBox.StandardButton(int(standard)))

    def setDefaultButton(self, standard):
        if self._default is not None:
            self._default.setDefault(False)
        self._default = self.button(standard)
        if self._default is not None:
            self._default.setDefault(True)

    def defaultButton(self):
        return self._default

    def reject(self):
        for candidate in (self.No, self.Cancel, self.Ok):
            if self.button(candidate) is not None:
                self.done(int(candidate))
                return
        super().reject()

    @classmethod
    def warning(cls, parent, title, text, buttons=QMessageBox.Ok, defaultButton=QMessageBox.NoButton):
        box = cls(QMessageBox.Warning, title, text, buttons, parent)
        if defaultButton != QMessageBox.NoButton:
            box.setDefaultButton(defaultButton)
        try:
            return box.exec()
        finally:
            box.deleteLater()


class FilePicker(AppDialog):
    """Read-only file browser; returns a path and never writes the chosen file."""
    def __init__(self, parent, caption, directory, filters, *, save=False):
        super().__init__(parent)
        self.save_mode = save
        self.selected_path = ''
        self.setWindowTitle(caption)
        self.resize(900, 650)
        layout = setup_pid_dialog(self, caption, window_controls=False, resize_grip=False)
        navigation = QHBoxLayout()
        up = QPushButton('Up one folder')
        self.location = QLineEdit()
        self.location.setAccessibleName('Folder path')
        navigation.addWidget(up)
        navigation.addWidget(self.location, 1)
        layout.addLayout(navigation)
        self.model = QFileSystemModel(self)
        self.model.setReadOnly(True)
        self.model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)
        self.model.setNameFilterDisables(False)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        self.tree.setColumnWidth(0, 360)
        layout.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.filename = QLineEdit()
        self.filename.setAccessibleName('File name')
        self.filters = ScreenSafeComboBox()
        self.filters.addItems(filters.split(';;') if filters else ['All files (*)'])
        row.addWidget(QLabel('File name'))
        row.addWidget(self.filename, 1)
        row.addWidget(self.filters)
        layout.addLayout(row)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        choose = QPushButton('Save' if save else 'Open')
        choose.setObjectName('dialogPrimaryAction')
        choose.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(choose)
        layout.addLayout(actions)
        for button in (up, cancel, choose):
            button.setAutoDefault(False)
        candidate = Path(directory or Path.home()).expanduser()
        self.folder = candidate if candidate.is_dir() else candidate.parent
        self.filename.setText('' if candidate.is_dir() else candidate.name)
        self._navigate(self.folder)
        up.clicked.connect(lambda: self._navigate(self.folder.parent))
        self.location.returnPressed.connect(lambda: self._navigate(Path(self.location.text()).expanduser()))
        self.tree.clicked.connect(self._select)
        self.tree.doubleClicked.connect(self._activate)
        self.filename.returnPressed.connect(self.accept)
        self.filters.currentTextChanged.connect(self._filter)
        self._filter()

    def _filter(self, *_):
        match = re.search(r'\(([^()]*)\)', self.filters.currentText())
        self.model.setNameFilters(match.group(1).split() if match else ['*'])

    def _navigate(self, path):
        if not path.is_dir():
            self.error.setText('Folder not found. Enter an existing folder path.')
            return
        self.folder = path.resolve()
        self.location.setText(str(self.folder))
        self.tree.setRootIndex(self.model.setRootPath(str(self.folder)))
        self.error.clear()

    def _select(self, index):
        path = Path(self.model.filePath(index))
        if path.is_file():
            self.filename.setText(path.name)

    def _activate(self, index):
        path = Path(self.model.filePath(index))
        if path.is_dir():
            self._navigate(path)
        else:
            self.filename.setText(path.name)
            self.accept()

    def accept(self):
        name = self.filename.text().strip()
        if not name:
            self.error.setText('Enter or select a file name.')
            return
        path = Path(name).expanduser()
        if not path.is_absolute():
            path = self.folder / path
        if path.is_dir():
            self._navigate(path)
            return
        if self.save_mode:
            if not path.suffix:
                extension = re.search(r'\*([.][a-zA-Z0-9]+)', self.filters.currentText())
                if extension:
                    path = path.with_suffix(extension.group(1))
            if not path.parent.is_dir():
                self.error.setText('The destination folder does not exist.')
                return
            if path.exists() and AppMessageBox.warning(self, 'Replace existing file?',
                    f'{path.name} already exists. Replace it?',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        elif not path.is_file():
            self.error.setText('File not found. Select an existing file.')
            return
        self.selected_path = str(path)
        super().accept()


class AppFileDialog:
    @staticmethod
    def _choose(parent, caption, directory, filter, save):
        picker = FilePicker(parent, caption, directory, filter, save=save)
        try:
            accepted = picker.exec() == QDialog.Accepted
            return (picker.selected_path, picker.filters.currentText()) if accepted else ('', '')
        finally:
            picker.deleteLater()

    @staticmethod
    def getOpenFileName(parent, caption='', directory='', filter=''):
        return AppFileDialog._choose(parent, caption, directory, filter, False)

    @staticmethod
    def getSaveFileName(parent, caption='', directory='', filter=''):
        return AppFileDialog._choose(parent, caption, directory, filter, True)
