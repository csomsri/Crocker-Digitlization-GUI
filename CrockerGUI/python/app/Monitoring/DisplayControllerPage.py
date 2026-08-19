from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from python.app.PageShell import DetailPage, MONITOR_PREVIEWS


class DisplayViewButton(QPushButton):
    def __init__(self, number: int, title: str, description: str) -> None:
        super().__init__()
        self.number = number
        self.title = title
        self.description = description
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(260, 150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        selected = self.isChecked()
        hovered = self.underMouse()
        painter.setBrush(QColor("#183b78") if selected else QColor("#172236"))
        painter.setPen(QPen(QColor("#60a5fa") if selected or hovered else QColor("#40516b"), 2 if selected else 1))
        painter.drawRoundedRect(rect, 9, 9)

        scale = max(0.85, min(1.25, self.height() / 190))
        badge_size = int(38 * scale)
        badge = rect.adjusted(20, 18, 0, 0)
        badge.setWidth(badge_size)
        badge.setHeight(badge_size)
        painter.setBrush(QColor("#2563eb") if selected else QColor("#24344e"))
        painter.setPen(QPen(QColor("#93c5fd") if selected else QColor("#52657f"), 1))
        painter.drawRoundedRect(badge, 6, 6)
        painter.setFont(QFont("Segoe UI", max(9, int(11 * scale)), QFont.Weight.Bold))
        painter.setPen(QColor("#eff6ff"))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, f"{self.number:02d}")

        title_rect = rect.adjusted(badge.right() - rect.left() + 15, 15, -18, -rect.height() + 50)
        painter.setFont(QFont("Segoe UI", max(10, int(13 * scale)), QFont.Weight.DemiBold))
        painter.setPen(QColor("#f8fafc"))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.title.upper())

        divider_y = badge.bottom() + 16
        painter.setPen(QPen(QColor("#4b6382") if selected else QColor("#334155"), 1))
        painter.drawLine(rect.left() + 20, divider_y, rect.right() - 20, divider_y)
        painter.setFont(QFont("Segoe UI", max(8, int(10 * scale))))
        painter.setPen(QColor("#93a9c5"))
        painter.drawText(
            rect.adjusted(20, divider_y - rect.top() + 14, -20, -18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            self.description,
        )


class DisplayControllerPage(DetailPage):
    """Operational selector for the monitoring page shown on managed displays."""

    def __init__(
        self,
        go_back: Callable[[], None],
        monitoring_pages: list[str],
        monitor_entries: Callable[[], list[dict[str, object]]],
        show_on_monitor: Callable[[str, str], bool],
        controller_layout: Callable[[], str],
    ) -> None:
        super().__init__(
            "Display Controller",
            "Route approved monitoring views to a managed display",
            "Back to Monitoring",
            go_back,
        )
        self._monitoring_pages = monitoring_pages
        self._monitor_entries = monitor_entries
        self._show_on_monitor = show_on_monitor
        self._controller_layout = controller_layout
        self._selected_page = monitoring_pages[0] if monitoring_pages else ""
        self._selected_monitor = ""

        _, layout = self.add_workspace()
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(14)

        target_panel = QFrame()
        target_panel.setObjectName("controllerTargetPanel")
        target_layout = QVBoxLayout(target_panel)
        target_layout.setContentsMargins(16, 12, 16, 12)
        target_layout.setSpacing(8)
        target_heading = QLabel("MANAGED DISPLAY")
        target_heading.setObjectName("controllerSectionHeading")
        target_layout.addWidget(target_heading)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self.target_value = self._status_block(status_row, "TARGET DISPLAY")
        self.access_value = self._status_block(status_row, "CONTROLLER ACCESS")
        self.layout_value = self._status_block(status_row, "ACTIVE LAYOUT")
        target_layout.addLayout(status_row)

        self.monitor_row = QHBoxLayout()
        self.monitor_row.setSpacing(10)
        target_layout.addLayout(self.monitor_row)
        layout.addWidget(target_panel)

        page_panel = QFrame()
        page_panel.setObjectName("monitorPagePicker")
        page_layout = QVBoxLayout(page_panel)
        page_layout.setContentsMargins(22, 18, 22, 22)
        page_layout.setSpacing(14)
        page_heading = QLabel("SELECT MONITORING VIEW")
        page_heading.setObjectName("controllerSectionHeading")
        page_layout.addWidget(page_heading)
        page_description = QLabel(
            "Choose the live visualization to send to the managed display."
        )
        page_description.setObjectName("settingsDescription")
        page_layout.addWidget(page_description)

        top_row = QHBoxLayout()
        top_row.setSpacing(14)
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(14)
        bottom_row.addStretch(1)
        self.page_buttons: dict[str, QPushButton] = {}
        for index, page_name in enumerate(monitoring_pages):
            preview = MONITOR_PREVIEWS.get(page_name, ["Live monitoring view"])[0]
            button = DisplayViewButton(index + 1, page_name, preview)
            button.setChecked(page_name == self._selected_page)
            button.clicked.connect(
                lambda checked=False, name=page_name: self._select_page(name)
            )
            self.page_buttons[page_name] = button
            if index < 3:
                top_row.addWidget(button, 1)
            else:
                bottom_row.addWidget(button, 2)
        bottom_row.addStretch(1)
        page_layout.addLayout(top_row, 1)
        page_layout.addLayout(bottom_row, 1)
        layout.addWidget(page_panel, 1)

        self.show_button = QPushButton("SHOW ON MONITOR")
        self.show_button.setObjectName("applySettingsButton")
        self.show_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_button.clicked.connect(self._apply)
        layout.addWidget(self.show_button)
        self.refresh()

    def _status_block(self, row: QHBoxLayout, title: str) -> QLabel:
        block = QFrame()
        block.setObjectName("controllerStatusBlock")
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(12, 8, 12, 8)
        block_layout.setSpacing(2)
        heading = QLabel(title)
        heading.setObjectName("controllerStatusLabel")
        value = QLabel("—")
        value.setObjectName("controllerStatusValue")
        value.setWordWrap(True)
        block_layout.addWidget(heading)
        block_layout.addWidget(value)
        row.addWidget(block, 1)
        return value

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        while self.monitor_row.count():
            item = self.monitor_row.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        managed = [
            entry for entry in self._monitor_entries()
            if bool(entry.get("controller_enabled", False))
        ]
        available_ids = [str(entry["id"]) for entry in managed]
        if self._selected_monitor not in available_ids:
            self._selected_monitor = available_ids[0] if available_ids else ""
        for entry in managed:
            screen_id = str(entry["id"])
            button = QPushButton(str(entry.get("label", entry["name"])))
            button.setObjectName("monitorTile")
            button.setCheckable(True)
            button.setChecked(screen_id == self._selected_monitor)
            button.clicked.connect(
                lambda checked=False, value=screen_id: self._select_monitor(value)
            )
            self.monitor_row.addWidget(button, 1)
        if not managed:
            empty = QLabel("No managed monitoring display. Enable one in Settings.")
            empty.setObjectName("controllerEmptyState")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.monitor_row.addWidget(empty)
        layout_name = self._controller_layout()
        target = next(
            (str(entry.get("label", entry["name"])) for entry in managed
             if str(entry["id"]) == self._selected_monitor),
            "No display selected",
        )
        self.target_value.setText(target)
        self.access_value.setText("ENABLED" if managed else "NOT CONFIGURED")
        self.access_value.setProperty("warning", not bool(managed))
        self.access_value.style().unpolish(self.access_value)
        self.access_value.style().polish(self.access_value)
        self.layout_value.setText(layout_name.upper())
        self.show_button.setEnabled(bool(self._selected_monitor and self._selected_page))

    def _select_monitor(self, screen_id: str) -> None:
        self._selected_monitor = screen_id
        self.refresh()

    def _select_page(self, page_name: str) -> None:
        self._selected_page = page_name
        for name, button in self.page_buttons.items():
            button.setChecked(name == page_name)

    def _apply(self) -> None:
        if self._show_on_monitor(self._selected_monitor, self._selected_page):
            self.access_value.setText(f"LIVE · {self._selected_page.upper()}")
        else:
            self.access_value.setText("DISPLAY UNAVAILABLE")
