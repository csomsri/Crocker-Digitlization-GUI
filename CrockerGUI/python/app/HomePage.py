from collections.abc import Callable

from PySide6.QtWidgets import (
    QHBoxLayout,
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
    "Automation": "AI CONTROL",
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

        outer = QHBoxLayout()
        outer.setContentsMargins(64, 78, 88, 72)
        outer.setSpacing(46)

        button_stack = QVBoxLayout()
        button_stack.setContentsMargins(0, 0, 0, 0)
        button_stack.setSpacing(22)

        for category in categories:
            button = CnlPanelButton(HOME_LABELS.get(category, category))
            button.setMinimumSize(330, 118)
            button.setMaximumSize(380, 138)
            button.setProperty("corner", "bottom-right")
            button.clicked.connect(
                lambda checked=False, name=category: show_category(name)
            )
            button_stack.addWidget(button)

        exit_button = QPushButton("EXIT")
        exit_button.setObjectName("homeExitButton")
        exit_button.setMinimumSize(330, 64)
        exit_button.setMaximumSize(380, 76)
        exit_button.clicked.connect(lambda checked=False: exit_app())
        button_stack.addWidget(exit_button)

        viewport = CnlViewportPlaceholder()

        outer.addLayout(button_stack, 0)
        outer.addWidget(viewport, 1)
        self.layout.addLayout(outer, 1)
