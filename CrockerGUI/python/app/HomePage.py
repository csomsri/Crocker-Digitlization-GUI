from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
)

from python.app.PageShell import PageShell


class HomePage(PageShell):
    def __init__(
        self,
        categories: list[str],
        show_category: Callable[[str], None],
    ) -> None:
        super().__init__("Home", "Main Dashboard / Launcher")

        hub = QFrame()
        hub.setObjectName("workspace")
        hub_layout = QVBoxLayout(hub)
        hub_layout.setContentsMargins(24, 24, 24, 24)
        hub_layout.setSpacing(18)

        hub_title = QLabel("Select a UI area")
        hub_title.setObjectName("workspaceTitle")

        carousel = QHBoxLayout()
        carousel.setSpacing(14)

        for category in categories:
            button = QPushButton(category)
            button.setObjectName("categoryButton")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(
                lambda checked=False, name=category: show_category(name)
            )
            carousel.addWidget(button)

        hub_layout.addWidget(hub_title)
        hub_layout.addLayout(carousel)
        hub_layout.addSpacerItem(
            QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding)
        )

        self.layout.addWidget(hub, 1)
