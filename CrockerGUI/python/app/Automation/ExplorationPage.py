from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy

from python.app.PageShell import DetailPage


class ExplorationPage(DetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__(
            "Exploration",
            "Explore and characterize daily machine settings",
            "Back to Automation",
            go_back,
        )

        _, panel_layout = self.add_workspace()
        placeholder = QLabel("Exploration workspace\n\nControls and results will be added here.")
        placeholder.setObjectName("chartPlaceholder")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        panel_layout.addWidget(placeholder, 1)
