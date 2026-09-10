from collections.abc import Callable

from python.app.ResponsiveLayout import ResponsiveRow

from PySide6.QtWidgets import (
    QPushButton,
    QVBoxLayout,
)

from python.app.PageShell import (
    CnlPanelButton,
    CnlViewportPlaceholder,
    PageShell,
)


HOME_LABELS = {
    "Manual Controls": "MANUAL CONTROL",
    "Automation": "AUTOMATION",
    "Configuration": "SETTINGS",
    "Monitoring": "MONITOR",
}


class HomePage(PageShell):
    def __init__(
        self,
        categories: list[str],
        show_category: Callable[[str], None],
        exit_app: Callable[[], None],
        ) -> None:
        super().__init__("Crocker Nuclear Lab Digital Control", "")

        outer = ResponsiveRow()
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(20)

        button_stack = QVBoxLayout()
        button_stack.setContentsMargins(0, 0, 0, 0)
        button_stack.setSpacing(22)

        for category in categories:
            button = CnlPanelButton(HOME_LABELS.get(category, category))
            button.setMinimumSize(160, 80)
            button.setProperty("corner", "bottom-right")
            button.clicked.connect(
                lambda checked=False, name=category: show_category(name)
            )
            button_stack.addWidget(button)

        exit_button = QPushButton("EXIT")
        exit_button.setObjectName("homeExitButton")
        exit_button.setMinimumSize(160, 40)
        exit_button.clicked.connect(lambda checked=False: exit_app())
        button_stack.addWidget(exit_button)

        viewport = CnlViewportPlaceholder()

        outer.addLayout(button_stack, 2)
        outer.addWidget(viewport, 5)
        self.layout.addLayout(outer, 1)
