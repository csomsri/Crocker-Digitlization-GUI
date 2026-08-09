from __future__ import annotations

import csv
import math
import time
from concurrent.futures import Future, ThreadPoolExecutor
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from python.app.PageShell import DetailPage
from python.app.widgets.MagneticFieldWidgets import (
    CHANNEL_NAMES,
    MAX_GAUGE_VALUE,
    SimulatedActual,
    TimeDomainPlot,
    clamp,
)
from source.Python.PID_Tuner.bayesion_optimization.bayesian_optimization import (
    BotorchPidOptimizer,
    PidGainCandidate,
    PidTrialResult,
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
        back_button = self.findChild(QPushButton, "backButton")
        if back_button is not None:
            back_button.setObjectName("pidBackButton")
            back_button.setText("Back to Automation")

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
        self.tuning_optimizer: BotorchPidOptimizer | None = None
        self.tuning_candidate: PidGainCandidate | None = None
        self.tuning_trial_candidate: PidGainCandidate | None = None
        self.tuning_samples: list[tuple[float, float, float, float]] = []
        self.tuning_results: list[PidTrialResult] = []
        self.tuning_session_active = False
        self.tuning_proposal: Future[list[PidGainCandidate]] | None = None
        self.tuning_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pid-bo")
        self.log_path = Path(__file__).resolve().parents[3] / "logs" / "pid_commands.csv"

        self._start_backend()

        _, workspace = self.add_workspace()
        workspace.setContentsMargins(12, 4, 12, 6)

        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("pidPageStack")
        workspace.addWidget(self.page_stack, 1)

        control_page = QWidget()
        control_page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(control_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.control_panel = self._build_control_panel()
        layout.addWidget(self.control_panel, 0, Qt.AlignTop)
        self.time_plot = TimeDomainPlot()
        self.time_plot.setObjectName("pidVisualizationViewport")
        self.time_plot.setMinimumHeight(260)
        self.time_plot.setMaximumHeight(16777215)
        self.time_plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.time_plot, 1)
        layout.addWidget(self._build_status_panel())

        self.tuner_page = self._build_tuner_page()
        self.page_stack.addWidget(control_page)
        self.page_stack.addWidget(self.tuner_page)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick_feedback)
        self.timer.start(125)
        self._refresh_status()

    def _build_control_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("pidPanel")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout = QGridLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(10)
        for row in range(7):
            layout.setRowStretch(row, 0)

        title_panel = QFrame()
        title_panel.setObjectName("pidControlTitlePanel")
        title_layout = QVBoxLayout(title_panel)
        title_layout.setContentsMargins(10, 5, 10, 5)
        title_layout.setSpacing(1)
        title = QLabel("PID CHANNEL CONTROL")
        title.setObjectName("pidControlTitle")
        subtitle = QLabel("REAL-TIME CLOSED-LOOP CONTROL")
        subtitle.setObjectName("pidControlSubtitle")
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)
        controller_status = QFrame()
        controller_status.setObjectName("pidControllerState")
        controller_status_layout = QHBoxLayout(controller_status)
        controller_status_layout.setContentsMargins(6, 4, 6, 4)
        controller_status_layout.setSpacing(6)
        self.pid_status_values: dict[str, QLabel] = {}
        for name in ("Channel", "State", "Error", "Command"):
            value = QLabel(f"{name}\n—")
            value.setObjectName("pidControllerMetric")
            value.setAlignment(Qt.AlignCenter)
            self.pid_status_values[name] = value
            controller_status_layout.addWidget(value, 1)
        self.open_tuner_button = QPushButton("Optimized Tuner")
        self.open_tuner_button.setObjectName("pidTunerOpen")
        self.open_tuner_button.setCursor(Qt.PointingHandCursor)
        self.open_tuner_button.clicked.connect(self._show_tuner)
        layout.addWidget(title_panel, 0, 0)
        layout.addWidget(controller_status, 0, 1, 1, 2)
        layout.addWidget(self.open_tuner_button, 0, 3)

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

    def _build_tuner_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pidTunerPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("PID Gain Tuning")
        title.setObjectName("pidTitle")
        subtitle = QLabel("Bayesian optimization-assisted commissioning")
        subtitle.setObjectName("pidTunerSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        heading.addLayout(title_box)
        heading.addStretch(1)
        self.close_tuner_button = QPushButton("Back to PID Control")
        self.close_tuner_button.setObjectName("pidTunerBack")
        self.close_tuner_button.setCursor(Qt.PointingHandCursor)
        self.close_tuner_button.clicked.connect(self._show_pid_control)
        heading.addWidget(self.close_tuner_button)
        outer.addLayout(heading)

        configuration = QFrame()
        configuration.setObjectName("pidPanel")
        grid = QGridLayout(configuration)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self.tuner_channel = QComboBox()
        self.tuner_channel.setObjectName("pidTunerChannel")
        self.tuner_channel.addItems(CHANNEL_NAMES)
        self.tuner_target = self._make_spinbox(0.0, MAX_GAUGE_VALUE, 0.1, " A")
        self.tuner_trials = QSpinBox()
        self.tuner_trials.setObjectName("pidSpin")
        self.tuner_trials.setRange(3, 200)
        self.tuner_trials.setValue(20)
        self.tuner_duration = self._make_spinbox(0.5, 300.0, 0.5, " s")
        self.tuner_duration.setValue(10.0)
        self.tuner_profile = QComboBox()
        self.tuner_profile.setObjectName("pidTunerProfile")
        self.tuner_profile.addItems(
            ["Balanced", "Fast response", "Minimal overshoot", "High precision", "Low control effort"]
        )

        primary_fields = (
            ("Controlled channel", self.tuner_channel),
            ("Trial target", self.tuner_target),
            ("Trial budget", self.tuner_trials),
            ("Trial duration", self.tuner_duration),
            ("Performance profile", self.tuner_profile),
        )
        for column, (text, widget) in enumerate(primary_fields):
            label = QLabel(text)
            label.setObjectName("pidFieldLabel")
            grid.addWidget(label, 0, column)
            grid.addWidget(widget, 1, column)

        self.tuner_gain_bounds: dict[str, tuple[QDoubleSpinBox, QDoubleSpinBox]] = {}
        self.tuner_bound_summaries: dict[str, QLabel] = {}
        defaults = {"Kp": (0.0, 5.0), "Ki": (0.0, 2.0), "Kd": (0.0, 1.0)}
        bounds_panel = QFrame()
        bounds_panel.setObjectName("pidBoundsPanel")
        bounds_layout = QGridLayout(bounds_panel)
        bounds_layout.setContentsMargins(10, 8, 10, 8)
        bounds_layout.setHorizontalSpacing(10)
        bounds_layout.setVerticalSpacing(5)
        bounds_title = QLabel("Safe gain search bounds")
        bounds_title.setObjectName("pidSectionTitle")
        bounds_layout.addWidget(bounds_title, 0, 0, 1, 2)
        self.reset_bounds_button = QPushButton("Reset Gain Bounds")
        self.reset_bounds_button.setObjectName("pidCompactAction")
        self.reset_bounds_button.clicked.connect(self._reset_tuner_bounds)
        bounds_layout.addWidget(self.reset_bounds_button, 0, 2, Qt.AlignRight)
        for column, gain in enumerate(("Kp", "Ki", "Kd")):
            minimum = self._make_spinbox(0.0, 100.0, 0.01)
            maximum = self._make_spinbox(0.0, 100.0, 0.01)
            minimum.setValue(defaults[gain][0])
            maximum.setValue(defaults[gain][1])
            self.tuner_gain_bounds[gain] = (minimum, maximum)
            gain_card = QFrame()
            gain_card.setObjectName("pidBoundCard")
            gain_layout = QVBoxLayout(gain_card)
            gain_layout.setContentsMargins(8, 5, 8, 7)
            gain_layout.setSpacing(4)
            gain_title = QLabel(gain)
            gain_title.setObjectName("pidBoundTitle")
            gain_layout.addWidget(gain_title)
            summary = QLabel()
            summary.setObjectName("pidBoundSummary")
            summary.setAlignment(Qt.AlignCenter)
            self.tuner_bound_summaries[gain] = summary
            gain_layout.addWidget(summary, 1)
            range_row = QHBoxLayout()
            range_row.setSpacing(6)
            for text, control in (("Minimum", minimum), ("Maximum", maximum)):
                field = QVBoxLayout()
                field.setSpacing(2)
                label = QLabel(text)
                label.setObjectName("pidBoundLabel")
                field.addWidget(label)
                field.addWidget(control)
                range_row.addLayout(field, 1)
            gain_layout.addLayout(range_row)
            bounds_layout.addWidget(gain_card, 1, column)
            minimum.valueChanged.connect(self._refresh_bound_summaries)
            maximum.valueChanged.connect(self._refresh_bound_summaries)
        grid.addWidget(bounds_panel, 2, 0, 1, 3)
        self._refresh_bound_summaries()

        self.tuner_safety_profile = QComboBox()
        self.tuner_safety_profile.setObjectName("pidTunerSafetyProfile")
        self.tuner_safety_profile.addItems(["Simulation / dry run", "Approved hardware profile"])

        candidate_panel = QFrame()
        candidate_panel.setObjectName("pidCandidatePanel")
        candidate_layout = QVBoxLayout(candidate_panel)
        candidate_layout.setContentsMargins(10, 8, 10, 8)
        candidate_layout.setSpacing(6)
        safety_row = QHBoxLayout()
        safety_label = QLabel("Safety profile")
        safety_label.setObjectName("pidSectionTitle")
        safety_row.addWidget(safety_label)
        safety_row.addWidget(self.tuner_safety_profile, 1)
        candidate_layout.addLayout(safety_row)
        self.tuner_status = QLabel("Not started. Configure and review the safe bounds.")
        self.tuner_status.setObjectName("pidTunerStatus")
        self.tuner_status.setWordWrap(True)
        candidate_layout.addWidget(self.tuner_status)
        progress_row = QHBoxLayout()
        progress_row.setSpacing(8)
        self.tuner_progress_values: dict[str, QLabel] = {}
        for name in ("Trial", "State", "Time", "Error"):
            value = QLabel(f"{name}\n—")
            value.setObjectName("pidStatusValue")
            value.setAlignment(Qt.AlignCenter)
            value.setMinimumWidth(82)
            self.tuner_progress_values[name] = value
            progress_row.addWidget(value)
        candidate_layout.addLayout(progress_row)
        gain_row = QHBoxLayout()
        gain_row.setSpacing(8)
        self.tuner_candidate_values: dict[str, QLabel] = {}
        for gain in ("Kp", "Ki", "Kd"):
            value = QLabel(f"{gain}\n—")
            value.setObjectName("pidCandidateValue")
            value.setAlignment(Qt.AlignCenter)
            value.setMinimumWidth(82)
            self.tuner_candidate_values[gain] = value
            gain_row.addWidget(value)
        candidate_layout.addLayout(gain_row)
        grid.addWidget(candidate_panel, 2, 3, 1, 2)
        outer.addWidget(configuration)

        self.tuner_viewport = QFrame()
        self.tuner_viewport.setObjectName("pidTunerViewport")
        self.tuner_viewport.setMinimumHeight(280)
        self.tuner_viewport.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tuner_viewport.setAccessibleName("Optimized tuner visualization viewport")
        outer.addWidget(self.tuner_viewport, 1)

        actions = QHBoxLayout()
        self.prepare_tuning_button = QPushButton("Prepare Tuning Session")
        self.prepare_tuning_button.setObjectName("fieldAction")
        self.prepare_tuning_button.clicked.connect(self._prepare_tuning_session)
        self.run_tuning_trial_button = QPushButton("Run Proposed Trial")
        self.run_tuning_trial_button.setObjectName("pidEnable")
        self.run_tuning_trial_button.setEnabled(False)
        self.run_tuning_trial_button.clicked.connect(self._run_tuning_trial)
        self.stop_tuning_button = QPushButton("Stop Tuning")
        self.stop_tuning_button.setObjectName("pidStop")
        self.stop_tuning_button.setEnabled(False)
        self.stop_tuning_button.clicked.connect(self._stop_tuning_session)
        self.review_history_button = QPushButton("Trial History")
        self.review_history_button.setObjectName("fieldAction")
        self.review_history_button.setEnabled(False)
        self.review_history_button.clicked.connect(self._show_tuning_history)
        self.approve_gains_button = QPushButton("Validate and Approve Best Gains")
        self.approve_gains_button.setObjectName("fieldAction")
        self.approve_gains_button.setEnabled(False)
        self.approve_gains_button.clicked.connect(self._validate_best_gains)
        self.apply_tuned_gains_button = QPushButton("Apply Settings to PID")
        self.apply_tuned_gains_button.setObjectName("pidApplyTunedGains")
        self.apply_tuned_gains_button.setToolTip(
            "Apply the validated gains to the PID Control page"
        )
        self.apply_tuned_gains_button.setEnabled(False)
        self.apply_tuned_gains_button.clicked.connect(self._apply_tuned_gains)
        actions.addWidget(self.prepare_tuning_button)
        actions.addWidget(self.run_tuning_trial_button)
        actions.addWidget(self.stop_tuning_button)
        actions.addWidget(self.review_history_button)
        actions.addStretch(1)
        actions.addWidget(self.approve_gains_button)
        actions.addWidget(self.apply_tuned_gains_button)
        outer.addLayout(actions)
        return page

    def _show_tuner(self) -> None:
        self.tuner_channel.setCurrentIndex(self.selected_index)
        self.tuner_target.setValue(self.setpoint_input.value())
        current_gains = {
            "Kp": self.kp_input.value(),
            "Ki": self.ki_input.value(),
            "Kd": self.kd_input.value(),
        }
        for gain, value in current_gains.items():
            minimum, maximum = self.tuner_gain_bounds[gain]
            if value < minimum.value():
                minimum.setValue(value)
            if value > maximum.value():
                maximum.setValue(value)
        self.page_stack.setCurrentWidget(self.tuner_page)

    def _show_pid_control(self) -> None:
        self.page_stack.setCurrentIndex(0)

    def _reset_tuner_bounds(self) -> None:
        defaults = {"Kp": (0.0, 5.0), "Ki": (0.0, 2.0), "Kd": (0.0, 1.0)}
        for gain, (minimum, maximum) in self.tuner_gain_bounds.items():
            minimum.setValue(defaults[gain][0])
            maximum.setValue(defaults[gain][1])
        self.tuner_status.setText("The recommended simulation gain bounds have been restored.")

    def _refresh_bound_summaries(self, _value: float = 0.0) -> None:
        for gain, (minimum, maximum) in self.tuner_gain_bounds.items():
            summary = self.tuner_bound_summaries.get(gain)
            if summary is not None:
                summary.setText(f"{minimum.value():.3f}  ≤  {gain}  ≤  {maximum.value():.3f}")

    def _set_candidate_values(self, candidate: PidGainCandidate | None) -> None:
        values = None if candidate is None else {
            "Kp": candidate.kp,
            "Ki": candidate.ki,
            "Kd": candidate.kd,
        }
        for gain, label in self.tuner_candidate_values.items():
            label.setText(f"{gain}\n—" if values is None else f"{gain}\n{values[gain]:.4f}")

    def _set_tuning_progress(
        self,
        *,
        trial: str = "—",
        state: str = "—",
        elapsed: str = "—",
        error: str = "—",
    ) -> None:
        values = {"Trial": trial, "State": state, "Time": elapsed, "Error": error}
        for name, value in values.items():
            self.tuner_progress_values[name].setText(f"{name}\n{value}")

    def _prepare_tuning_session(self) -> None:
        if self.backend_mode != "simulation":
            self.tuner_status.setText(
                "Hardware tuning is unavailable until a calibrated allocation profile is loaded."
            )
            return
        if not self.backend_available or self.backend is None:
            self.tuner_status.setText("Tuning cannot start because the control backend is unavailable.")
            return
        bounds = {
            gain: (minimum.value(), maximum.value())
            for gain, (minimum, maximum) in self.tuner_gain_bounds.items()
        }
        if any(lower >= upper for lower, upper in bounds.values()):
            self.tuner_status.setText("Each gain minimum must be lower than its maximum.")
            return
        self._stop_pid("Starting tuning session")
        self.tuning_optimizer = BotorchPidOptimizer(
            bounds["Kp"], bounds["Ki"], bounds["Kd"], use_cuda=False
        )
        self.tuning_candidate = None
        self._set_candidate_values(None)
        self.tuning_trial_candidate = None
        self.tuning_samples.clear()
        self.tuning_results.clear()
        self.review_history_button.setEnabled(False)
        self._set_tuning_progress(state="Preparing")
        self.tuning_session_active = True
        self.prepare_tuning_button.setEnabled(False)
        self.stop_tuning_button.setEnabled(True)
        self.approve_gains_button.setEnabled(False)
        self.apply_tuned_gains_button.setEnabled(False)
        self.tuner_status.setText("BoTorch is preparing the next gain candidate.")
        self._request_tuning_candidate()

    def _request_tuning_candidate(self) -> None:
        if self.tuning_optimizer is None or not self.tuning_session_active:
            return
        if len(self.tuning_results) >= self.tuner_trials.value():
            self._finish_tuning_session()
            return
        self.tuning_candidate = None
        self.run_tuning_trial_button.setEnabled(False)
        self.tuning_proposal = self.tuning_executor.submit(
            self.tuning_optimizer.propose_batch, 1
        )

    def _poll_tuning_workflow(self) -> None:
        proposal = self.tuning_proposal
        if proposal is not None and proposal.done():
            self.tuning_proposal = None
            if not self.tuning_session_active:
                return
            try:
                self.tuning_candidate = proposal.result()[0]
            except Exception as exc:
                self.tuner_status.setText(f"Candidate generation failed: {exc}")
                self._stop_tuning_session()
                return
            candidate = self.tuning_candidate
            self._set_candidate_values(candidate)
            self.tuner_status.setText(
                "Review the proposed gains before starting the trial."
            )
            self._set_tuning_progress(
                trial=f"{len(self.tuning_results) + 1} of {self.tuner_trials.value()}",
                state="Ready",
            )
            self.run_tuning_trial_button.setEnabled(True)

        if self.tuning_trial_candidate is None or self.backend is None:
            return
        try:
            status = self.backend.PidTrialStatus()
        except Exception as exc:
            self.tuner_status.setText(f"The trial status could not be read: {exc}")
            self._stop_tuning_session()
            return
        state = str(status["state"])
        elapsed = float(status["elapsed_seconds"])
        measured = float(status["measured_field"])
        error = float(status["error"])
        effort = abs(float(status["control_output"]))
        self.tuning_samples.append((elapsed, measured, error, effort))
        self.tuner_status.setText("PID response trial in progress.")
        self._set_tuning_progress(
            trial=f"{len(self.tuning_results) + 1} of {self.tuner_trials.value()}",
            state=state,
            elapsed=f"{elapsed:.1f} / {self.tuner_duration.value():.1f} s",
            error=f"{error:+.3f}",
        )
        if state == "Completed":
            self._complete_tuning_trial(True)
        elif state in {"Faulted", "Stopped"}:
            self._complete_tuning_trial(False)

    def _run_tuning_trial(self) -> None:
        if self.tuning_candidate is None or self.backend is None:
            return
        channel = self.tuner_channel.currentIndex()
        allocation = [0.0 for _ in CHANNEL_NAMES]
        allocation[channel] = 1.0
        minimum = min(self.min_output_input.value(), self.max_output_input.value())
        maximum = max(self.min_output_input.value(), self.max_output_input.value())
        candidate = self.tuning_candidate
        config = {
            "measurement_channel": channel,
            "setpoint": self.tuner_target.value(),
            "kp": candidate.kp,
            "ki": candidate.ki,
            "kd": candidate.kd,
            "update_rate_hz": 20.0,
            "duration_seconds": self.tuner_duration.value(),
            "telemetry_timeout_seconds": 1.0,
            "allocation": allocation,
            "command_bias": list(self.command_values),
            "minimum_command": [minimum for _ in CHANNEL_NAMES],
            "maximum_command": [maximum for _ in CHANNEL_NAMES],
            "maximum_slew_per_second": [self.max_step_input.value() * 8.0 for _ in CHANNEL_NAMES],
            "allocation_calibrated": False,
            "hardware_armed": True,
            "dry_run": False,
        }
        try:
            self.backend.StartPidTrial(config)
        except Exception as exc:
            self.tuner_status.setText(f"The trial could not be started: {exc}")
            return
        self.tuning_trial_candidate = candidate
        self.tuning_candidate = None
        self.tuning_samples.clear()
        self.run_tuning_trial_button.setEnabled(False)
        self.stop_tuning_button.setEnabled(True)

    def _complete_tuning_trial(self, safe: bool) -> None:
        candidate = self.tuning_trial_candidate
        if candidate is None or self.tuning_optimizer is None:
            return
        if self.backend is not None:
            self.backend.StopPidTrial(True)
        target = self.tuner_target.value()
        samples = self.tuning_samples or [(0.0, self.actual_values[self.tuner_channel.currentIndex()], target, 0.0)]
        errors = [abs(sample[2]) for sample in samples]
        tolerance = max(0.01 * max(abs(target), 1.0), 0.1)
        settling_time = samples[-1][0]
        for index, sample in enumerate(samples):
            if all(abs(later[2]) <= tolerance for later in samples[index:]):
                settling_time = sample[0]
                break
        overshoot = max(0.0, max(sample[1] for sample in samples) - target)
        tail_size = max(1, len(errors) // 5)
        steady_state_error = sum(errors[-tail_size:]) / tail_size
        control_effort = 0.0
        for previous, current in zip(samples, samples[1:]):
            control_effort += current[3] * max(0.0, current[0] - previous[0])
        weights = {
            "Balanced": (1.0, 2.0, 4.0, 0.01),
            "Fast response": (3.0, 1.0, 3.0, 0.01),
            "Minimal overshoot": (1.0, 6.0, 3.0, 0.01),
            "High precision": (1.0, 2.0, 8.0, 0.01),
            "Low control effort": (1.0, 2.0, 4.0, 0.08),
        }[self.tuner_profile.currentText()]
        score = (
            weights[0] * settling_time
            + weights[1] * overshoot
            + weights[2] * steady_state_error
            + weights[3] * control_effort
        )
        if not safe or not math.isfinite(score):
            safe = False
            score = 1.0e12
        result = PidTrialResult(
            candidate, score, settling_time, overshoot,
            steady_state_error, control_effort, safe,
        )
        self.tuning_optimizer.record_results([result])
        self.tuning_results.append(result)
        self.review_history_button.setEnabled(True)
        self.tuning_trial_candidate = None
        best = self.tuning_optimizer.best_result
        best_text = "none" if best is None else f"{best.score:.4f}"
        self.tuner_status.setText(
            f"Trial recorded. Cost: {score:.4f}. Best cost: {best_text}. Lower is better."
        )
        self._set_tuning_progress(
            trial=f"{len(self.tuning_results)} of {self.tuner_trials.value()}",
            state="Recorded" if safe else "Unsafe",
            elapsed=f"{samples[-1][0]:.1f} s",
            error=f"{steady_state_error:.3f}",
        )
        self._request_tuning_candidate()

    def _finish_tuning_session(self) -> None:
        self.tuning_session_active = False
        self.stop_tuning_button.setEnabled(False)
        self.prepare_tuning_button.setEnabled(True)
        best = self.tuning_optimizer.best_result if self.tuning_optimizer else None
        if best is None:
            self.tuner_status.setText("Tuning is complete, but no safe gain result was found.")
            return
        self.approve_gains_button.setEnabled(True)
        self.tuner_status.setText(
            f"Tuning is complete. The best observed cost is {best.score:.4f}."
        )
        self._set_candidate_values(best.candidate)

    def _validate_best_gains(self) -> None:
        best = self.tuning_optimizer.best_result if self.tuning_optimizer else None
        if best is None:
            return
        self.apply_tuned_gains_button.setProperty("approvedCandidate", best.candidate)
        self.apply_tuned_gains_button.setEnabled(True)
        self.tuner_status.setText(
            "The displayed gains have been validated for simulation and are ready to apply."
        )
        self._set_candidate_values(best.candidate)

    def _show_tuning_history(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("PID Gain Tuning Trial History")
        dialog.resize(980, 420)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(self.tuning_results), 10)
        table.setHorizontalHeaderLabels(
            [
                "Trial", "Kp", "Ki", "Kd", "Cost", "Settling",
                "Overshoot", "Steady Error", "Effort", "Safe",
            ]
        )
        for row, result in enumerate(self.tuning_results):
            values = (
                row + 1, result.candidate.kp, result.candidate.ki,
                result.candidate.kd, result.score, result.settling_time,
                result.overshoot, result.steady_state_error,
                result.control_effort, "yes" if result.safe else "no",
            )
            for column, value in enumerate(values):
                text = f"{value:.4f}" if isinstance(value, float) else str(value)
                table.setItem(row, column, QTableWidgetItem(text))
        layout.addWidget(table)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, 0, Qt.AlignRight)
        dialog.exec()

    def _apply_tuned_gains(self) -> None:
        candidate = self.apply_tuned_gains_button.property("approvedCandidate")
        if not isinstance(candidate, PidGainCandidate):
            return
        self.selected_index = self.tuner_channel.currentIndex()
        self.channel_select.setCurrentIndex(self.selected_index)
        self.setpoint_input.setValue(self.tuner_target.value())
        self.kp_input.setValue(candidate.kp)
        self.ki_input.setValue(candidate.ki)
        self.kd_input.setValue(candidate.kd)
        self._show_pid_control()
        self.last_safety_message = "Validated tuning settings applied; PID remains disabled"
        self._refresh_status()

    def _stop_tuning_session(self) -> None:
        if self.backend is not None and self.tuning_trial_candidate is not None:
            self.backend.StopPidTrial(True)
        self.tuning_session_active = False
        if self.tuning_proposal is not None:
            self.tuning_proposal.cancel()
            self.tuning_proposal = None
        self.tuning_trial_candidate = None
        self.tuning_candidate = None
        self.run_tuning_trial_button.setEnabled(False)
        self.stop_tuning_button.setEnabled(False)
        self.prepare_tuning_button.setEnabled(True)
        best = self.tuning_optimizer.best_result if self.tuning_optimizer else None
        self.approve_gains_button.setEnabled(best is not None)
        suffix = "no safe result" if best is None else f"best cost {best.score:.4f} available"
        self.tuner_status.setText(
            f"Tuning stopped and the allocated output was disabled. Result: {suffix}."
        )

    def _build_status_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("fieldBackendStatus")
        panel.setFixedHeight(64)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(12)

        self.connection_dot = QLabel()
        self.connection_dot.setObjectName("fieldStatusDot")
        self.connection_dot.setProperty("connected", False)
        self.connection_dot.setFixedSize(18, 18)
        self.connection_label = QLabel()
        self.connection_label.setObjectName("pidStatusCard")
        self.destination_label = QLabel()
        self.destination_label.setObjectName("pidStatusCard")
        self.command_label = QLabel()
        self.command_label.setObjectName("pidStatusCard")
        self.safety_label = QLabel()
        self.safety_label.setObjectName("pidStatusCard")

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
        self._poll_tuning_workflow()
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
        status_values = {
            "Channel": channel,
            "State": state.title(),
            "Error": f"{error:+.2f} A",
            "Command": f"{command:.2f} A",
        }
        for name, value in status_values.items():
            self.pid_status_values[name].setText(f"{name.upper()}\n{value}")

        connected = self.backend_available and self.backend_connection.lower() in {"connected", "listening"}
        self.connection_dot.setProperty("connected", connected)
        self.connection_dot.style().unpolish(self.connection_dot)
        self.connection_dot.style().polish(self.connection_dot)
        self.connection_label.setText(f"CONNECTION\n{self.backend_connection}")
        self.destination_label.setText(f"DESTINATION\n{self.backend_destination}")
        self.command_label.setText(f"CHANNEL\n{channel}    Packets {self.backend_packets}")
        self.safety_label.setText(
            "SAFETY\n"
            f"{self.last_safety_message}    "
            f"Apply {'OK' if self.last_apply_ok else 'Pending'}    "
            f"Mode {'Dry run' if self.dry_run_check.isChecked() else 'Live'}    "
            f"Output {'On' if self.telemetry_on[self.selected_index] else 'Off'}    "
            f"Control {'Enabled' if self.telemetry_enabled[self.selected_index] else 'Disabled'}"
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
        self._stop_tuning_session()
        self.tuning_executor.shutdown(wait=False, cancel_futures=True)
        if self.backend is not None:
            try:
                self.backend.Stop()
            except Exception:
                pass
        self.backend_available = False
