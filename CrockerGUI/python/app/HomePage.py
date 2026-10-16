from collections.abc import Callable
from PySide6.QtCore import Qt, QTimer

from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget
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
        super().__init__("Home", "")
        self.header.hide()
        heading = QHBoxLayout()
        heading.setContentsMargins(24, 24, 24, 12)
        text = QVBoxLayout()
        title = QLabel("Home")
        title.setObjectName("homeWorkspaceTitle")
        text.addWidget(title)
        subtitle = QLabel("Choose an area of the control workspace.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("homeCategoryDescription")
        text.addWidget(subtitle)
        heading.addLayout(text, 1)
        self.exit_button = QPushButton("Exit")
        self.exit_button.setAccessibleName("Exit application")
        self.exit_button.setToolTip("Close the application and finish saving recordings")
        self.exit_button.setCursor(Qt.PointingHandCursor)
        self.exit_button.setObjectName("workspaceExitButton")
        self.exit_button.clicked.connect(lambda checked=False: exit_app())
        heading.addWidget(self.exit_button, 0, Qt.AlignTop)
        self.layout.addLayout(heading)
        self.cards = QVBoxLayout()
        self.cards.setContentsMargins(24, 12, 24, 24)
        self.cards.setSpacing(12)
        self.category_cards = []
        self._button_labels = []
        for category in categories:
            button = QPushButton()
            button.setObjectName("homeNavigationButton")
            button.setAccessibleName("Open " + category)
            button.setToolTip("Open the " + category.lower() + " workspace")
            button.setCursor(Qt.PointingHandCursor)
            content = QHBoxLayout(button)
            content.setContentsMargins(22, 18, 22, 18)
            content.setSpacing(20)
            text = QWidget()
            text.setAttribute(Qt.WA_TransparentForMouseEvents)
            labels = QVBoxLayout(text)
            labels.setContentsMargins(0, 0, 0, 0)
            labels.setSpacing(5)
            title = QLabel(category)
            title.setObjectName("homeCategoryTitle")
            labels.addWidget(title)
            description = QLabel(HOME_LABELS.get(category, ""))
            description.setObjectName("homeCategoryDescription")
            description.setWordWrap(True)
            labels.addWidget(description)
            content.addWidget(text, 1)
            arrow = QLabel("→")
            arrow.setObjectName("homeNavigationArrow")
            arrow.setAttribute(Qt.WA_TransparentForMouseEvents)
            arrow.setFixedWidth(28)
            arrow.setAlignment(Qt.AlignCenter)
            content.addWidget(arrow)
            button.clicked.connect(lambda checked=False, name=category: show_category(name))
            self.cards.addWidget(button)
            self.category_cards.append(button)
            self._button_labels.append((title, description))
        self.layout.addLayout(self.cards)
        self.layout.addStretch()

    def _align_button_heights(self):
        width = max(80, self.scroll_area.viewport().width() - 48 - 44 - 20 - 28)
        height = max([104] + [36 + title.sizeHint().height() + 5 +
                     max(description.sizeHint().height(), description.heightForWidth(width))
                     for title, description in self._button_labels])
        for button in self.category_cards:
            # Explicit style bounds survive application theme repolishing.
            button.setStyleSheet(f'QPushButton#homeNavigationButton {{ min-height: {height}px; max-height: {height}px; }}')

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._align_button_heights)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._align_button_heights)
