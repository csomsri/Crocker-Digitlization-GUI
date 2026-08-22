from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from python.app.PageShell import DetailPage


class SettingsPage(DetailPage):
    DISPLAY_MODES = ("Windowed", "Borderless Window", "Full Screen")
    RESOLUTIONS = (
        "1280 x 820",
        "1366 x 768",
        "1440 x 900",
        "1600 x 900",
        "1920 x 1080",
    )

    def __init__(
        self,
        go_back: Callable[[], None],
        set_display_mode: Callable[[str], None],
        set_window_resolution: Callable[[str], None],
        current_display_mode: str = "Windowed",
        current_window_resolution: str = "1280 x 820",
        monitor_entries: list[dict[str, object]] | None = None,
        page_names: list[str] | None = None,
        apply_monitor_assignments: (
            Callable[[dict[str, str]], None] | None
        ) = None,
        controller_layout: str = "Auto",
        apply_controller_settings: Callable[[set[str], str], None] | None = None,
    ) -> None:
        super().__init__(
            "Settings",
            "App settings",
            "Back to Configuration",
            go_back,
        )

        _, workspace_layout = self.add_workspace()
        workspace_layout.setContentsMargins(10, 8, 10, 10)
        workspace_layout.setSpacing(0)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("settingsScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        scroll_content = QWidget()
        scroll_content.setObjectName("settingsScrollContent")
        panel_layout = QVBoxLayout(scroll_content)
        panel_layout.setContentsMargins(16, 12, 16, 16)
        panel_layout.setSpacing(12)
        panel_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        panel_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        scroll_area.setWidget(scroll_content)
        workspace_layout.addWidget(scroll_area, 1)
        self._set_display_mode = set_display_mode
        self._set_window_resolution = set_window_resolution
        self._apply_monitor_assignments = apply_monitor_assignments
        self._apply_controller_settings = apply_controller_settings
        self._page_names = page_names or []
        self._monitor_assignments: dict[str, str] = {}
        self._selected_monitor = ""
        self._controller_monitors: set[str] = set()
        self._primary_monitors: set[str] = set()
        self.page_buttons: list[QPushButton] = []

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

        resolution_heading = QLabel("DISPLAY RESOLUTION")
        resolution_heading.setObjectName("settingsHeading")
        panel_layout.addWidget(resolution_heading)

        resolution_description = QLabel(
            "Choose the size used by Windowed mode. Full Screen and "
            "Borderless Window fill the display."
        )
        resolution_description.setObjectName("settingsDescription")
        resolution_description.setWordWrap(True)
        panel_layout.addWidget(resolution_description)

        resolution_row = QHBoxLayout()
        resolution_label = QLabel("RESOLUTION")
        resolution_label.setObjectName("monitorAssignmentLabel")
        self.resolution_select = QComboBox()
        self.resolution_select.setObjectName("monitorPageSelect")
        for resolution in self.RESOLUTIONS:
            self.resolution_select.addItem(resolution, resolution)
        resolution_index = self.resolution_select.findData(current_window_resolution)
        self.resolution_select.setCurrentIndex(max(0, resolution_index))
        resolution_row.addWidget(resolution_label)
        resolution_row.addWidget(self.resolution_select, 1)
        panel_layout.addLayout(resolution_row)

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

        assignment_panel = QFrame()
        assignment_panel.setObjectName("monitorPagePicker")
        assignment_panel_layout = QVBoxLayout(assignment_panel)
        assignment_panel_layout.setContentsMargins(12, 10, 12, 12)
        assignment_panel_layout.setSpacing(8)

        assignment_row = QHBoxLayout()
        self.assignment_label = QLabel("PAGE ASSIGNMENT")
        self.assignment_label.setObjectName("monitorAssignmentLabel")
        self.page_search = QLineEdit()
        self.page_search.setObjectName("monitorPageSearch")
        self.page_search.setPlaceholderText("Search pages")
        self.page_search.textChanged.connect(self._refresh_page_picker)
        assignment_row.addWidget(self.assignment_label)
        assignment_row.addWidget(self.page_search, 1)
        assignment_panel_layout.addLayout(assignment_row)

        self.page_picker_grid_frame = QFrame()
        self.page_picker_grid_frame.setObjectName("monitorPageGrid")
        self.page_picker_grid = QGridLayout(self.page_picker_grid_frame)
        self.page_picker_grid.setContentsMargins(0, 0, 0, 0)
        self.page_picker_grid.setHorizontalSpacing(8)
        self.page_picker_grid.setVerticalSpacing(8)
        assignment_panel_layout.addWidget(self.page_picker_grid_frame)
        panel_layout.addWidget(assignment_panel)

        controller_heading = QLabel("DISPLAY CONTROLLER")
        controller_heading.setObjectName("settingsHeading")
        panel_layout.addWidget(controller_heading)
        controller_description = QLabel(
            "Select a display above, then allow the Monitoring Display Controller "
            "to change only its monitoring view."
        )
        controller_description.setObjectName("settingsDescription")
        controller_description.setWordWrap(True)
        panel_layout.addWidget(controller_description)
        self.controller_access = QCheckBox(
            "Allow Display Controller to manage the selected monitor"
        )
        self.controller_access.setObjectName("toggleRow")
        self.controller_access.toggled.connect(self._toggle_controller_access)
        panel_layout.addWidget(self.controller_access)
        controller_layout_row = QHBoxLayout()
        controller_layout_label = QLabel("CONTROLLER LAYOUT")
        controller_layout_label.setObjectName("monitorAssignmentLabel")
        self.controller_layout_select = QComboBox()
        self.controller_layout_select.setObjectName("monitorPageSelect")
        for value in ("Auto", "Compact", "Full"):
            self.controller_layout_select.addItem(value, value)
        self.controller_layout_select.setCurrentText(controller_layout)
        controller_layout_row.addWidget(controller_layout_label)
        controller_layout_row.addWidget(self.controller_layout_select, 1)
        panel_layout.addLayout(controller_layout_row)
        self.set_monitor_entries(monitor_entries or [])

        hint = QLabel(
            "Windowed keeps the title bar and borders. Full Screen and "
            "Borderless Window use the full display."
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
        selected_resolution = self.resolution_select.currentData() or self.RESOLUTIONS[0]
        if selected is not None:
            self._set_display_mode(selected.text())
        self._set_window_resolution(str(selected_resolution))
        if self._apply_monitor_assignments is not None:
            self._apply_monitor_assignments(dict(self._monitor_assignments))
        if self._apply_controller_settings is not None:
            self._apply_controller_settings(
                set(self._controller_monitors),
                str(self.controller_layout_select.currentData()),
            )

    def set_monitor_entries(self, entries: list[dict[str, object]]) -> None:
        while self.monitor_layout.count():
            item = self.monitor_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._monitor_assignments = {
            str(entry.get("id", entry["name"])): str(entry.get("assignment", ""))
            for entry in entries
        }
        self._controller_monitors = {
            str(entry.get("id", entry["name"]))
            for entry in entries if bool(entry.get("controller_enabled", False))
        }
        self._primary_monitors = {
            str(entry.get("id", entry["name"]))
            for entry in entries if bool(entry.get("occupied", False))
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
            screen_id = str(entry.get("id", entry["name"]))
            name = str(entry["name"])
            label = str(entry.get("label", name))
            occupied = bool(entry.get("occupied", False))
            suffix = "\n* PRIMARY" if occupied else ""
            tile = QPushButton(f"{number}\n{label}{suffix}")
            tile.setObjectName("monitorTile")
            tile.setCheckable(True)
            tile.setMinimumSize(210, 112)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setProperty("primary", occupied)
            tile.setProperty("screenId", screen_id)
            tile.setProperty("screenName", label)
            tile.clicked.connect(
                lambda checked=False, selected_id=screen_id: self._select_monitor(
                    selected_id
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
            self.page_search.hide()
            self.page_picker_grid_frame.hide()
            self.controller_access.setEnabled(False)
            return

        screen_ids = [str(entry.get("id", entry["name"])) for entry in entries]
        if self._selected_monitor not in screen_ids:
            self._selected_monitor = screen_ids[0]
        for button in self.monitor_group.buttons():
            if button.property("screenId") == self._selected_monitor:
                button.setChecked(True)
                break
        self.assignment_label.show()
        self.page_search.show()
        self.page_picker_grid_frame.show()
        self._select_monitor(self._selected_monitor)

    def _select_monitor(self, screen_id: str) -> None:
        self._selected_monitor = screen_id
        label = screen_id
        for button in self.monitor_group.buttons():
            if button.property("screenId") == screen_id:
                label = str(button.property("screenName"))
                break
        assignment = self._monitor_assignments.get(screen_id, "")
        suffix = assignment or "Unassigned"
        self.assignment_label.setText(f"PAGE FOR {label.upper()}  -  {suffix.upper()}")
        self.controller_access.blockSignals(True)
        self.controller_access.setEnabled(True)
        self.controller_access.setChecked(screen_id in self._controller_monitors)
        self.controller_access.setToolTip("")
        self.controller_access.blockSignals(False)
        self._refresh_page_picker()

    def _toggle_controller_access(self, enabled: bool) -> None:
        if not self._selected_monitor:
            return
        if enabled:
            self._controller_monitors.add(self._selected_monitor)
        else:
            self._controller_monitors.discard(self._selected_monitor)

    def _refresh_page_picker(self, *_ignored) -> None:
        while self.page_picker_grid.count():
            item = self.page_picker_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.page_buttons = []

        query = self.page_search.text().strip().lower()
        selected_page = self._monitor_assignments.get(self._selected_monitor, "")
        choices = [("Unassigned", ""), *[(page_name, page_name) for page_name in self._page_names]]
        visible_choices = [
            (label, page_name)
            for label, page_name in choices
            if not query or query in label.lower()
        ]
        if not visible_choices:
            empty = QLabel("No matching pages")
            empty.setObjectName("settingsDescription")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.page_picker_grid.addWidget(empty, 0, 0)
            return

        columns = 4
        for index, (label, page_name) in enumerate(visible_choices):
            button = QPushButton(label)
            button.setObjectName("monitorPageTile")
            button.setCheckable(True)
            button.setChecked(page_name == selected_page)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda checked=False, value=page_name: self._assign_page_to_selected_monitor(value)
            )
            self.page_buttons.append(button)
            self.page_picker_grid.addWidget(button, index // columns, index % columns)

    def _assign_page_to_selected_monitor(self, page_name: str) -> None:
        if not self._selected_monitor:
            return
        self._monitor_assignments[self._selected_monitor] = page_name
        self._select_monitor(self._selected_monitor)
