from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from python.app.PageShell import DetailPage
from python.app.widgets.MagneticFieldWidgets import (
    BubbleToggle,
    CHANNEL_NAMES,
    MAX_GAUGE_VALUE,
    SimulatedActual,
    TimeDomainPlot,
    clamp,
    make_speedometer,
)

try:
    import CycloViz
except Exception:
    CycloViz = None


CONVERGENCE_TOLERANCE = 0.5
PLOT_SAMPLE_LIMIT = 240


class FieldCtrlPage(DetailPage):
    def __init__(
        self,
        go_back: Callable[[], None],
        backend_mode: str,
        zmq_endpoint: str = "tcp://0.0.0.0:5555",
        open_sequencer: Callable[[], None] | None = None,
        control_backend=None,
    ) -> None:
        super().__init__(
            "Field Ctrl",
            "Magnetic field control",
            "Back to Manual Controls",
            go_back,
        )

        self.backend_mode = backend_mode.lower()
        self.zmq_endpoint = zmq_endpoint
        self.open_sequencer = open_sequencer
        self.selected_index = 0
        self.target_values = [0.0 for _ in CHANNEL_NAMES]
        self.actual_models = [SimulatedActual() for _ in CHANNEL_NAMES]
        self.actual_values = [0.0 for _ in CHANNEL_NAMES]
        self.history = [deque(maxlen=PLOT_SAMPLE_LIMIT) for _ in CHANNEL_NAMES]
        self.convergence_started_at: list[float | None] = [None for _ in CHANNEL_NAMES]
        self.convergence_elapsed = [0.0 for _ in CHANNEL_NAMES]
        self.converged = [True for _ in CHANNEL_NAMES]
        self.value_labels: list[QLabel] = []
        self.channel_cards: list[QFrame] = []
        self.on_buttons: list[BubbleToggle] = []
        self.enable_buttons: list[BubbleToggle] = []
        self.plot_buttons: list[BubbleToggle] = []
        self.digit_labels: list[QLabel] = []
        self.digit_steps = (1000.0, 100.0, 10.0, 1.0, 0.1, 0.01)
        self.selected_digit_index = 3
        self.target_slider: QSlider | None = None
        self.backend = control_backend
        self.backend_available = control_backend is not None
        self.owns_backend = control_backend is None
        self.backend_status = f"{self.backend_mode.upper()} backend not connected"
        self.backend_connection = "Not Connected"
        self.backend_destination = "None"
        self.backend_packets = 0
        self._status_tick = 0
        self._last_pending_signature = None
        self._local_edit_dirty = False

        if self.owns_backend:
            self._start_backend()
        elif self.backend_available:
            self.backend_connection = "Connected"
            self.backend_destination = "Shared ControlService"
            self.backend_status = f"{self.backend_mode.upper()} shared backend connected"
        self._promote_instruction_header()

        workspace_frame, workspace = self.add_workspace()
        workspace_frame.setObjectName("fieldControlWorkspace")
        workspace.setContentsMargins(12, 12, 12, 12)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_channel_matrix())
        splitter.addWidget(self._build_controller_panel())
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 5)
        workspace.addWidget(splitter, 1)

        self._refresh_selection()
        self._refresh_target_display()
        self._install_shortcuts()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick_feedback)
        self.timer.start(125)

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
        nav_layout.addStretch(1)
        if self.open_sequencer is not None:
            sequencer_button = QPushButton("Sequencer")
            sequencer_button.setObjectName("fieldSequencerButton")
            sequencer_button.setCursor(Qt.PointingHandCursor)
            sequencer_button.clicked.connect(lambda checked=False: self.open_sequencer())
            nav_layout.addWidget(sequencer_button)

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
        layout.addLayout(bulk_controls, 0, 0, 1, 5)

        headers = ["Channel", "Target", "On", "En", "Plot"]
        for col, text in enumerate(headers):
            label = QLabel(text)
            label.setObjectName("fieldHeader")
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label, 1, col)
        layout.setColumnStretch(0, 2)
        for col in range(1, 5):
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

            value = QLabel("0.00")
            value.setObjectName("fieldValue")
            value.setAlignment(Qt.AlignCenter)

            select = QPushButton("Select")
            select.setObjectName("fieldSelect")
            select.clicked.connect(lambda checked=False, idx=row - 2: self._select_channel(idx))

            card_layout.addWidget(name, 0, 0)
            card_layout.addWidget(value, 0, 1)
            card_layout.addWidget(select, 0, 2)

            layout.addWidget(card, row, 0, 1, 2)
            on_toggle = BubbleToggle(f"{channel} output on", "#49e6ff")
            enable_toggle = BubbleToggle(f"{channel} enabled", "#7cffb2")
            plot_toggle = BubbleToggle(f"{channel} plotted", "#ffb52d")
            on_toggle.setChecked(True)
            enable_toggle.setChecked(True)
            plot_toggle.setChecked(True)
            on_toggle.toggled.connect(lambda checked=False: self._mark_pending_signature_from_ui())
            enable_toggle.toggled.connect(lambda checked=False: self._mark_pending_signature_from_ui())
            plot_toggle.toggled.connect(lambda checked=False: self._refresh_plot())
            layout.addWidget(on_toggle, row, 2, Qt.AlignVCenter)
            layout.addWidget(enable_toggle, row, 3, Qt.AlignVCenter)
            layout.addWidget(plot_toggle, row, 4, Qt.AlignVCenter)

            self.value_labels.append(value)
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

        layout.addWidget(self.connection_dot)
        layout.addWidget(self.connection_label, 1)
        layout.addWidget(self.destination_label, 2)
        layout.addWidget(self.packets_label, 1)
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

        self.time_plot = TimeDomainPlot(panel)
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
        self._local_edit_dirty = True
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

    def _tick_feedback(self) -> None:
        if self.backend_available and self.backend is not None:
            try:
                snapshot = self.backend.LatestSnapshot()
                channels = snapshot["channels"]
                for index in range(min(len(CHANNEL_NAMES), len(channels))):
                    self.actual_values[index] = float(channels[index]["actual"])
                self._sync_pending_command()
                health = self.backend.Health()
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
                self.backend_connection = "Not Connected"
                self.backend_destination = self.backend_mode.upper()
                self.backend_status = f"{self.backend_mode.upper()} fallback: {exc}"
                self.backend_label.setText(self.backend_status)
                self._refresh_backend_status_panel()
        else:
            target = self.target_values[self.selected_index]
            self.actual_values[self.selected_index] = self.actual_models[self.selected_index].step(target)
        self._update_speedometer()

    def _sync_pending_command(self) -> None:
        if self.backend is None or not hasattr(self.backend, "PendingCommand"):
            return
        try:
            command = self.backend.PendingCommand()
        except Exception:
            return
        if self._local_edit_dirty:
            return
        signature = self._pending_signature(command)
        if signature == self._last_pending_signature:
            return
        self._last_pending_signature = signature
        changed = False
        for index, channel in enumerate(command[:len(CHANNEL_NAMES)]):
            target = clamp(float(channel["target"]))
            if abs(self.target_values[index] - target) >= 0.01:
                self.target_values[index] = target
                changed = True
            if index < len(self.on_buttons):
                self.on_buttons[index].blockSignals(True)
                self.on_buttons[index].setChecked(bool(channel["on"]))
                self.on_buttons[index].blockSignals(False)
            if index < len(self.enable_buttons):
                self.enable_buttons[index].blockSignals(True)
                self.enable_buttons[index].setChecked(bool(channel["enabled"]))
                self.enable_buttons[index].blockSignals(False)
        if changed:
            self._refresh_target_display()

    def _pending_signature(self, command) -> tuple[tuple[float, bool, bool], ...]:
        return tuple(
            (
                round(clamp(float(channel["target"])), 4),
                bool(channel["on"]),
                bool(channel["enabled"]),
            )
            for channel in command[:len(CHANNEL_NAMES)]
        )

    def _update_speedometer(self) -> None:
        target = self.target_values[self.selected_index]
        actual = self.actual_values[self.selected_index]
        error = target - actual
        converged = abs(error) <= CONVERGENCE_TOLERANCE
        self._update_convergence_state(self.selected_index, converged)
        seconds = self._convergence_seconds(self.selected_index)

        self.speedometer.set_values(target, actual, CHANNEL_NAMES[self.selected_index])
        self.speedometer.set_status(converged, error, CONVERGENCE_TOLERANCE, seconds, self.convergence_started_at[self.selected_index] is not None)
        self._append_plot_sample(self.selected_index, target, actual, error)
        self._refresh_plot()

    def _start_backend(self) -> None:
        if CycloViz is None or not hasattr(CycloViz, "ControlService"):
            return
        try:
            self.backend = CycloViz.ControlService()
            if self.backend_mode == "simulation":
                self.backend.StartSimulator(20.0)
                self.backend_connection = "Connected"
                self.backend_destination = "Simulation"
                self.backend_status = "SIMULATION Connected | simulator://local"
            elif self.backend_mode == "zmq":
                self.backend.StartServer(self.zmq_endpoint)
                self.backend_connection = "Listening"
                self.backend_destination = self.zmq_endpoint
                self.backend_status = f"ZMQ Listening | {self.zmq_endpoint}"
            else:
                raise ValueError(f"Unknown backend mode: {self.backend_mode}")
            self.backend_available = True
            self._refresh_backend_status_panel()
        except Exception as exc:
            self.backend = None
            self.backend_available = False
            self.backend_connection = "Not Connected"
            self.backend_destination = self.backend_mode.upper()
            self.backend_status = f"{self.backend_mode.upper()} unavailable: {exc}"
            self._refresh_backend_status_panel()

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
                self.backend.SetChannelCommand(index, target, on, enabled)
                if hasattr(self.backend, "PendingCommand"):
                    self._last_pending_signature = self._pending_signature(self.backend.PendingCommand())
                applied = bool(self.backend.ApplyCommand())
                self._local_edit_dirty = False
                mode = self.backend_mode.upper()
                self.backend_status = f"{mode} command applied" if applied else f"{mode} command rejected"
                self.backend_label.setText(self.backend_status)
                return applied
            except Exception as exc:
                self.backend_status = f"Simulator command failed: {exc}"
                self.backend_label.setText(self.backend_status)
                return False

        self.actual_models[index].value = self.actual_values[index]
        self.backend_label.setText("Local UI fallback command applied")
        return True

    def _apply_all_commands(self) -> None:
        applied = [self._apply_channel_command(index) for index in range(len(CHANNEL_NAMES))]
        for index, ok in enumerate(applied):
            if ok:
                self._begin_convergence_timer(index)
        ok_count = sum(1 for ok in applied if ok)
        self.backend_label.setText(f"{ok_count}/{len(CHANNEL_NAMES)} channel commands applied")
        self._local_edit_dirty = False

    def _set_all_toggles(self, buttons: list[BubbleToggle], checked: bool) -> None:
        for button in buttons:
            button.setChecked(checked)
        self._local_edit_dirty = True

    def _mark_pending_signature_from_ui(self) -> None:
        self._local_edit_dirty = True

    def _hold_selected_actual(self) -> None:
        self._set_selected_target(self.actual_values[self.selected_index])

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
        self.history[index].append((time.perf_counter(), actual, target, error))

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
