from collections.abc import Callable
from PySide6.QtCore import Qt

from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QStyle
from python.app.PageShell import PageShell


HOME_LABELS = {
    "Monitoring": "Live equipment readings and trends.",
    "Manual Controls": "Field control, beam range, alarms and snapshots.",
    "Automation": "PID control, Bayesian tuning and Hybrid optimization.",
    "Configuration": "Connections, calibration, saved settings and history.",
}


class HomePage(PageShell):
    def __init__(
        self,
        categories: list[str],
        show_category: Callable[[str], None],
        exit_app: Callable[[], None],
        ) -> None:
        super().__init__("Control workspace", "")
        self.header.hide()
        heading = QHBoxLayout()
        heading.setContentsMargins(24, 24, 24, 12)
        text = QVBoxLayout()
        title = QLabel("Control workspace")
        title.setObjectName("homeWorkspaceTitle")
        text.addWidget(title)
        subtitle = QLabel("Select an area to monitor equipment, operate controls or configure the system.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("homeCategoryDescription")
        text.addWidget(subtitle)
        heading.addLayout(text, 1)
        self.exit_button = QPushButton("Exit application")
        self.exit_button.setObjectName("workspaceExitButton")
        self.exit_button.setIcon(self.style().standardIcon(QStyle.SP_DialogCloseButton))
        self.exit_button.clicked.connect(lambda checked=False: exit_app())
        heading.addWidget(self.exit_button, 0, Qt.AlignTop)
        self.layout.addLayout(heading)
        self.cards = QGridLayout()
        self.cards.setContentsMargins(20, 12, 20, 20)
        self.cards.setSpacing(16)
        self.category_cards = []
        for index, category in enumerate(categories):
            card = QFrame()
            card.setObjectName("homeCategoryCard")
            content = QVBoxLayout(card)
            content.setContentsMargins(24, 24, 24, 24)
            content.setSpacing(12)
            icon = QLabel(f"{index + 1:02d}")
            icon.setObjectName("homeCategoryIndex")
            content.addWidget(icon)
            title = QLabel(category)
            title.setObjectName("homeCategoryTitle")
            content.addWidget(title)
            description = QLabel(HOME_LABELS.get(category, ""))
            description.setObjectName("homeCategoryDescription")
            description.setWordWrap(True)
            content.addWidget(description)
            content.addSpacing(16)
            button = QPushButton("Open " + category.lower() + "  →")
            button.clicked.connect(lambda checked=False, name=category: show_category(name))
            button.setObjectName("homeCategoryAction")
            button.setCursor(Qt.PointingHandCursor)
            content.addWidget(button, 0, Qt.AlignLeft)
            self.cards.addWidget(card, index // 2, index % 2)
            self.category_cards.append(card)
        self.layout.addLayout(self.cards)
        self.layout.addStretch()

    def resizeEvent(self, event):
        columns = 1 if event.size().width() < 620 else 2
        for index, card in enumerate(self.category_cards):
            self.cards.addWidget(card, index // columns, index % columns)
        super().resizeEvent(event)
