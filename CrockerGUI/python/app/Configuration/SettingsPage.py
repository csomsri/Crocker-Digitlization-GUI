from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from python.app.PageShell import DetailPage


class SettingsPage(DetailPage):
    DISPLAY_MODES = ("Windowed", "Borderless Window", "Full Screen")

    def __init__(
        self,
        go_back: Callable[[], None],
        set_display_mode: Callable[[str], None],
        current_display_mode: str = "Windowed",
        monitor_entries: list[dict[str, object]] | None = None,
        page_names: list[str] | None = None,
        apply_monitor_assignments: (
            Callable[[dict[str, str]], None] | None
        ) = None,
    ) -> None:
        super().__init__(
            "Settings",
            "App settings",
            "Back to Configuration",
            go_back,
        )

        _, panel_layout = self.add_workspace()
        panel_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._set_display_mode = set_display_mode
        self._apply_monitor_assignments = apply_monitor_assignments
        self._page_names = page_names or []
        self._monitor_assignments: dict[str, str] = {}
        self._selected_monitor = ""

        heading = QLabel("DISPLAY MODE")
        heading.setObjectName("settingsHeading")
        panel_layout.addWidget(heading)

        description = QLabel(
            "Choose how the control interface uses your display. "
            "Changes apply immediately."
        )
        description.setObjectName("settingsDescription")
        description.setWordWrap(True)
        panel_layout.addWidget(description)

        mode_panel = QFrame()
        mode_panel.setObjectName("displayModePanel")
        mode_layout = QHBoxLayout(mode_panel)
        mode_layout.setContentsMargins(12, 12, 12, 12)
        mode_layout.setSpacing(10)

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons: dict[str, QPushButton] = {}
        for mode in self.DISPLAY_MODES:
            button = QPushButton(mode)
            button.setObjectName("displayModeButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(mode == current_display_mode)
            self.mode_group.addButton(button)
            self.mode_buttons[mode] = button
            mode_layout.addWidget(button, 1)

        panel_layout.addWidget(mode_panel)

        monitor_heading = QLabel("MULTI-MONITOR PAGES")
        monitor_heading.setObjectName("settingsHeading")
        panel_layout.addWidget(monitor_heading)

        self.monitor_description = QLabel(
            "Select a display rectangle, then choose the page it should show."
        )
        self.monitor_description.setObjectName("settingsDescription")
        self.monitor_description.setWordWrap(True)
        panel_layout.addWidget(self.monitor_description)

        self.monitor_panel = QFrame()
        self.monitor_panel.setObjectName("monitorMapPanel")
        self.monitor_layout = QVBoxLayout(self.monitor_panel)
        self.monitor_layout.setContentsMargins(16, 12, 16, 16)
        self.monitor_layout.setSpacing(10)
        panel_layout.addWidget(self.monitor_panel)

        assignment_row = QHBoxLayout()
        self.assignment_label = QLabel("PAGE ASSIGNMENT")
        self.assignment_label.setObjectName("monitorAssignmentLabel")
        self.monitor_page_select = QComboBox()
        self.monitor_page_select.setObjectName("monitorPageSelect")
        self.monitor_page_select.currentIndexChanged.connect(
            self._page_assignment_changed
        )
        assignment_row.addWidget(self.assignment_label)
        assignment_row.addWidget(self.monitor_page_select, 1)
        panel_layout.addLayout(assignment_row)
        self.set_monitor_entries(monitor_entries or [])

        hint = QLabel(
            "Windowed keeps the title bar and borders. Borderless Window "
            "fills the desktop "
            "without borders. Full Screen takes exclusive screen space."
        )
        hint.setObjectName("settingsDescription")
        hint.setWordWrap(True)
        panel_layout.addWidget(hint)
        panel_layout.addStretch(1)

        apply_button = QPushButton("APPLY SETTINGS")
        apply_button.setObjectName("applySettingsButton")
        apply_button.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_button.clicked.connect(self._apply_settings)
        panel_layout.addWidget(apply_button)

    def _apply_settings(self) -> None:
        selected = self.mode_group.checkedButton()
        if selected is not None:
            self._set_display_mode(selected.text())
        if self._apply_monitor_assignments is not None:
            self._apply_monitor_assignments(dict(self._monitor_assignments))

    def set_monitor_entries(self, entries: list[dict[str, object]]) -> None:
        while self.monitor_layout.count():
            item = self.monitor_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._monitor_assignments = {
            str(entry["name"]): str(entry.get("assignment", ""))
            for entry in entries
        }

        count_label = QLabel(f"DISPLAYS ({len(entries)})")
        count_label.setObjectName("monitorMapHeading")
        self.monitor_layout.addWidget(count_label)

        canvas = QFrame()
        canvas.setObjectName("monitorCanvas")
        canvas.setMinimumHeight(180)
        canvas_layout = QGridLayout(canvas)
        canvas_layout.setContentsMargins(80, 28, 80, 28)
        canvas_layout.setHorizontalSpacing(18)
        canvas_layout.setVerticalSpacing(14)

        self.monitor_group = QButtonGroup(self)
        self.monitor_group.setExclusive(True)

        for number, entry in enumerate(entries, start=1):
            name = str(entry["name"])
            occupied = bool(entry.get("occupied", False))
            suffix = "\n* PRIMARY" if occupied else ""
            tile = QPushButton(f"{number}\n{name}{suffix}")
            tile.setObjectName("monitorTile")
            tile.setCheckable(True)
            tile.setMinimumSize(210, 112)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setProperty("primary", occupied)
            tile.setProperty("screenName", name)
            tile.clicked.connect(
                lambda checked=False, screen_name=name: self._select_monitor(
                    screen_name
                )
            )
            self.monitor_group.addButton(tile)
            canvas_layout.addWidget(tile, (number - 1) // 2, (number - 1) % 2)

        self.monitor_layout.addWidget(canvas)

        if not entries:
            empty = QLabel("No displays detected")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.monitor_layout.addWidget(empty)
            self.assignment_label.hide()
            self.monitor_page_select.hide()
            return

        names = [str(entry["name"]) for entry in entries]
        if self._selected_monitor not in names:
            self._selected_monitor = names[0]
        for button in self.monitor_group.buttons():
            if button.property("screenName") == self._selected_monitor:
                button.setChecked(True)
                break
        self.assignment_label.show()
        self.monitor_page_select.show()
        self._select_monitor(self._selected_monitor)

    def _select_monitor(self, name: str) -> None:
        self._selected_monitor = name
        self.assignment_label.setText(f"PAGE FOR {name.upper()}")
        self.monitor_page_select.blockSignals(True)
        self.monitor_page_select.clear()
        self.monitor_page_select.addItem("Unassigned", "")
        for page_name in self._page_names:
            self.monitor_page_select.addItem(page_name, page_name)
        assignment = self._monitor_assignments.get(name, "")
        index = self.monitor_page_select.findData(assignment)
        self.monitor_page_select.setCurrentIndex(max(0, index))
        self.monitor_page_select.blockSignals(False)

    def _page_assignment_changed(self) -> None:
        if self._selected_monitor:
            selected_page = self.monitor_page_select.currentData() or ""
            self._monitor_assignments[self._selected_monitor] = selected_page
