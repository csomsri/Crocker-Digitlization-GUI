from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QStyle


class DialogTitleBar(QFrame):
    """Draggable title bar for a frameless dialog, with a native move fallback."""

    def __init__(self, dialog, title: str, window_controls: bool = True) -> None:
        super().__init__(dialog)
        self._dialog = dialog
        self.setObjectName("dialogTitleBar")
        self.setFixedHeight(42)
        self._drag_offset = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 4, 2)
        label = QLabel(title)
        label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(label)
        layout.addStretch()
        for title, icon, action in (
            ('Minimize', QStyle.SP_TitleBarMinButton, dialog.showMinimized),
            ('Maximize / restore', QStyle.SP_TitleBarMaxButton,
             lambda: dialog.showNormal() if dialog.isMaximized() else dialog.showMaximized()),
            ('Close', QStyle.SP_TitleBarCloseButton, dialog.close),
        ) if window_controls else ():
            button = QPushButton()
            button.setObjectName('dialogWindowControl')
            button.setIcon(self.style().standardIcon(icon))
            button.setToolTip(title)
            button.setAccessibleName(title)
            button.setFixedSize(30, 28)
            button.clicked.connect(action)
            layout.addWidget(button)
        self.setToolTip("Drag to move")

    def mousePressEvent(self, event) -> None:
        if not self._dialog.isWindow():
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            self._drag_offset = None
            window = self.window()
            handle = window.windowHandle()
            if handle is None or not handle.startSystemMove():
                self._drag_offset = event.globalPosition().toPoint() - window.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)
