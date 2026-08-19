from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from python.app.PageShell import DetailPage
from python.app.widgets.MagneticFieldWidgets import (
    BubbleToggle,
    CHANNEL_NAMES,
    FIELD_PLOT_SAMPLE_RATE_HZ,
    MAX_GAUGE_VALUE,
    SimulatedActual,
    clamp,
    magnetic_field_plot_state,
    make_speedometer,
    make_time_domain_plot,
)
from python.app.widgets.MonitoringPlotState import (
    MONITOR_CONTROL_TABS,
    MONITOR_VARIABLES,
    monitoring_plot_state,
)

try:
    import CycloViz
except Exception:
    CycloViz = None


CONVERGENCE_TOLERANCE = 0.5
FIELD_FEEDBACK_REFRESH_FPS = FIELD_PLOT_SAMPLE_RATE_HZ
FIELD_FEEDBACK_REFRESH_MS = round(1000 / FIELD_FEEDBACK_REFRESH_FPS)


class FieldCtrlPage(DetailPage):
    def __init__(
        self,
        go_back: Callable[[], None],
        backend_mode: str,
        zmq_endpoint: str = "tcp://0.0.0.0:5555",
    ) -> None:
        super().__init__(
            "Field Ctrl",
            "Magnetic field control",
            "Back to Manual Controls",
            go_back,
        )

        self.backend_mode = backend_mode.lower()
        self.zmq_endpoint = zmq_endpoint
        self.plot_state = magnetic_field_plot_state()
        self.monitor_plot_state = monitoring_plot_state()
        self.selected_index = 0
        self.target_values = self.plot_state.target_values
        self.actual_models = [SimulatedActual() for _ in CHANNEL_NAMES]
        self.actual_values = self.plot_state.actual_values
        self.history = self.plot_state.history
        self.applied_targets = [0.0 for _ in CHANNEL_NAMES]
        self.applied_on = [False for _ in CHANNEL_NAMES]
        self.applied_enabled = [False for _ in CHANNEL_NAMES]
        self.convergence_started_at: list[float | None] = [None for _ in CHANNEL_NAMES]
        self.convergence_elapsed = [0.0 for _ in CHANNEL_NAMES]
        self.converged = [True for _ in CHANNEL_NAMES]
        self.value_labels: list[QLabel] = []
        self.actual_value_labels: list[QLabel] = []
        self.channel_cards: list[QFrame] = []
        self.on_buttons: list[BubbleToggle] = []
        self.enable_buttons: list[BubbleToggle] = []
        self.plot_buttons: list[BubbleToggle] = []
        self.monitor_plot_buttons: list[BubbleToggle] = []
        self.toggle_bulk_buttons: list[QPushButton] = []
        self.monitor_bulk_buttons: list[QPushButton] = []
        self.control_tab_buttons: list[QPushButton] = []
        self.toggle_lock_button: QPushButton | None = None
        self.toggles_locked = True
        self.digit_labels: list[QLabel] = []
        self.digit_steps = (1000.0, 100.0, 10.0, 1.0, 0.1, 0.01)
        self.selected_digit_index = 3
        self.target_slider: QSlider | None = None
        self.backend = None
        self.backend_available = False
        self.backend_status = f"{self.backend_mode.upper()} backend not connected"
        self.backend_connection = "Not Connected"
        self.backend_destination = "None"
        self.backend_packets = 0
        self.scaling_status = "identity scaling"
        self._status_tick = 0
        self.owns_backend = False
        self._telemetry_state_synced = False
        self._operator_toggle_edited = False

        self._start_backend()
        self._promote_instruction_header()

        workspace_frame, workspace = self.add_workspace()
        workspace_frame.setObjectName("fieldControlWorkspace")
        workspace.setContentsMargins(12, 12, 12, 12)

        self.control_stack = QStackedWidget()
        self.control_stack.setObjectName("fieldControlStack")

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_channel_matrix())
        splitter.addWidget(self._build_controller_panel())
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 5)
        self.control_stack.addWidget(splitter)

        for page_title, _tab_title in MONITOR_CONTROL_TABS[1:]:
            self.control_stack.addWidget(self._build_monitor_plot_panel(page_title))

        workspace.addWidget(self.control_stack, 1)

        self._refresh_toggle_lock()
        self._refresh_selection()
        self._refresh_target_display()
        self._install_shortcuts()

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick_feedback)
        self.timer.start(FIELD_FEEDBACK_REFRESH_MS)

    def _build_control_tabs(self) -> QWidget:
        tab_bar = QFrame()
        tab_bar.setObjectName("fieldControlTabs")
        layout = QHBoxLayout(tab_bar)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(0)

        self.control_tab_group = QButtonGroup(self)
        self.control_tab_group.setExclusive(True)
        for index, (_page_title, tab_title) in enumerate(MONITOR_CONTROL_TABS):
            button = QPushButton(tab_title)
            button.setObjectName("fieldControlTab")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda checked=False, tab_index=index: self._set_control_tab(tab_index))
            self.control_tab_group.addButton(button, index)
            self.control_tab_buttons.append(button)
            layout.addWidget(button)
        layout.addStretch(1)
        self.control_tab_buttons[0].setChecked(True)
        return tab_bar

    def _set_control_tab(self, index: int) -> None:
        if hasattr(self, "control_stack"):
            self.control_stack.setCurrentIndex(index)
        if 0 <= index < len(self.control_tab_buttons):
            self.control_tab_buttons[index].setChecked(True)

    def _build_monitor_plot_panel(self, page_title: str) -> QWidget:
        body = QWidget()
        body.setObjectName("fieldMonitorControl")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        heading = QLabel(page_title)
        heading.setObjectName("fieldMonitorTitle")
        layout.addWidget(heading)

        button_row = QHBoxLayout()
        for label, enabled in (("All Plot", True), ("Clear Plot", False)):
            button = QPushButton(label)
            button.setObjectName("fieldBulk")
            button.clicked.connect(
                lambda checked=False, title=page_title, state=enabled: self._set_all_monitor_plots(title, state)
            )
            button_row.addWidget(button)
            self.monitor_bulk_buttons.append(button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        channels = MONITOR_VARIABLES.get(page_title, [])
        for index, channel in enumerate(channels):
            row = index // 2
            column = index % 2
            card = QFrame()
            card.setObjectName("fieldRow")
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(10)

            name = QLabel(channel)
            name.setObjectName("fieldName")
            toggle = BubbleToggle(f"{channel} plotted", "#ffb52d")
            toggle.setChecked(self.monitor_plot_state.is_enabled(page_title, channel))
            toggle.toggled.connect(
                lambda checked=False, title=page_title, variable=channel:
                    self._set_monitor_plot_enabled(title, variable, checked)
            )

            card_layout.addWidget(name, 1)
            card_layout.addWidget(toggle)
            grid.addWidget(card, row, column)
            self.monitor_plot_buttons.append(toggle)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        return body

    def _install_shortcuts(self) -> None:
        for key, direction in (("Shift+Left", -1), ("Shift+Right", 1)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda amount=direction: self._select_relative_digit(amount))

        for key, direction in ((Qt.Key_Up, 1), (Qt.Key_Down, -1), ("Shift+Up", 1), ("Shift+Down", -1)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda amount=direction: self._nudge_selected_digit(amount))

        for key in (Qt.Key_Return, Qt.Key_Enter):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self._apply_selected_command)

    def _promote_instruction_header(self) -> None:
        for item_index in (0, 1):
            item = self.layout.itemAt(item_index)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.hide()

        nav_item = self.layout.itemAt(3)
        nav_layout = nav_item.layout() if nav_item is not None else None
        if nav_layout is None:
            return

        back_item = nav_layout.takeAt(0)
        back_button = back_item.widget() if back_item is not None else None
        while nav_layout.count():
            nav_layout.takeAt(0)
        if back_button is not None:
            nav_layout.addWidget(back_button)
        nav_layout.addWidget(self._build_control_tabs(), 1)
        nav_layout.addStretch(1)

    def _build_channel_matrix(self) -> QWidget:
        body = QWidget()
        body.setObjectName("fieldMatrix")
        body.setMinimumWidth(610)
        outer = QVBoxLayout(body)
        outer.setContentsMargins(0, 0, 8, 0)
        outer.setSpacing(8)

        grid_holder = QWidget()
        grid_holder.setObjectName("fieldMatrixGrid")
        layout = QGridLayout(grid_holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(3)
        layout.setRowMinimumHeight(0, 34)
        layout.setRowMinimumHeight(1, 24)

        bulk_controls = QHBoxLayout()
        for label, handler in (
            ("All On", lambda: self._set_all_toggles(self.on_buttons, True)),
            ("Clear On", lambda: self._set_all_toggles(self.on_buttons, False)),
            ("All En", lambda: self._set_all_toggles(self.enable_buttons, True)),
            ("Clear En", lambda: self._set_all_toggles(self.enable_buttons, False)),
            ("All Plot", lambda: self._set_all_toggles(self.plot_buttons, True)),
            ("Clear Plot", lambda: self._set_all_toggles(self.plot_buttons, False)),
            ("Apply All", self._apply_all_commands),
        ):
            button = QPushButton(label)
            button.setObjectName("fieldBulk")
            button.clicked.connect(handler)
            bulk_controls.addWidget(button)
            if label != "Apply All":
                self.toggle_bulk_buttons.append(button)
        layout.addLayout(bulk_controls, 0, 0, 1, 6)

        headers = ["Channel", "Actual", "Target", "Output", "En", "Plot"]
        for col, text in enumerate(headers):
            label = QLabel(text)
            label.setObjectName("fieldHeader")
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label, 1, col)
        layout.setColumnStretch(0, 3)
        for col in (1, 2):
            layout.setColumnStretch(col, 2)
        for col in range(3, 6):
            layout.setColumnStretch(col, 1)

        for row, channel in enumerate(CHANNEL_NAMES, start=2):
            card = QFrame()
            card.setObjectName("fieldRow")
            card.setMinimumHeight(40)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            card_layout = QGridLayout(card)
            card_layout.setContentsMargins(8, 6, 8, 6)
            card_layout.setHorizontalSpacing(6)
            card_layout.setColumnStretch(0, 1)

            name = QLabel(channel)
            name.setObjectName("fieldName")

            select = QPushButton("Select")
            select.setObjectName("fieldSelect")
            select.clicked.connect(lambda checked=False, idx=row - 2: self._select_channel(idx))

            card_layout.addWidget(name, 0, 0)
            card_layout.addWidget(select, 0, 1)

            actual_value = QLabel("0.00")
            actual_value.setObjectName("fieldActualValue")
            actual_value.setAlignment(Qt.AlignCenter)

            target_value = QLabel("0.00")
            target_value.setObjectName("fieldValue")
            target_value.setAlignment(Qt.AlignCenter)

            layout.addWidget(card, row, 0)
            layout.addWidget(actual_value, row, 1)
            layout.addWidget(target_value, row, 2)
            on_toggle = BubbleToggle(f"{channel} output on", "#49e6ff")
            enable_toggle = BubbleToggle(f"{channel} enabled", "#7cffb2")
            plot_toggle = BubbleToggle(f"{channel} plotted", "#ffb52d")
            on_toggle.setChecked(True)
            enable_toggle.setChecked(False)
            plot_toggle.setChecked(self.plot_state.plot_enabled[row - 2])
            on_toggle.toggled.connect(lambda checked=False: self._mark_operator_toggle_edit())
            enable_toggle.toggled.connect(lambda checked=False: self._mark_operator_toggle_edit())
            plot_toggle.toggled.connect(
                lambda checked=False, idx=row - 2: self._set_plot_enabled(idx, checked)
            )
            layout.addWidget(on_toggle, row, 3, Qt.AlignVCenter)
            layout.addWidget(enable_toggle, row, 4, Qt.AlignVCenter)
            layout.addWidget(plot_toggle, row, 5, Qt.AlignVCenter)

            self.value_labels.append(target_value)
            self.actual_value_labels.append(actual_value)
            self.channel_cards.append(card)
            self.on_buttons.append(on_toggle)
            self.enable_buttons.append(enable_toggle)
            self.plot_buttons.append(plot_toggle)

        for row in range(2, 2 + len(CHANNEL_NAMES)):
            layout.setRowMinimumHeight(row, 38)
            layout.setRowStretch(row, 1)
        outer.addWidget(grid_holder, 1)
        outer.addWidget(self._build_backend_status_panel())
        return body

    def _build_backend_status_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("fieldBackendStatus")
        panel.setFixedHeight(58)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        self.connection_dot = QLabel()
        self.connection_dot.setObjectName("fieldStatusDot")
        self.connection_dot.setProperty("connected", False)
        self.connection_dot.setFixedSize(18, 18)

        self.connection_label = QLabel("Connection\nNot Connected")
        self.connection_label.setObjectName("fieldStatusText")
        self.destination_label = QLabel("Destination\nNone")
        self.destination_label.setObjectName("fieldStatusText")
        self.packets_label = QLabel("Packets\n0")
        self.packets_label.setObjectName("fieldStatusText")
        self.toggle_lock_button = QPushButton()
        self.toggle_lock_button.setObjectName("fieldLockButton")
        self.toggle_lock_button.setCheckable(True)
        self.toggle_lock_button.setCursor(Qt.PointingHandCursor)
        self.toggle_lock_button.clicked.connect(self._set_toggle_lock_from_button)

        layout.addWidget(self.connection_dot)
        layout.addWidget(self.connection_label, 1)
        layout.addWidget(self.destination_label, 2)
        layout.addWidget(self.packets_label, 1)
        layout.addWidget(self.toggle_lock_button)
        self._refresh_toggle_lock()
        self._refresh_backend_status_panel()
        return panel

    def _build_controller_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("fieldController")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(8)

        self.speedometer = make_speedometer(panel)
        self.speedometer.setMinimumHeight(350)
        layout.addWidget(self.speedometer, 1)

        self.time_plot = make_time_domain_plot(panel)
        layout.addWidget(self.time_plot)

        editor = QFrame()
        editor.setObjectName("fieldEditor")
        editor.setMinimumHeight(340)
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(14, 14, 14, 14)
        editor_layout.setSpacing(12)

        self.target_input = QDoubleSpinBox()
        self.target_input.setObjectName("fieldTargetInput")
        self.target_input.setRange(0.0, MAX_GAUGE_VALUE)
        self.target_input.setDecimals(2)
        self.target_input.setSingleStep(0.1)
        self.target_input.setSuffix(" A")
        self.target_input.valueChanged.connect(self._set_selected_target)

        self.target_slider = QSlider(Qt.Horizontal)
        self.target_slider.setObjectName("fieldPowerSlider")
        self.target_slider.setRange(0, int(MAX_GAUGE_VALUE * 10))
        self.target_slider.valueChanged.connect(lambda value: self._set_selected_target(value / 10.0))

        target_row = QHBoxLayout()
        target_title = QLabel("Target Current")
        target_title.setObjectName("fieldEditorTitle")
        target_row.addWidget(target_title)
        target_row.addWidget(self.target_input)
        editor_layout.addLayout(target_row)
        editor_layout.addWidget(self.target_slider)
        editor_layout.addWidget(self._build_digit_adjuster())

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 18, 0, 0)
        actions.setSpacing(10)
        for label in ("Apply", "Hold", "Zero"):
            button = QPushButton(label)
            button.setObjectName("fieldAction")
            if label == "Apply":
                button.clicked.connect(self._apply_selected_command)
            if label == "Hold":
                button.clicked.connect(self._hold_selected_actual)
            if label == "Zero":
                button.clicked.connect(lambda checked=False: self._set_selected_target(0.0))
            actions.addWidget(button)
        editor_layout.addLayout(actions)

        self.backend_label = QLabel(self.backend_status)
        self.backend_label.setObjectName("workspaceBody")
        self.backend_label.hide()
        layout.addWidget(editor)

        return panel

    def _build_digit_adjuster(self) -> QWidget:
        adjuster = QFrame()
        adjuster.setObjectName("fieldDigitAdjuster")
        adjuster.setFixedHeight(136)
        adjuster.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QGridLayout(adjuster)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(6)
        layout.setRowMinimumHeight(0, 26)
        layout.setRowMinimumHeight(1, 36)
        layout.setRowMinimumHeight(2, 26)

        columns = (0, 1, 2, 3, 5, 6)
        for step, column in zip(self.digit_steps, columns):
            up = QPushButton("▲")
            up.setObjectName("fieldDigitArrow")
            up.setToolTip(f"Increase by {step:g} A")
            up.clicked.connect(lambda checked=False, amount=step: self._nudge_selected(amount))

            digit = QLabel("0")
            digit.setObjectName("fieldDigit")
            digit.setAlignment(Qt.AlignCenter)

            down = QPushButton("▼")
            down.setObjectName("fieldDigitArrow")
            down.setToolTip(f"Decrease by {step:g} A")
            down.clicked.connect(lambda checked=False, amount=step: self._nudge_selected(-amount))

            layout.addWidget(up, 0, column)
            layout.addWidget(digit, 1, column)
            layout.addWidget(down, 2, column)
            layout.setColumnStretch(column, 1)
            self.digit_labels.append(digit)

        decimal = QLabel(".")
        decimal.setObjectName("fieldDigitDecimal")
        decimal.setAlignment(Qt.AlignCenter)
        layout.addWidget(decimal, 1, 4)
        layout.setColumnMinimumWidth(4, 8)
        self._refresh_digit_selection()
        return adjuster

    def _select_channel(self, index: int) -> None:
        self.selected_index = index
        self._refresh_selection()
        self._refresh_target_display()
        self._refresh_plot()

    def _refresh_selection(self) -> None:
        for index, card in enumerate(self.channel_cards):
            card.setProperty("selected", index == self.selected_index)
            card.style().unpolish(card)
            card.style().polish(card)

    def _set_selected_target(self, value: float) -> None:
        next_value = clamp(value)
        if abs(next_value - self.target_values[self.selected_index]) >= 0.01:
            self.target_values[self.selected_index] = next_value
            self._begin_convergence_timer(self.selected_index)
        else:
            self.target_values[self.selected_index] = next_value
        self._refresh_target_display()

    def _nudge_selected(self, amount: float) -> None:
        self._set_selected_target(self.target_values[self.selected_index] + amount)

    def _select_relative_digit(self, direction: int) -> None:
        self.selected_digit_index = max(0, min(len(self.digit_labels) - 1, self.selected_digit_index + direction))
        self._refresh_digit_selection()

    def _nudge_selected_digit(self, direction: int) -> None:
        if not self.digit_steps:
            return
        amount = self.digit_steps[self.selected_digit_index] * direction
        self._nudge_selected(amount)

    def _refresh_digit_display(self, value: float) -> None:
        digits = f"{clamp(value):07.2f}".replace(".", "")
        for label, digit in zip(self.digit_labels, digits):
            label.setText(digit)
        self._refresh_digit_selection()

    def _refresh_digit_selection(self) -> None:
        for index, label in enumerate(self.digit_labels):
            label.setProperty("selected", index == self.selected_digit_index)
            label.style().unpolish(label)
            label.style().polish(label)

    def _refresh_target_display(self) -> None:
        target = self.target_values[self.selected_index]
        self.target_input.blockSignals(True)
        self.target_input.setValue(target)
        self.target_input.blockSignals(False)
        if self.target_slider is not None:
            self.target_slider.blockSignals(True)
            self.target_slider.setValue(int(round(target * 10.0)))
            self.target_slider.blockSignals(False)
        for index, value in enumerate(self.target_values):
            self.value_labels[index].setText(f"{value:.2f}")

        self._refresh_digit_display(target)
        self._update_speedometer()

    def _refresh_actual_display(self) -> None:
        for index, value in enumerate(self.actual_values):
            if index < len(self.actual_value_labels):
                self.actual_value_labels[index].setText(f"{value:.2f}")

    def _tick_feedback(self) -> None:
        if self.backend_available and self.backend is not None:
            try:
                snapshot = self.backend.LatestSnapshot()
                channels = snapshot["channels"]
                health = self.backend.Health()
                has_real_telemetry = (
                    int(health["received_packets"]) > 0
                    or int(snapshot.get("sequence_number", 0)) > 0
                    or str(snapshot.get("connection", "")).lower() == "connected"
                )
                for index in range(min(len(CHANNEL_NAMES), len(channels))):
                    channel = channels[index]
                    if has_real_telemetry:
                        self.actual_values[index] = float(channel["actual"])
                        if not self._operator_toggle_edited and not self._telemetry_state_synced:
                            self.applied_targets[index] = self.actual_values[index]
                            self.applied_on[index] = bool(channel["on"])
                            self.applied_enabled[index] = bool(channel["enabled"])
                    if has_real_telemetry and not self._operator_toggle_edited and not self._telemetry_state_synced:
                        self._set_toggle_from_telemetry(self.on_buttons[index], bool(channel["on"]))
                        self._set_toggle_from_telemetry(self.enable_buttons[index], bool(channel["enabled"]))
                if has_real_telemetry and channels and not self._operator_toggle_edited:
                    self._telemetry_state_synced = True
                self.backend_connection = str(health["connection"])
                self.backend_destination = str(health["endpoint"])
                self.backend_packets = int(health["received_packets"])
                self.backend_status = (
                    f"{self.backend_mode.upper()} {health['connection']} | "
                    f"packets {health['received_packets']} | "
                    f"{health['endpoint']}"
                )
                self._status_tick += 1
                if self._status_tick % 4 == 0 and self.backend_label.text() != self.backend_status:
                    self.backend_label.setText(self.backend_status)
                    self._refresh_backend_status_panel()
            except Exception as exc:
                self.backend_available = False
                self._telemetry_state_synced = False
                self.backend_connection = "Not Connected"
                self.backend_destination = self.backend_mode.upper()
                self.backend_status = f"{self.backend_mode.upper()} fallback: {exc}"
                self.backend_label.setText(self.backend_status)
                self._refresh_backend_status_panel()
        else:
            target = self.target_values[self.selected_index]
            self.actual_values[self.selected_index] = self.actual_models[self.selected_index].step(target)
        for index in range(len(CHANNEL_NAMES)):
            target = self.target_values[index]
            actual = self.actual_values[index]
            self._append_plot_sample(index, target, actual, target - actual)
        self._refresh_actual_display()
        self._update_speedometer()

    def _update_speedometer(self) -> None:
        target = self.target_values[self.selected_index]
        actual = self.actual_values[self.selected_index]
        error = target - actual
        converged = abs(error) <= CONVERGENCE_TOLERANCE
        self._update_convergence_state(self.selected_index, converged)
        seconds = self._convergence_seconds(self.selected_index)

        self.speedometer.set_values(target, actual, CHANNEL_NAMES[self.selected_index])
        self.speedometer.set_status(converged, error, CONVERGENCE_TOLERANCE, seconds, self.convergence_started_at[self.selected_index] is not None)
        self._refresh_plot()

    def _start_backend(self) -> None:
        if CycloViz is None or not hasattr(CycloViz, "ControlService"):
            return
        try:
            self.backend = CycloViz.ControlService()
            self.owns_backend = True
            if self.backend_mode == "simulation":
                self.backend.StartSimulator(float(FIELD_PLOT_SAMPLE_RATE_HZ))
                self.backend_connection = "Connected"
                self.backend_destination = "Simulation"
                self.backend_status = "SIMULATION Connected | simulator://local"
            elif self.backend_mode == "zmq":
                scaling = self._load_trim_coil_scaling()
                self.backend.StartServer(self.zmq_endpoint, scaling)
                self.backend_connection = "Listening"
                self.backend_destination = self.zmq_endpoint
                self.backend_status = f"ZMQ Listening | {self.zmq_endpoint} | {self.scaling_status}"
            else:
                raise ValueError(f"Unknown backend mode: {self.backend_mode}")
            self.backend_available = True
            self._refresh_backend_status_panel()
        except Exception as exc:
            self.backend = None
            self.owns_backend = False
            self.backend_available = False
            self.backend_connection = "Not Connected"
            self.backend_destination = self.backend_mode.upper()
            self.backend_status = f"{self.backend_mode.upper()} unavailable: {exc}"
            self._refresh_backend_status_panel()

    def _load_trim_coil_scaling(self) -> dict[str, object]:
        scaling = self._identity_trim_coil_scaling()
        config_path = self._find_scaling_config_path()
        if config_path is None:
            self.scaling_status = "identity scaling"
            return scaling

        try:
            with config_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            loaded = self._scaling_from_json(data)
        except Exception as exc:
            self.scaling_status = f"scaling unavailable: {exc}"
            return scaling

        enabled_count = self._enabled_scaling_count(loaded)
        self.scaling_status = f"scaling {enabled_count}/{len(CHANNEL_NAMES)} channels from {config_path.name}"
        return loaded

    def _find_scaling_config_path(self) -> Path | None:
        app_root = Path(__file__).resolve().parents[3]
        candidates = (
            app_root / "config" / "trim_coil_scaling.json",
            app_root / "calibration.json",
            Path.cwd() / "calibration.json",
        )
        for path in candidates:
            if path.exists():
                return path
        return None

    def _identity_trim_coil_scaling(self) -> dict[str, object]:
        count = len(CHANNEL_NAMES)
        return {
            "raw_to_eng_gain": [1.0] * count,
            "raw_to_eng_offset": [0.0] * count,
            "eng_to_raw_gain": [1.0] * count,
            "eng_to_raw_offset": [0.0] * count,
            "enabled": [False] * count,
        }

    def _scaling_from_json(self, data: object) -> dict[str, object]:
        scaling = self._identity_trim_coil_scaling()
        if not isinstance(data, dict):
            raise ValueError("scaling file must contain a JSON object")

        array_keys = {"raw_to_eng_gain", "raw_to_eng_offset", "eng_to_raw_gain", "eng_to_raw_offset", "enabled"}
        if array_keys.intersection(data):
            for key in array_keys:
                if key in data:
                    values = data[key]
                    if not isinstance(values, list) or len(values) != len(CHANNEL_NAMES):
                        raise ValueError(f"{key} must contain {len(CHANNEL_NAMES)} entries")
                    scaling[key] = [bool(value) for value in values] if key == "enabled" else [float(value) for value in values]
            return scaling

        channel_keys = [f"ch{index}" for index in range(1, 13)] + ["main_magnet", "centering_beam"]
        if any(isinstance(data.get(key), dict) for key in channel_keys):
            return data
        return scaling

    def _enabled_scaling_count(self, scaling: dict[str, object]) -> int:
        enabled = scaling.get("enabled")
        if isinstance(enabled, list):
            return sum(1 for value in enabled if bool(value))

        channel_keys = [f"ch{index}" for index in range(1, 13)] + ["main_magnet", "centering_beam"]
        count = 0
        for index, key in enumerate(channel_keys):
            entry = scaling.get(key)
            if isinstance(entry, dict):
                count += 1 if bool(entry.get("enabled", True)) else 0
        return count

    def _apply_channel_scaling_entry(
        self,
        scaling: dict[str, list[float] | list[bool]],
        index: int,
        entry: dict[str, object],
    ) -> None:
        raw_to_eng = entry.get("raw_to_eng")
        eng_to_raw = entry.get("eng_to_raw")
        enabled = bool(entry.get("enabled", True)) and isinstance(raw_to_eng, dict) and isinstance(eng_to_raw, dict)
        scaling["enabled"][index] = enabled
        if not enabled:
            return

        scaling["raw_to_eng_gain"][index] = float(raw_to_eng.get("gain", 1.0))
        scaling["raw_to_eng_offset"][index] = float(raw_to_eng.get("offset", 0.0))
        scaling["eng_to_raw_gain"][index] = float(eng_to_raw.get("gain", 1.0))
        scaling["eng_to_raw_offset"][index] = float(eng_to_raw.get("offset", 0.0))

    def apply_scaling(self, scaling: dict[str, object] | None = None) -> bool:
        if scaling is None:
            scaling = self._load_trim_coil_scaling()
        if not self.backend_available or self.backend is None or not hasattr(self.backend, "SetScaling"):
            self.backend_status = "Scaling saved; no live Field Ctrl backend to update"
            if hasattr(self, "backend_label"):
                self.backend_label.setText(self.backend_status)
            self._refresh_backend_status_panel()
            return False

        self.backend.SetScaling(scaling)
        enabled_count = self._enabled_scaling_count(scaling)
        self.scaling_status = f"scaling {enabled_count}/{len(CHANNEL_NAMES)} channels active"
        self.backend_status = f"{self.backend_mode.upper()} {self.scaling_status}"
        if hasattr(self, "backend_label"):
            self.backend_label.setText(self.backend_status)
        self._refresh_backend_status_panel()
        return True

    def transport_snapshot(self) -> dict | None:
        if not self.backend_available or self.backend is None:
            return None
        try:
            return self.backend.LatestSnapshot()
        except Exception:
            return None

    def _apply_selected_command(self) -> bool:
        applied = self._apply_channel_command(self.selected_index)
        if applied:
            self._begin_convergence_timer(self.selected_index)
        return applied

    def _apply_channel_command(self, index: int) -> bool:
        target = self.target_values[index]
        on = self.on_buttons[index].isChecked()
        enabled = self.enable_buttons[index].isChecked()
        if self.backend_available and self.backend is not None:
            try:
                self._stage_selected_channel_command(index, target, on, enabled)
                applied = bool(self.backend.ApplyCommand())
                mode = self.backend_mode.upper()
                self.backend_status = f"{mode} command applied" if applied else f"{mode} command rejected"
                self.backend_label.setText(self.backend_status)
                if applied:
                    self._remember_applied_channel(index, target, on, enabled)
                return applied
            except Exception as exc:
                self.backend_status = f"Simulator command failed: {exc}"
                self.backend_label.setText(self.backend_status)
                return False

        self.actual_models[index].value = self.actual_values[index]
        self._remember_applied_channel(index, target, on, enabled)
        self.backend_label.setText("Local UI fallback command applied")
        return True

    def _stage_selected_channel_command(self, selected_index: int, target: float, on: bool, enabled: bool) -> None:
        for index in range(len(CHANNEL_NAMES)):
            if index == selected_index:
                self.backend.SetChannelCommand(index, target, on, enabled)
            else:
                self.backend.SetChannelCommand(
                    index,
                    self.applied_targets[index],
                    self.applied_on[index],
                    self.applied_enabled[index],
                )

    def _remember_applied_channel(self, index: int, target: float, on: bool, enabled: bool) -> None:
        self.applied_targets[index] = target
        self.applied_on[index] = on
        self.applied_enabled[index] = enabled

    def _apply_all_commands(self) -> None:
        applied = self._apply_all_channel_commands()
        if applied:
            for index in range(len(CHANNEL_NAMES)):
                self._remember_applied_channel(
                    index,
                    self.target_values[index],
                    self.on_buttons[index].isChecked(),
                    self.enable_buttons[index].isChecked(),
                )
                self._begin_convergence_timer(index)
        ok_count = len(CHANNEL_NAMES) if applied else 0
        self.backend_label.setText(f"{ok_count}/{len(CHANNEL_NAMES)} channel commands applied")

    def _apply_all_channel_commands(self) -> bool:
        if self.backend_available and self.backend is not None:
            try:
                for index in range(len(CHANNEL_NAMES)):
                    self.backend.SetChannelCommand(
                        index,
                        self.target_values[index],
                        self.on_buttons[index].isChecked(),
                        self.enable_buttons[index].isChecked(),
                    )
                return bool(self.backend.ApplyCommand())
            except Exception as exc:
                self.backend_status = f"Simulator command failed: {exc}"
                self.backend_label.setText(self.backend_status)
                return False
        return True

    def _set_all_toggles(self, buttons: list[BubbleToggle], checked: bool) -> None:
        if self.toggles_locked:
            return
        self._operator_toggle_edited = True
        for button in buttons:
            button.setChecked(checked)

    def _set_toggle_lock_from_button(self, unlocked: bool) -> None:
        self.toggles_locked = not unlocked
        self._refresh_toggle_lock()

    def _refresh_toggle_lock(self) -> None:
        unlocked = not self.toggles_locked
        for button in [
            *self.on_buttons,
            *self.enable_buttons,
            *self.plot_buttons,
            *self.monitor_plot_buttons,
            *self.toggle_bulk_buttons,
            *self.monitor_bulk_buttons,
        ]:
            button.setEnabled(unlocked)
        if self.toggle_lock_button is not None:
            self.toggle_lock_button.blockSignals(True)
            self.toggle_lock_button.setChecked(unlocked)
            self.toggle_lock_button.setText("Lock Toggles" if unlocked else "Unlock Toggles")
            self.toggle_lock_button.setToolTip(
                "Lock the ON, Enable, and Plot controls"
                if unlocked else
                "Unlock the ON, Enable, and Plot controls"
            )
            self.toggle_lock_button.blockSignals(False)

    def _set_plot_enabled(self, index: int, checked: bool) -> None:
        self.plot_state.set_plot_enabled(index, checked)
        self._refresh_plot()

    def _set_monitor_plot_enabled(self, page_title: str, channel: str, checked: bool) -> None:
        self.monitor_plot_state.set_enabled(page_title, channel, checked)

    def _set_all_monitor_plots(self, page_title: str, checked: bool) -> None:
        if self.toggles_locked:
            return
        self.monitor_plot_state.set_all_enabled(page_title, checked)
        for button in self.monitor_plot_buttons:
            if button.toolTip().endswith(" plotted"):
                channel = button.toolTip()[: -len(" plotted")]
                if channel in MONITOR_VARIABLES.get(page_title, []):
                    button.setChecked(checked)

    def _hold_selected_actual(self) -> None:
        self._set_selected_target(self.actual_values[self.selected_index])

    def _mark_operator_toggle_edit(self) -> None:
        if self._building_telemetry_state():
            return
        self._operator_toggle_edited = True

    def _building_telemetry_state(self) -> bool:
        return getattr(self, "_syncing_telemetry_state", False)

    def _set_toggle_from_telemetry(self, button: BubbleToggle, checked: bool) -> None:
        self._syncing_telemetry_state = True
        button.blockSignals(True)
        button.setChecked(checked)
        button.blockSignals(False)
        self._syncing_telemetry_state = False

    def _begin_convergence_timer(self, index: int) -> None:
        self.convergence_started_at[index] = time.perf_counter()
        self.convergence_elapsed[index] = 0.0
        self.converged[index] = False

    def _update_convergence_state(self, index: int, converged: bool) -> None:
        self.converged[index] = converged
        started_at = self.convergence_started_at[index]
        if started_at is None:
            return
        elapsed = time.perf_counter() - started_at
        self.convergence_elapsed[index] = elapsed
        if converged:
            self.convergence_started_at[index] = None

    def _convergence_seconds(self, index: int) -> float:
        started_at = self.convergence_started_at[index]
        if started_at is not None:
            return time.perf_counter() - started_at
        return self.convergence_elapsed[index]

    def _append_plot_sample(self, index: int, target: float, actual: float, error: float) -> None:
        self.plot_state.append_sample(index, time.perf_counter(), actual, target, error)

    def _refresh_plot(self) -> None:
        if not self.plot_buttons[self.selected_index].isChecked():
            self.time_plot.set_samples([])
            return
        self.time_plot.set_samples(list(self.history[self.selected_index]))

    def _refresh_backend_status_panel(self) -> None:
        connected = self.backend_available and self.backend_connection.lower() in {"connected", "listening"}
        if hasattr(self, "connection_dot"):
            self.connection_dot.setProperty("connected", connected)
            self.connection_dot.style().unpolish(self.connection_dot)
            self.connection_dot.style().polish(self.connection_dot)
        if hasattr(self, "connection_label"):
            self.connection_label.setText(f"Connection\n{self.backend_connection}")
            self.destination_label.setText(f"Destination\n{self.backend_destination}")
            self.packets_label.setText(f"Packets\n{self.backend_packets}")

    def closeEvent(self, event) -> None:
        self.stop_backend()
        super().closeEvent(event)

    def stop_backend(self) -> None:
        if self.owns_backend and self.backend is not None:
            try:
                self.backend.Stop()
            except Exception:
                pass
        self.backend_available = False
