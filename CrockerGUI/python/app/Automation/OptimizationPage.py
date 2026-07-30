from __future__ import annotations

import math
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from python.app.PageShell import DetailPage
from python.app.widgets.MagneticFieldWidgets import CHANNEL_NAMES, MAX_GAUGE_VALUE, SimulatedActual
from source.Python.PID_Tuner.bayesion_optimization.trial_suggestion import (
    AssistedTrialSuggester,
    SafeCandidate,
)

try:
    import CycloViz
except Exception:
    CycloViz = None


UNSAFE_STATUSES = {"Fault", "Interlocked"}
TRIAL_COLUMNS = ["Trial", "Channel", "Candidate", "Range", "Actual", "Error", "Score", "Safe"]


class OptimizationPage(DetailPage):
    def __init__(
        self,
        go_back: Callable[[], None],
        backend_mode: str,
        zmq_endpoint: str = "tcp://0.0.0.0:5555",
    ) -> None:
        super().__init__(
            "Assisted Tuning",
            "Safe assisted tuning",
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
        self.backend = None
        self.backend_available = False
        self.backend_connection = "Not Connected"
        self.backend_destination = "None"
        self.backend_packets = 0
        self.armed = False
        self.pending_candidate: SafeCandidate | None = None
        self.active_trial: SafeCandidate | None = None
        self.trial_started_at: float | None = None
        self.trial_samples: list[float] = []
        self.last_message = "Not armed"
        self.last_apply_ok = False
        log_path = Path(__file__).resolve().parents[3] / "logs" / "assisted_tuning_trials.csv"
        self.optimizer = AssistedTrialSuggester(CHANNEL_NAMES, log_path)
        self.trials = self.optimizer.trials

        self._start_backend()

        _, workspace = self.add_workspace()
        workspace.setContentsMargins(16, 16, 16, 16)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        workspace.addLayout(layout, 1)
        layout.addWidget(self._build_setup_panel())
        layout.addWidget(self._build_candidate_panel())
        layout.addWidget(self._build_trial_table(), 1)
        layout.addWidget(self._build_status_panel())

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick_feedback)
        self.timer.start(125)
        self.approve_shortcut = QShortcut(QKeySequence(Qt.Key_Return), self)
        self.approve_shortcut.activated.connect(self._approve_trial)
        self.keypad_approve_shortcut = QShortcut(QKeySequence(Qt.Key_Enter), self)
        self.keypad_approve_shortcut.activated.connect(self._approve_trial)
        self._refresh_status()

    def _build_setup_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("pidPanel")
        layout = QGridLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(10)

        title = QLabel("Target-Guided Trial Session")
        title.setObjectName("pidTitle")
        self.run_status_label = QLabel("Idle")
        self.run_status_label.setObjectName("pidStatus")
        self.run_status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(title, 0, 0, 1, 2)
        layout.addWidget(self.run_status_label, 0, 2, 1, 3)

        self.channel_select = QComboBox()
        self.channel_select.setObjectName("pidChannelSelect")
        self.channel_select.addItems(CHANNEL_NAMES)
        self.channel_select.currentIndexChanged.connect(self._set_channel)

        self.arm_button = QPushButton("Arm Trial Runner")
        self.arm_button.setObjectName("pidArm")
        self.arm_button.setCheckable(True)
        self.arm_button.toggled.connect(self._set_armed)
        channel_label = QLabel("Controlled Channel")
        channel_label.setObjectName("pidFieldLabel")
        target_label = QLabel("Target Value")
        target_label.setObjectName("pidFieldLabel")
        layout.addWidget(channel_label, 1, 0, 1, 2)
        layout.addWidget(target_label, 1, 2, 1, 2)
        layout.addWidget(self.arm_button, 1, 4)

        self.target_actual_input = self._make_spinbox(0.0, MAX_GAUGE_VALUE, 0.1, " A")
        self.target_actual_input.valueChanged.connect(self._target_changed)
        layout.addWidget(self.channel_select, 2, 0, 1, 2)
        layout.addWidget(self.target_actual_input, 2, 2, 1, 2)

        self.min_command_input = self._make_spinbox(0.0, MAX_GAUGE_VALUE, 1.0, " A")
        self.max_command_input = self._make_spinbox(0.0, MAX_GAUGE_VALUE, 1.0, " A")
        self.max_step_input = self._make_spinbox(0.1, 100.0, 0.5, " A/trial")
        self.min_step_input = self._make_spinbox(0.01, 100.0, 0.1, " A/trial")
        self.tolerance_input = self._make_spinbox(0.01, MAX_GAUGE_VALUE, 0.1, " A")
        self.observe_seconds_input = self._make_spinbox(0.5, 60.0, 0.5, " s")
        self.max_command_input.setValue(MAX_GAUGE_VALUE)
        self.max_step_input.setValue(10.0)
        self.min_step_input.setValue(0.5)
        self.tolerance_input.setValue(1.0)
        self.observe_seconds_input.setValue(3.0)

        for column, (label_text, widget) in enumerate(
            (
                ("Min Cmd", self.min_command_input),
                ("Max Cmd", self.max_command_input),
                ("Initial Range", self.max_step_input),
                ("Minimum Range", self.min_step_input),
                ("Target Tolerance", self.tolerance_input),
                ("Observe", self.observe_seconds_input),
            )
        ):
            label = QLabel(label_text)
            label.setObjectName("pidFieldLabel")
            layout.addWidget(label, 3, column)
            layout.addWidget(widget, 4, column)

        self.automated_trials_check = QCheckBox("Automated Trials")
        self.automated_trials_check.setObjectName("toggleRow")
        self.automated_trials_check.toggled.connect(self._set_automated_trials)
        self.auto_approve_check = QCheckBox("Automatically Approve Trials")
        self.auto_approve_check.setObjectName("toggleRow")
        self.auto_approve_check.toggled.connect(self._set_auto_approve)
        self.output_on_check = QCheckBox("Output On")
        self.output_on_check.setObjectName("toggleRow")
        self.output_on_check.toggled.connect(self._set_output_on)
        self.control_enabled_check = QCheckBox("Control Enabled")
        self.control_enabled_check.setObjectName("toggleRow")
        self.control_enabled_check.toggled.connect(self._set_control_enabled)
        self.dry_run_check = QCheckBox("Dry Run")
        self.dry_run_check.setObjectName("toggleRow")
        self.dry_run_check.setChecked(True)
        self.dry_run_check.toggled.connect(self._safety_setting_changed)
        layout.addWidget(self.automated_trials_check, 5, 0)
        layout.addWidget(self.output_on_check, 5, 1)
        layout.addWidget(self.control_enabled_check, 5, 2)
        layout.addWidget(self.dry_run_check, 5, 3)
        layout.addWidget(self.auto_approve_check, 5, 4)
        return panel

    def _build_candidate_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("pidPanel")
        layout = QGridLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(10)

        self.candidate_label = QLabel("No trial suggested")
        self.candidate_label.setObjectName("pidStatus")
        self.candidate_label.setWordWrap(True)
        layout.addWidget(self.candidate_label, 0, 0, 1, 4)

        self.generate_button = QPushButton("Prepare Next Trial")
        self.generate_button.setObjectName("fieldAction")
        self.generate_button.clicked.connect(self._generate_candidate)
        self.approve_button = QPushButton("Approve Trial (Enter)")
        self.approve_button.setObjectName("pidEnable")
        self.approve_button.clicked.connect(self._approve_trial)
        self.reject_button = QPushButton("Reject Trial")
        self.reject_button.setObjectName("fieldAction")
        self.reject_button.clicked.connect(self._reject_candidate)
        self.stop_button = QPushButton("Stop Trial")
        self.stop_button.setObjectName("pidStop")
        self.stop_button.clicked.connect(lambda checked=False: self._stop_trial("Operator stop"))
        for column, button in enumerate((self.generate_button, self.approve_button, self.reject_button, self.stop_button)):
            layout.addWidget(button, 1, column)
        return panel

    def _build_trial_table(self) -> QTableWidget:
        self.trial_table = QTableWidget(0, len(TRIAL_COLUMNS))
        self.trial_table.setHorizontalHeaderLabels(TRIAL_COLUMNS)
        self.trial_table.setObjectName("optimizationTable")
        return self.trial_table

    def _build_status_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("fieldBackendStatus")
        panel.setFixedHeight(74)
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
        self.safety_label = QLabel()
        self.safety_label.setObjectName("fieldStatusText")
        layout.addWidget(self.connection_dot)
        layout.addWidget(self.connection_label, 1)
        layout.addWidget(self.destination_label, 2)
        layout.addWidget(self.safety_label, 3)
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
        self._stop_trial("Channel changed")
        self.selected_index = index
        self.pending_candidate = None
        self._sync_channel_toggles()
        self._refresh_candidate()
        self._refresh_status()

    def _set_armed(self, armed: bool) -> None:
        self.armed = armed
        self.arm_button.setText("Disarm Trial Runner" if armed else "Arm Trial Runner")
        if not armed:
            self._stop_trial("Disarmed")
            self.pending_candidate = None
        self.last_message = "Armed" if armed else "Not armed"
        self._maybe_generate_next_candidate()
        self._refresh_status()

    def _set_automated_trials(self, checked: bool) -> None:
        if checked:
            self.last_message = "Automated trials enabled"
            self._maybe_generate_next_candidate()
        else:
            self.pending_candidate = None
            self.last_message = "Automated trials disabled"
        self._refresh_status()

    def _set_auto_approve(self, checked: bool) -> None:
        if checked and self.pending_candidate is not None:
            self._approve_trial()
        else:
            self.last_message = "Automatic approval enabled" if checked else "Manual approval required"
            self._maybe_generate_next_candidate()
            self._refresh_status()

    def _target_changed(self, _value: float) -> None:
        if self.active_trial is not None:
            self._stop_trial("Target changed")
        self.pending_candidate = None
        if self.automated_trials_check.isChecked():
            self._maybe_generate_next_candidate()
        self._refresh_status()

    def _set_output_on(self, checked: bool) -> None:
        self.channel_on[self.selected_index] = checked
        self.desired_state_initialized[self.selected_index] = True
        self._maybe_generate_next_candidate()
        self._refresh_status()

    def _set_control_enabled(self, checked: bool) -> None:
        self.channel_enabled[self.selected_index] = checked
        self.desired_state_initialized[self.selected_index] = True
        self._maybe_generate_next_candidate()
        self._refresh_status()

    def _safety_setting_changed(self, _checked: bool) -> None:
        self._maybe_generate_next_candidate()
        self._refresh_status()

    def _sync_channel_toggles(self) -> None:
        self.output_on_check.blockSignals(True)
        self.control_enabled_check.blockSignals(True)
        self.output_on_check.setChecked(self.channel_on[self.selected_index])
        self.control_enabled_check.setChecked(self.channel_enabled[self.selected_index])
        self.output_on_check.blockSignals(False)
        self.control_enabled_check.blockSignals(False)

    def _generate_candidate(self) -> None:
        if self.active_trial is not None:
            self.last_message = "A trial is already running"
            self._refresh_status()
            return
        if not self.automated_trials_check.isChecked():
            self.last_message = "Enable Automated Trials first"
            self._refresh_status()
            return
        current_error = abs(self.target_actual_input.value() - self.actual_values[self.selected_index])
        if current_error <= self.tolerance_input.value():
            self.pending_candidate = None
            self.last_message = "Target reached within tolerance"
            self._refresh_status()
            return
        self.pending_candidate = self.optimizer.propose(
            channel=self.selected_index,
            current_command=self.command_values[self.selected_index],
            current_actual=self.actual_values[self.selected_index],
            target_actual=self.target_actual_input.value(),
            min_command=self.min_command_input.value(),
            max_command=self.max_command_input.value(),
            max_step=self.max_step_input.value(),
            min_step=self.min_step_input.value(),
        )
        if not self._candidate_is_safe(self.pending_candidate):
            self.pending_candidate = None
        elif self.auto_approve_check.isChecked():
            self._approve_trial()
        self._refresh_candidate()
        self._refresh_status()

    def _maybe_generate_next_candidate(self) -> None:
        if (
            self.pending_candidate is None
            and self.active_trial is None
            and self.automated_trials_check.isChecked()
            and self.armed
            and self.channel_on[self.selected_index]
            and self.channel_enabled[self.selected_index]
        ):
            self._generate_candidate()

    def _candidate_is_safe(self, candidate: SafeCandidate) -> bool:
        if not self.armed:
            self.last_message = "Rejecting trial: runner is not armed"
            return False
        if not self.channel_on[candidate.channel]:
            self.last_message = "Rejecting trial: output is off"
            return False
        if not self.channel_enabled[candidate.channel]:
            self.last_message = "Rejecting trial: control is disabled"
            return False
        if self.channel_interlocked[candidate.channel]:
            self.last_message = "Rejecting trial: channel interlocked"
            return False
        status = self.channel_status[candidate.channel]
        if status in UNSAFE_STATUSES:
            self.last_message = f"Rejecting trial: unsafe status {status}"
            return False
        current = self.command_values[candidate.channel]
        if abs(candidate.command - current) > candidate.allowed_step + 1.0e-9:
            self.last_message = "Rejecting trial: exceeds adaptive range"
            return False
        self.last_message = "Trial suggestion passed safety checks"
        return True

    def _approve_trial(self) -> None:
        if self.pending_candidate is None:
            self.last_message = "No trial suggestion to approve"
            self._refresh_status()
            return
        if not self._candidate_is_safe(self.pending_candidate):
            self._refresh_candidate()
            self._refresh_status()
            return
        self.active_trial = self.pending_candidate
        self.pending_candidate = None
        self.trial_started_at = time.perf_counter()
        self.trial_samples = []
        self.command_values[self.active_trial.channel] = self.active_trial.command
        self.last_apply_ok = self._apply_channel_command(self.active_trial.channel)
        self.last_message = "Trial running" if self.last_apply_ok else "Trial command failed"
        self._refresh_candidate()
        self._refresh_status()

    def _reject_candidate(self) -> None:
        if self.pending_candidate is not None:
            self._record_trial(self.pending_candidate, safe=False, score=float("inf"), actual=self.actual_values[self.pending_candidate.channel])
        self.pending_candidate = None
        self.last_message = "Trial suggestion rejected"
        self._maybe_generate_next_candidate()
        self._refresh_candidate()
        self._refresh_status()

    def _stop_trial(self, reason: str) -> None:
        self.active_trial = None
        self.trial_started_at = None
        self.trial_samples = []
        self.last_message = reason
        self._refresh_candidate()
        self._refresh_status()

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
        self._observe_active_trial()
        self._refresh_status()

    def _observe_active_trial(self) -> None:
        if self.active_trial is None or self.trial_started_at is None:
            return
        if not self._candidate_is_safe(self.active_trial):
            self._record_trial(
                self.active_trial,
                safe=False,
                score=float("inf"),
                actual=self.actual_values[self.active_trial.channel],
            )
            self._stop_trial(self.last_message)
            return
        self.trial_samples.append(self.actual_values[self.active_trial.channel])
        elapsed = time.perf_counter() - self.trial_started_at
        if elapsed < self.observe_seconds_input.value():
            return

        actual, _error, score = self.optimizer.score_trial(
            self.target_actual_input.value(),
            self.trial_samples,
        )
        self._record_trial(self.active_trial, safe=True, score=score, actual=actual)
        self._stop_trial("Trial complete")
        self._maybe_generate_next_candidate()

    def _apply_channel_command(self, index: int) -> bool:
        target = self.command_values[index]
        on = self.channel_on[index]
        enabled = self.channel_enabled[index]
        if self.dry_run_check.isChecked():
            self.last_apply_ok = True
            return True
        if self.backend_available and self.backend is not None:
            try:
                self.backend.SetChannelCommand(index, target, on, enabled)
                self.last_apply_ok = bool(self.backend.ApplyCommand())
                return self.last_apply_ok
            except Exception as exc:
                self.last_message = f"Command failed: {exc}"
                self.last_apply_ok = False
                return False
        self.actual_models[index].value = self.actual_values[index]
        self.last_apply_ok = True
        return True

    def _record_trial(self, candidate: SafeCandidate, safe: bool, score: float, actual: float) -> None:
        trial = self.optimizer.record_trial(
            candidate=candidate,
            target_actual=self.target_actual_input.value(),
            actual=actual,
            score=score,
            safe=safe,
            message=self.last_message,
            dry_run=self.dry_run_check.isChecked(),
        )
        self._append_trial_row(trial)

    def _append_trial_row(self, trial: dict[str, object]) -> None:
        row = self.trial_table.rowCount()
        self.trial_table.insertRow(row)
        values = (
            trial["trial"],
            trial["channel"],
            f"{float(trial['candidate']):.3f}",
            f"+/-{float(trial['allowed_step']):.3f}",
            f"{float(trial['actual']):.3f}",
            f"{float(trial['error']):.3f}",
            "inf" if math.isinf(float(trial["score"])) else f"{float(trial['score']):.3f}",
            "yes" if trial["safe"] else "no",
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(Qt.AlignCenter)
            self.trial_table.setItem(row, column, item)

    def _refresh_candidate(self) -> None:
        if self.active_trial is not None:
            elapsed = 0.0 if self.trial_started_at is None else time.perf_counter() - self.trial_started_at
            self.candidate_label.setText(
                f"Running {CHANNEL_NAMES[self.active_trial.channel]} -> {self.active_trial.command:.3f} A "
                f"({elapsed:.1f}/{self.observe_seconds_input.value():.1f} s)"
            )
            return
        if self.pending_candidate is None:
            self.candidate_label.setText("Complete the safety checklist to prepare the first trial")
            return
        self.candidate_label.setText(
            f"Suggested {CHANNEL_NAMES[self.pending_candidate.channel]} command "
            f"{self.pending_candidate.command:.3f} A | error {self.pending_candidate.current_error:+.3f} A | "
            f"{self.pending_candidate.reason} | press Enter to approve"
        )

    def _refresh_status(self) -> None:
        channel = CHANNEL_NAMES[self.selected_index]
        actual = self.actual_values[self.selected_index]
        command = self.command_values[self.selected_index]
        target = self.target_actual_input.value()
        error = target - actual
        adaptive_range = (
            self.pending_candidate.allowed_step
            if self.pending_candidate is not None
            else self.optimizer.adaptive_step(
                current_error=error,
                max_step=self.max_step_input.value(),
                min_step=self.min_step_input.value(),
            )
        )
        state = "running" if self.active_trial is not None else "idle"
        self.run_status_label.setText(
            f"{channel} {state} | actual {actual:.2f} A | target {target:.2f} A | "
            f"error {error:+.2f} A | next range +/-{adaptive_range:.2f} A"
        )
        connected = self.backend_available and self.backend_connection.lower() in {"connected", "listening"}
        self.connection_dot.setProperty("connected", connected)
        self.connection_dot.style().unpolish(self.connection_dot)
        self.connection_dot.style().polish(self.connection_dot)
        self.connection_label.setText(f"Connection\n{self.backend_connection}")
        self.destination_label.setText(f"Destination\n{self.backend_destination}")
        self.safety_label.setText(
            "Safety\n"
            f"{self.last_message} | dry run {self.dry_run_check.isChecked()} | "
            f"automated {self.automated_trials_check.isChecked()} | "
            f"auto approve {self.auto_approve_check.isChecked()} | armed {self.armed} | "
            f"last apply {self.last_apply_ok} | packets {self.backend_packets}"
        )
        self._refresh_candidate()

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
