from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy

from python.app.PageShell import DetailPage


class OptimizationPage(DetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__(
            "Optimization",
            "Optimize and stabilize beam performance",
            "Back to Automation",
            go_back,
        )

        _, panel_layout = self.add_workspace()
        placeholder = QLabel("Optimization workspace\n\nPID and beam optimization controls will be added here.")
        placeholder.setObjectName("chartPlaceholder")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        panel_layout.addWidget(placeholder, 1)
