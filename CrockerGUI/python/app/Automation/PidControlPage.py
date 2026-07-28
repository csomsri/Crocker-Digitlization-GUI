from __future__ import annotations

import csv
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from python.app.PageShell import DetailPage
from python.app.widgets.MagneticFieldWidgets import (
    CHANNEL_NAMES,
    MAX_GAUGE_VALUE,
    SimulatedActual,
    TimeDomainPlot,
    clamp,
)

try:
    import CycloViz
except Exception:
    CycloViz = None


PID_OUTPUT_LIMIT = MAX_GAUGE_VALUE
UNSAFE_STATUSES = {"Fault", "Interlocked"}


class PidControlPage(DetailPage):
    def __init__(
        self,
        go_back: Callable[[], None],
        backend_mode: str,
        zmq_endpoint: str = "tcp://0.0.0.0:5555",
    ) -> None:
        super().__init__(
            "PID Control",
            "Closed-loop channel control",
            "Back to Automation",
            go_back,
        )

        self.backend_mode = backend_mode.lower()
        self.zmq_endpoint = zmq_endpoint
        self.selected_index = 0
        self.command_values = [0.0 for _ in CHANNEL_NAMES]
        self.actual_values = [0.0 for _ in CHANNEL_NAMES]
        self.channel_on = [False for _ in CHANNEL_NAMES]
        self.channel_enabled = [False for _ in CHANNEL_NAMES]
        self.telemetry_on = [False for _ in CHANNEL_NAMES]
        self.telemetry_enabled = [False for _ in CHANNEL_NAMES]
        self.desired_state_initialized = [False for _ in CHANNEL_NAMES]
        self.channel_status = ["Unknown" for _ in CHANNEL_NAMES]
        self.channel_interlocked = [False for _ in CHANNEL_NAMES]
        self.actual_models = [SimulatedActual() for _ in CHANNEL_NAMES]
        self.history: list[tuple[float, float, float, float]] = []
        self.armed = False
        self.pid_enabled = False
        self.pid_integral = 0.0
        self.pid_previous_error: float | None = None
        self.pid_previous_time: float | None = None
        self.pid_output_bias = 0.0
        self.backend = None
        self.backend_available = False
        self.backend_connection = "Not Connected"
        self.backend_destination = "None"
        self.backend_packets = 0
        self.last_apply_ok = False
        self.last_safety_message = "Not armed"
        self.log_path = Path(__file__).resolve().parents[3] / "logs" / "pid_commands.csv"

        self._start_backend()

        _, workspace = self.add_workspace()
        workspace.setContentsMargins(16, 16, 16, 16)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        workspace.addLayout(layout, 1)

        layout.addWidget(self._build_control_panel())
        self.time_plot = TimeDomainPlot()
        layout.addWidget(self.time_plot)
        layout.addWidget(self._build_status_panel())
        layout.addStretch(1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick_feedback)
        self.timer.start(125)
        self._refresh_status()

    def _build_control_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("pidPanel")
        layout = QGridLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(10)

        title = QLabel("PID Channel Control")
        title.setObjectName("pidTitle")
        self.pid_status_label = QLabel("Standby")
        self.pid_status_label.setObjectName("pidStatus")
        self.pid_status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(title, 0, 0, 1, 2)
        layout.addWidget(self.pid_status_label, 0, 2, 1, 2)

        self.channel_select = QComboBox()
        self.channel_select.setObjectName("pidChannelSelect")
        self.channel_select.addItems(CHANNEL_NAMES)
        self.channel_select.currentIndexChanged.connect(self._set_channel)

        self.enable_button = QPushButton("Enable PID")
        self.enable_button.setObjectName("pidEnable")
        self.enable_button.setCheckable(True)
        self.enable_button.setEnabled(False)
        self.enable_button.toggled.connect(self._set_pid_enabled)

        self.arm_button = QPushButton("Arm PID")
        self.arm_button.setObjectName("pidArm")
        self.arm_button.setCheckable(True)
        self.arm_button.toggled.connect(self._set_armed)
        layout.addWidget(self.channel_select, 1, 0, 1, 2)
        layout.addWidget(self.arm_button, 1, 2)
        layout.addWidget(self.enable_button, 1, 3)

        self.setpoint_input = self._make_spinbox(0.0, MAX_GAUGE_VALUE, 0.1, " A")
        self.kp_input = self._make_spinbox(0.0, 100.0, 0.1)
        self.ki_input = self._make_spinbox(0.0, 100.0, 0.01)
        self.kd_input = self._make_spinbox(0.0, 100.0, 0.01)
        self.kp_input.setValue(0.8)
        self.ki_input.setValue(0.05)

        for column, (label_text, widget) in enumerate(
            (
                ("Setpoint", self.setpoint_input),
                ("Kp", self.kp_input),
                ("Ki", self.ki_input),
                ("Kd", self.kd_input),
            )
        ):
            label = QLabel(label_text)
            label.setObjectName("pidFieldLabel")
            layout.addWidget(label, 2, column)
            layout.addWidget(widget, 3, column)

        self.min_output_input = self._make_spinbox(0.0, MAX_GAUGE_VALUE, 1.0, " A")
        self.max_output_input = self._make_spinbox(0.0, MAX_GAUGE_VALUE, 1.0, " A")
        self.max_step_input = self._make_spinbox(0.1, 100.0, 0.5, " A/tick")
        self.max_output_input.setValue(MAX_GAUGE_VALUE)
        self.max_step_input.setValue(10.0)

        for column, (label_text, widget) in enumerate(
            (
                ("Min Cmd", self.min_output_input),
                ("Max Cmd", self.max_output_input),
                ("Max Step", self.max_step_input),
            )
        ):
            label = QLabel(label_text)
            label.setObjectName("pidFieldLabel")
            layout.addWidget(label, 4, column)
            layout.addWidget(widget, 5, column)

        self.output_on_check = QCheckBox("Output On")
        self.output_on_check.setObjectName("toggleRow")
        self.output_on_check.toggled.connect(self._set_output_on)
        self.control_enabled_check = QCheckBox("Control Enabled")
        self.control_enabled_check.setObjectName("toggleRow")
        self.control_enabled_check.toggled.connect(self._set_control_enabled)
        self.dry_run_check = QCheckBox("Dry Run")
        self.dry_run_check.setObjectName("toggleRow")
        self.dry_run_check.setChecked(True)
        self.dry_run_check.toggled.connect(lambda checked=False: self._refresh_status())
        layout.addWidget(self.output_on_check, 4, 3)
        layout.addWidget(self.control_enabled_check, 5, 3)
        layout.addWidget(self.dry_run_check, 6, 3)

        actions = QHBoxLayout()
        self.hold_button = QPushButton("Hold Actual")
        self.hold_button.setObjectName("fieldAction")
        self.hold_button.clicked.connect(self._hold_actual)
        self.zero_button = QPushButton("Zero Command")
        self.zero_button.setObjectName("fieldAction")
        self.zero_button.clicked.connect(self._zero_command)
        self.stop_button = QPushButton("Stop PID / Hold")
        self.stop_button.setObjectName("pidStop")
        self.stop_button.clicked.connect(lambda checked=False: self._stop_pid("Operator stop"))
        actions.addWidget(self.hold_button)
        actions.addWidget(self.zero_button)
        actions.addWidget(self.stop_button)
        layout.addLayout(actions, 6, 0, 1, 3)
        return panel

    def _build_status_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("fieldBackendStatus")
        panel.setFixedHeight(70)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        self.connection_dot = QLabel()
        self.connection_dot.setObjectName("fieldStatusDot")
        self.connection_dot.setProperty("connected", False)
        self.connection_dot.setFixedSize(18, 18)
        self.connection_label = QLabel()
        self.connection_label.setObjectName("fieldStatusText")
        self.destination_label = QLabel()
        self.destination_label.setObjectName("fieldStatusText")
        self.command_label = QLabel()
        self.command_label.setObjectName("fieldStatusText")
        self.safety_label = QLabel()
        self.safety_label.setObjectName("fieldStatusText")

        layout.addWidget(self.connection_dot)
        layout.addWidget(self.connection_label, 1)
        layout.addWidget(self.destination_label, 2)
        layout.addWidget(self.command_label, 2)
        layout.addWidget(self.safety_label, 2)
        return panel

    def _make_spinbox(self, lower: float, upper: float, step: float, suffix: str = "") -> QDoubleSpinBox:
        spinbox = QDoubleSpinBox()
        spinbox.setObjectName("pidSpin")
        spinbox.setRange(lower, upper)
        spinbox.setDecimals(3 if step < 0.1 else 2)
        spinbox.setSingleStep(step)
        spinbox.setSuffix(suffix)
        return spinbox

    def _set_channel(self, index: int) -> None:
        if self.pid_enabled:
            self._stop_pid("Channel changed")
        self.selected_index = index
        self.history.clear()
        self._reset_pid_state()
        self._sync_channel_toggles()
        self._refresh_status()
        self._refresh_plot()

    def _set_armed(self, armed: bool) -> None:
        self.armed = armed
        if not armed and self.pid_enabled:
            self._stop_pid("Disarmed")
        self.enable_button.setEnabled(armed)
        self.arm_button.setText("Disarm PID" if armed else "Arm PID")
        self.last_safety_message = "Armed" if armed else "Not armed"
        self._refresh_status()

    def _set_pid_enabled(self, enabled: bool) -> None:
        if enabled and not self._is_safe_to_run():
            self.enable_button.blockSignals(True)
            self.enable_button.setChecked(False)
            self.enable_button.blockSignals(False)
            self.pid_enabled = False
            self._refresh_status()
            return
        self.pid_enabled = enabled
        self.pid_output_bias = self.command_values[self.selected_index]
        self._reset_pid_state()
        self.enable_button.setText("Disable PID" if enabled else "Enable PID")
        self.last_safety_message = "PID active" if enabled else "PID stopped"
        self._refresh_status()

    def _reset_pid_state(self) -> None:
        self.pid_integral = 0.0
        self.pid_previous_error = None
        self.pid_previous_time = None

    def _zero_command(self) -> None:
        self._stop_pid("Zero command")
        self.command_values[self.selected_index] = 0.0
        self._apply_channel_command(self.selected_index)
        self._refresh_status()

    def _hold_actual(self) -> None:
        self.setpoint_input.setValue(self.actual_values[self.selected_index])
        self.pid_output_bias = self.command_values[self.selected_index]
        self._reset_pid_state()
        self._refresh_status()

    def _set_output_on(self, checked: bool) -> None:
        self.channel_on[self.selected_index] = checked
        self.desired_state_initialized[self.selected_index] = True
        self._refresh_status()

    def _set_control_enabled(self, checked: bool) -> None:
        self.channel_enabled[self.selected_index] = checked
        self.desired_state_initialized[self.selected_index] = True
        self._refresh_status()

    def _sync_channel_toggles(self) -> None:
        self.output_on_check.blockSignals(True)
        self.control_enabled_check.blockSignals(True)
        self.output_on_check.setChecked(self.channel_on[self.selected_index])
        self.control_enabled_check.setChecked(self.channel_enabled[self.selected_index])
        self.output_on_check.blockSignals(False)
        self.control_enabled_check.blockSignals(False)

    def _tick_feedback(self) -> None:
        if self.backend_available and self.backend is not None:
            try:
                snapshot = self.backend.LatestSnapshot()
                channels = snapshot["channels"]
                for index in range(min(len(CHANNEL_NAMES), len(channels))):
                    channel = channels[index]
                    self.actual_values[index] = float(channel["actual"])
                    self.telemetry_on[index] = bool(channel["on"])
                    self.telemetry_enabled[index] = bool(channel["enabled"])
                    if not self.desired_state_initialized[index]:
                        self.channel_on[index] = self.telemetry_on[index]
                        self.channel_enabled[index] = self.telemetry_enabled[index]
                        self.desired_state_initialized[index] = True
                    self.channel_status[index] = str(channel["status"])
                    self.channel_interlocked[index] = bool(channel["interlocked"])
                health = self.backend.Health()
                self.backend_connection = str(health["connection"])
                self.backend_destination = str(health["endpoint"])
                self.backend_packets = int(health["received_packets"])
            except Exception as exc:
                self.backend_available = False
                self.backend_connection = "Not Connected"
                self.backend_destination = f"{self.backend_mode.upper()} fallback: {exc}"
        else:
            target = self.command_values[self.selected_index]
            self.actual_values[self.selected_index] = self.actual_models[self.selected_index].step(target)

        self._sync_channel_toggles()
        if self.pid_enabled and not self._is_safe_to_run():
            self._stop_pid(self.last_safety_message)
        self._tick_pid_controller()
        self._append_plot_sample()
        self._refresh_plot()
        self._refresh_status()

    def _tick_pid_controller(self) -> None:
        if not self.pid_enabled:
            return

        now = time.perf_counter()
        error = self.setpoint_input.value() - self.actual_values[self.selected_index]
        if self.pid_previous_time is None:
            self.pid_previous_time = now
            self.pid_previous_error = error
            return

        dt = max(now - self.pid_previous_time, 1.0e-3)
        previous_error = self.pid_previous_error if self.pid_previous_error is not None else error
        self.pid_integral = max(-PID_OUTPUT_LIMIT, min(PID_OUTPUT_LIMIT, self.pid_integral + error * dt))
        derivative = (error - previous_error) / dt
        raw_output = (
            self.pid_output_bias
            + self.kp_input.value() * error
            + self.ki_input.value() * self.pid_integral
            + self.kd_input.value() * derivative
        )
        self.command_values[self.selected_index] = self._limited_output(raw_output)
        self._apply_channel_command(self.selected_index)
        self.pid_previous_time = now
        self.pid_previous_error = error

    def _apply_channel_command(self, index: int) -> bool:
        target = self.command_values[index]
        on = self.channel_on[index]
        enabled = self.channel_enabled[index]
        ok = False
        if self.dry_run_check.isChecked():
            self.last_apply_ok = True
            self.last_safety_message = "Dry run: command logged only"
            self._log_command(index, target, on, enabled, True)
            return True
        if self.backend_available and self.backend is not None:
            try:
                self.backend.SetChannelCommand(index, target, on, enabled)
                ok = bool(self.backend.ApplyCommand())
            except Exception as exc:
                self.last_safety_message = f"Command failed: {exc}"
                ok = False
            self.last_apply_ok = ok
            self._log_command(index, target, on, enabled, ok)
            return ok
        self.actual_models[index].value = self.actual_values[index]
        self.last_apply_ok = True
        self._log_command(index, target, on, enabled, True)
        return True

    def _limited_output(self, raw_output: float) -> float:
        minimum = min(self.min_output_input.value(), self.max_output_input.value())
        maximum = max(self.min_output_input.value(), self.max_output_input.value())
        bounded = clamp(raw_output, minimum, maximum)
        previous = self.command_values[self.selected_index]
        max_step = self.max_step_input.value()
        return max(previous - max_step, min(previous + max_step, bounded))

    def _is_safe_to_run(self) -> bool:
        if not self.armed:
            self.last_safety_message = "Not armed"
            return False
        if not self.channel_on[self.selected_index]:
            self.last_safety_message = "Output is off"
            return False
        if not self.channel_enabled[self.selected_index]:
            self.last_safety_message = "Control is disabled"
            return False
        if self.channel_interlocked[self.selected_index]:
            self.last_safety_message = "Channel interlocked"
            return False
        status = self.channel_status[self.selected_index]
        if status in UNSAFE_STATUSES:
            self.last_safety_message = f"Unsafe channel status: {status}"
            return False
        self.last_safety_message = "Safety checks passed"
        return True

    def _stop_pid(self, reason: str) -> None:
        self.pid_enabled = False
        self.enable_button.blockSignals(True)
        self.enable_button.setChecked(False)
        self.enable_button.setText("Enable PID")
        self.enable_button.blockSignals(False)
        self._reset_pid_state()
        self.last_safety_message = reason
        self._apply_channel_command(self.selected_index)
        self._refresh_status()

    def _log_command(self, index: int, target: float, on: bool, enabled: bool, ok: bool) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        exists = self.log_path.exists()
        with self.log_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if not exists:
                writer.writerow(
                    [
                        "timestamp",
                        "channel_index",
                        "channel",
                        "setpoint",
                        "actual",
                        "error",
                        "command",
                        "kp",
                        "ki",
                        "kd",
                        "output_on",
                    "control_enabled",
                    "dry_run",
                    "armed",
                        "pid_enabled",
                        "status",
                        "interlocked",
                        "ok",
                        "message",
                    ]
                )
            actual = self.actual_values[index]
            setpoint = self.setpoint_input.value()
            writer.writerow(
                [
                    f"{time.time():.6f}",
                    index,
                    CHANNEL_NAMES[index],
                    f"{setpoint:.6f}",
                    f"{actual:.6f}",
                    f"{setpoint - actual:.6f}",
                    f"{target:.6f}",
                    f"{self.kp_input.value():.6f}",
                    f"{self.ki_input.value():.6f}",
                    f"{self.kd_input.value():.6f}",
                    on,
                    enabled,
                    self.dry_run_check.isChecked(),
                    self.armed,
                    self.pid_enabled,
                    self.channel_status[index],
                    self.channel_interlocked[index],
                    ok,
                    self.last_safety_message,
                ]
            )

    def _append_plot_sample(self) -> None:
        actual = self.actual_values[self.selected_index]
        setpoint = self.setpoint_input.value()
        error = setpoint - actual
        self.history.append((time.perf_counter(), actual, setpoint, error))
        self.history = self.history[-240:]

    def _refresh_plot(self) -> None:
        self.time_plot.set_samples(self.history)

    def _refresh_status(self) -> None:
        channel = CHANNEL_NAMES[self.selected_index]
        actual = self.actual_values[self.selected_index]
        command = self.command_values[self.selected_index]
        error = self.setpoint_input.value() - actual
        state = "active" if self.pid_enabled else "standby"
        self.pid_status_label.setText(f"{channel} {state} | err {error:.2f} A | cmd {command:.2f} A")

        connected = self.backend_available and self.backend_connection.lower() in {"connected", "listening"}
        self.connection_dot.setProperty("connected", connected)
        self.connection_dot.style().unpolish(self.connection_dot)
        self.connection_dot.style().polish(self.connection_dot)
        self.connection_label.setText(f"Connection\n{self.backend_connection}")
        self.destination_label.setText(f"Destination\n{self.backend_destination}")
        self.command_label.setText(f"Channel\n{channel} | packets {self.backend_packets}")
        self.safety_label.setText(
            "Safety\n"
            f"{self.last_safety_message} | last apply {self.last_apply_ok} | "
            f"dry run {self.dry_run_check.isChecked()} | "
            f"hw on/en {self.telemetry_on[self.selected_index]}/{self.telemetry_enabled[self.selected_index]}"
        )

    def _start_backend(self) -> None:
        if CycloViz is None or not hasattr(CycloViz, "ControlService"):
            return
        try:
            self.backend = CycloViz.ControlService()
            if self.backend_mode == "simulation":
                self.backend.StartSimulator(20.0)
                self.backend_connection = "Connected"
                self.backend_destination = "Simulation"
            elif self.backend_mode == "zmq":
                self.backend.StartServer(self.zmq_endpoint)
                self.backend_connection = "Listening"
                self.backend_destination = self.zmq_endpoint
            else:
                raise ValueError(f"Unknown backend mode: {self.backend_mode}")
            self.backend_available = True
        except Exception as exc:
            self.backend = None
            self.backend_available = False
            self.backend_connection = "Not Connected"
            self.backend_destination = f"{self.backend_mode.upper()} unavailable: {exc}"

    def closeEvent(self, event) -> None:
        self.stop_backend()
        super().closeEvent(event)

    def stop_backend(self) -> None:
        if self.backend is not None:
            try:
                self.backend.Stop()
            except Exception:
                pass
        self.backend_available = False
