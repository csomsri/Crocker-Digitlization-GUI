from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow

if TYPE_CHECKING:
    from python.app.MainWindow import MainWindow


class AssignedMonitorWindow(QMainWindow):
    """Hosts one assigned application page on an auxiliary monitor."""

    def __init__(self, owner: MainWindow, screen_name: str) -> None:
        super().__init__()
        self.owner = owner
        self.screen_name = screen_name
        self.page_name = ""
        self.setWindowTitle(f"Crocker Display - {screen_name}")

    def set_page(self, page_name: str) -> None:
        if page_name == self.page_name and self.centralWidget() is not None:
            return
        old_page = self.takeCentralWidget()
        if old_page is not None:
            old_page.deleteLater()
        self.setCentralWidget(
            self.owner.create_assigned_page(page_name, self)
        )
        self.page_name = page_name

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
