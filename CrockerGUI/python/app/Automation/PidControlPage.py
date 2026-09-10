from __future__ import annotations

import csv
import math
import time
from concurrent.futures import Future, ThreadPoolExecutor
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QAbstractItemView,
    QHeaderView,
    QDoubleSpinBox,
    QDialog,
    QFileDialog,
    QFrame,
    QFormLayout,
    QScrollArea,
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

from source.Python.Optimization.trial_metrics import evaluate_trial, trial_cost
from python.app.Automation.RunMetrics import RunMetrics
from python.app.PageShell import DetailPage
from python.app.widgets.DialogTitleBar import DialogTitleBar
from python.app.widgets.PidDialog import setup_pid_dialog
from python.app.widgets.ScreenSafeComboBox import ScreenSafeComboBox as QComboBox
from python.app.Automation.SurrogatePlotWidget import SurrogatePlotWidget
from python.app.widgets.MagneticFieldWidgets import (
    CHANNEL_NAMES,
    MAX_GAUGE_VALUE,
    SimulatedActual,
    clamp,
    make_time_domain_plot,
)
from source.Python.Optimization.pid_gain_adapter import (
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
        shared_backend: object | None = None,
        tuning_enabled: bool | None = None,
        manage_backend: bool = True,
        simulation_mode: str | None = None,
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
        self.simulation_mode = simulation_mode
        self.zmq_endpoint = zmq_endpoint
        self.tuning_enabled = (
            self.backend_mode == "simulation"
            if tuning_enabled is None
            else bool(tuning_enabled)
        )
        self.manage_backend = manage_backend
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
        self._service_pid_active = False
        self._tuning_controller_config = {"controller_kind": "conventional"}
        self.pid_integral = 0.0
        self.pid_previous_error: float | None = None
        self.pid_previous_time: float | None = None
        self.pid_output_bias = 0.0
        self.backend = shared_backend
        self.owns_backend = False
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
        self._oscillation_stopped = False
        self.tuning_results: list[PidTrialResult] = []
        self.tuning_session_active = False
        self.tuning_auto_run = False
        self.tuning_proposal: Future[list[PidGainCandidate]] | None = None
        self.tuning_surrogate_grid: dict | None = None
        self.tuning_surrogate_proposal: Future[dict] | None = None
        self.tuning_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pid-bo")
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
        self._organize_control_panel()
        layout.addWidget(self.control_panel, 0, Qt.AlignTop)
        self.run_metrics = RunMetrics(self.log_path.parent / 'pid_runs')
        layout.addWidget(self.run_metrics)
        self.time_plot = make_time_domain_plot()
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
        for name in ("Channel", "State", "Error", "Actual"):
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
        # Keep Qt's native popup.  The application-wide animation polish swaps
        # combo views, which can leave this frequently refreshed page with a
        # popup that displays choices but does not commit mouse selections.
        self.channel_select.setProperty("stablePopup", True)
        self.channel_select.addItems(CHANNEL_NAMES)
        self.channel_select.currentIndexChanged.connect(self._set_channel)
        channel_selector = self.channel_select

        self.enable_button = QPushButton("Enable PID")
        self.enable_button.setObjectName("pidEnable")
        self.enable_button.setCheckable(True)
        self.enable_button.setEnabled(False)
        self.enable_button.toggled.connect(self._set_pid_enabled)

        self.arm_button = QPushButton("Arm PID")
        self.arm_button.setObjectName("pidArm")
        self.arm_button.setCheckable(True)
        self.arm_button.toggled.connect(self._set_armed)
        layout.addWidget(channel_selector, 1, 0, 1, 2)
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
        self.cpp_nla_panel = QWidget()
        nla_layout = QGridLayout(self.cpp_nla_panel)
        nla_layout.setContentsMargins(0, 0, 0, 0)
        self.controller_kind_input = QComboBox()
        self.controller_kind_input.addItem("Conventional PID", "conventional")
        self.controller_kind_input.addItem("C++ NLAPID", "nla")
        self.controller_kind_input.setCurrentIndex(1)
        self.nla_deadband_input = self._make_spinbox(0, 100, 0.01, " A")
        self.nla_deadband_input.setValue(0.05)
        self.nla_direction_input = QComboBox()
        self.nla_direction_input.addItem("Increase first", 1)
        self.nla_direction_input.addItem("Decrease first", -1)
        self.nla_window_input = self._make_spinbox(0.05, 60, 0.05, " s")
        self.nla_window_input.setValue(1.0)
        self.nla_tolerance_input = self._make_spinbox(0, 100, 0.01, " A")
        self.nla_tolerance_input.setValue(0.05)
        self.nla_memory_input = self._make_spinbox(0.1, 120, 0.5, " s")
        self.nla_memory_input.setValue(20.0)
        for index, (label, widget) in enumerate((
            ("Controller", self.controller_kind_input), ("NLA deadband", self.nla_deadband_input),
            ("NLA initial direction", self.nla_direction_input), ("NLA direction window", self.nla_window_input),
            ("NLA trend tolerance", self.nla_tolerance_input), ("NLA integral memory", self.nla_memory_input),
        )):
            row, column = divmod(index, 6)
            field_label = QLabel(label)
            field_label.setObjectName("pidFieldLabel")
            nla_layout.addWidget(field_label, row * 2, column)
            nla_layout.addWidget(widget, row * 2 + 1, column)
        self.cpp_nla_status = QLabel("C++ NLAPID ready")
        self.cpp_nla_status.setWordWrap(True)
        self.cpp_nla_status.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        nla_layout.addWidget(self.cpp_nla_status, 2, 0, 1, 6)
        self.controller_kind_input.currentIndexChanged.connect(self._controller_kind_changed)
        layout.addWidget(self.cpp_nla_panel, 7, 0, 1, 4)
        return panel

    def _organize_control_panel(self):
        grid = self.control_panel.layout()
        details = QWidget()
        details.setObjectName('pidSettingsContents')
        details.setStyleSheet('QWidget#pidSettingsContents { background: #101a29; }')
        detail_grid = QVBoxLayout(details)
        detail_grid.setContentsMargins(0, 0, 0, 0)
        detail_grid.setSpacing(12)
        for index in reversed(range(grid.count())):
            row, col, rows, cols = grid.getItemPosition(index)
            if (row in (4, 5) and col < 3) or row >= 7:
                item = grid.takeAt(index)
                if item.widget():
                    item.widget().hide()
        fields = [('Minimum command', self.min_output_input),
                  ('Maximum command', self.max_output_input), ('Maximum step', self.max_step_input)]
        if hasattr(self, 'deadband_input'):
            fields += [('Deadband', self.deadband_input), ('Initial direction', self.direction_input),
                       ('Direction window', self.direction_interval_input),
                       ('Trend tolerance', self.trend_tolerance_input)]
            status = self.nla_status
        else:
            fields += [('Controller', self.controller_kind_input), ('Deadband', self.nla_deadband_input),
                       ('Initial direction', self.nla_direction_input), ('Direction window', self.nla_window_input),
                       ('Trend tolerance', self.nla_tolerance_input), ('Integral memory', self.nla_memory_input)]
            status = self.cpp_nla_status
        for heading, group_fields in [('OUTPUT LIMITS', fields[:3]), ('ADAPTIVE CONTROLLER', fields[3:])]:
            card = QFrame()
            card.setStyleSheet('QFrame { background: #142235; border-radius: 6px; }')
            group = QGridLayout(card)
            group.setContentsMargins(12, 10, 12, 12)
            group.setHorizontalSpacing(14)
            group.setVerticalSpacing(6)
            title = QLabel(heading)
            title.setStyleSheet('color: #91aacb; font-size: 11px; font-weight: 600;')
            group.addWidget(title, 0, 0, 1, 2)
            for index, (name, widget) in enumerate(group_fields):
                row, column = divmod(index, 2)
                group.addWidget(QLabel(name), row*2+1, column)
                widget.setFixedHeight(36)
                group.addWidget(widget, row*2+2, column)
                widget.show()
            group.setColumnStretch(0, 1)
            group.setColumnStretch(1, 1)
            detail_grid.addWidget(card)
        detail_grid.addWidget(status)
        detail_grid.addStretch()
        status.show()
        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle('Controller settings and output limits')
        dialog_layout = setup_pid_dialog(self.settings_dialog, 'Controller Settings', window_controls=False)
        scroll = QScrollArea()
        scroll.setStyleSheet('QScrollArea { background: #101a29; border: none; }')
        scroll.setWidgetResizable(True)
        scroll.setWidget(details)
        dialog_layout.addWidget(scroll)
        close = QPushButton('Close')
        close.setFixedSize(100, 36)
        close.clicked.connect(self.settings_dialog.close)
        dialog_layout.addWidget(close, 0, Qt.AlignRight)
        outputs = QHBoxLayout()
        for widget in (self.output_on_check, self.control_enabled_check, self.dry_run_check):
            grid.removeWidget(widget)
            outputs.addWidget(widget)
        grid.addLayout(outputs, 4, 0, 1, 4)
        for index in range(grid.count()):
            row, col, rows, cols = grid.getItemPosition(index)
            if row == 6 and grid.itemAt(index).layout():
                item = grid.takeAt(index)
                grid.addLayout(item.layout(), 5, 0, 1, 4)
                break
        toggle = QPushButton('Controller settings and output limits…')
        def open_settings():
            available = self.screen().availableGeometry()
            self.settings_dialog.resize(min(680, available.width()-40), min(650, available.height()-80))
            self.settings_dialog.show()
            self.settings_dialog.raise_()
        toggle.clicked.connect(open_settings)
        grid.addWidget(toggle, 6, 0, 1, 4)

    def _cpp_nla_selected(self) -> bool:
        return self.controller_kind_input.currentData() == "nla"

    def _controller_config(self) -> dict:
        return {
            "controller_kind": self.controller_kind_input.currentData(),
            "nla_deadband": self.nla_deadband_input.value(),
            "nla_initial_direction": int(self.nla_direction_input.currentData()),
            "nla_direction_check_interval": self.nla_window_input.value(),
            "nla_trend_tolerance": self.nla_tolerance_input.value(),
            "nla_integral_memory_s": self.nla_memory_input.value(),
            "nla_output_max": self.max_step_input.value(),
        }

    def _controller_kind_changed(self, _index: int) -> None:
        if self.pid_enabled:
            self._stop_pid("Controller changed")
        if self.tuning_session_active:
            self._stop_tuning_session()
        self.apply_tuned_gains_button.setEnabled(False)
        self.approve_gains_button.setEnabled(False)
        self.apply_tuned_gains_button.setProperty("approvedCandidate", None)
        self.cpp_nla_status.setText(
            "C++ NLAPID selected. Optimized Tuner will tune this controller."
            if self._cpp_nla_selected() else "Conventional PID selected."
        )

    def _lock_controller_inputs(self, locked: bool) -> None:
        # These controls now live in the settings dialog, outside cpp_nla_panel.
        for widget in (self.controller_kind_input, self.nla_deadband_input,
                       self.nla_direction_input, self.nla_window_input,
                       self.nla_tolerance_input, self.nla_memory_input):
            widget.setEnabled(not locked)
        for widget in (self.cpp_nla_panel, self.channel_select, self.setpoint_input,
                       self.kp_input, self.ki_input, self.kd_input, self.min_output_input,
                       self.max_output_input, self.max_step_input, self.dry_run_check,
                       self.hold_button, self.zero_button):
            widget.setEnabled(not locked)
        for name in ("tuner_channel", "tuner_target", "tuner_trials", "tuner_duration", "tuner_profile",
                     "smoke2_preset_button"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setEnabled(not locked)
        for bounds in getattr(self, "tuner_gain_bounds", {}).values():
            for widget in bounds:
                widget.setEnabled(not locked)

    def _start_service_nla(self) -> None:
        if not self._is_safe_to_run():
            self._stop_pid(self.last_safety_message)
            return
        if self.backend is None or not self.backend_available:
            self._stop_pid("C++ NLAPID requires a connected ControlService")
            return
        index = self.selected_index
        allocation = [0.0 for _ in CHANNEL_NAMES]
        allocation[index] = 1.0
        lower, upper = sorted((self.min_output_input.value(), self.max_output_input.value()))
        config = {
            **self._controller_config(), "continuous": True,
            "measurement_channel": index, "setpoint": self.setpoint_input.value(),
            "kp": self.kp_input.value(), "ki": self.ki_input.value(), "kd": self.kd_input.value(),
            "update_rate_hz": 20.0, "duration_seconds": 1.0, "telemetry_timeout_seconds": 1.0,
            "allocation": allocation, "command_bias": list(self.command_values),
            "minimum_command": [lower] * len(CHANNEL_NAMES),
            "maximum_command": [upper] * len(CHANNEL_NAMES),
            "maximum_slew_per_second": [self.max_step_input.value() * 8.0] * len(CHANNEL_NAMES),
            "allocation_calibrated": False, "hardware_armed": self.armed,
            "dry_run": self.dry_run_check.isChecked(),
        }
        try:
            # Reject an older extension rather than silently running conventional PID.
            if not hasattr(CycloViz, "NLAPID"):
                raise RuntimeError("Rebuild CycloViz to enable C++ NLAPID")
            self.command_values[index] = float(self.backend.PendingCommand()[index]["target"])
            self.backend.StartPidTrial(config)
        except Exception as exc:
            self._stop_pid(f"NLA start failed: {exc}")
            return
        self._service_pid_active = self.pid_enabled = True
        self.run_metrics.start(self._run_metrics_config())
        self.enable_button.setText("Disable PID")
        self._lock_controller_inputs(True)
        self.last_safety_message = "C++ NLAPID active"
        self._refresh_status()

    def _poll_service_nla(self) -> None:
        try:
            status = self.backend.PidTrialStatus()
            if status["state"] != "Running":
                self._stop_pid(f"C++ NLA {status['state']}: {status['message']}")
                return
            if status["iterations"]:
                self.command_values[self.selected_index] = float(status["command_target"])
            result = status["nla"]
            self.cpp_nla_status.setText(
                f"C++ NLA | {result['error_trend']} | direction {result['direction']:+d} | "
                f"P {result['proportional']:.4g} I {result['integral']:.4g} D {result['derivative']:.4g} A/update | "
                f"calculation {status['calculation_us']:.1f} us"
            )
        except Exception as exc:
            self._stop_pid(f"NLA status failed: {exc}")

    def _build_tuner_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pidTunerPage")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName('pidTunerScroll')
        scroll.setStyleSheet('QScrollArea#pidTunerScroll { background: #0f172a; border: none; }')
        scroll.viewport().setStyleSheet('background: #0f172a;')
        content = QWidget()
        content.setObjectName('pidTunerScrollContents')
        content.setStyleSheet('QWidget#pidTunerScrollContents { background: #0f172a; }')
        scroll.setWidget(content)
        page_layout.addWidget(scroll, 1)
        outer = QVBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("PID Gain Tuning")
        title.setObjectName("pidTitle")
        subtitle = QLabel("Bayesian optimization-assisted commissioning — Conventional PID")
        self.tuner_engine_label = subtitle
        subtitle.setObjectName("pidTunerSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        heading.addLayout(title_box)
        heading.addStretch(1)
        self.smoke2_preset_button = QPushButton("Load smoke2 BO preset")
        self.smoke2_preset_button.setObjectName("pidCompactAction")
        self.smoke2_preset_button.setVisible(self.simulation_mode == "smoke2")
        self.smoke2_preset_button.clicked.connect(self._load_smoke2_preset)
        heading.addWidget(self.smoke2_preset_button)
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
        self.tuner_channel.setProperty("stablePopup", True)
        self.tuner_channel.addItems(CHANNEL_NAMES)
        if self.backend_mode != "simulation":
            for index in range(12, len(CHANNEL_NAMES)):
                self.tuner_channel.model().item(index).setEnabled(False)
        tuner_channel_selector = self.tuner_channel
        self.tuner_target = self._make_spinbox(0.0, MAX_GAUGE_VALUE, 0.1, " A")
        self.tuner_trials = QSpinBox()
        self.tuner_trials.setObjectName("pidSpin")
        self.tuner_trials.setRange(3, 200)
        self.tuner_trials.setValue(20)
        self.tuner_duration = self._make_spinbox(0.5, 300.0, 0.5, " s")
        self.tuner_duration.setValue(10.0)
        self.tuner_profile = QComboBox()
        self.tuner_profile.setObjectName("pidTunerProfile")
        # Keep Qt's native popup. Replacing the view while this stacked page is
        # being attached can produce a popup that paints but ignores clicks.
        self.tuner_profile.setProperty("stablePopup", True)
        self.tuner_profile.addItems(
            ["Balanced", "Fast response", "Suppress oscillation", "High precision", "Low control effort"]
        )

        primary_fields = (
            ("Controlled channel", tuner_channel_selector),
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
            widget.setFixedHeight(36)

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
            gain_layout.setAlignment(Qt.AlignTop)
            gain_title = QLabel(gain)
            gain_title.setObjectName("pidBoundTitle")
            gain_layout.addWidget(gain_title)
            summary = QLabel()
            summary.setObjectName("pidBoundSummary")
            summary.setAlignment(Qt.AlignCenter)
            self.tuner_bound_summaries[gain] = summary
            summary.hide()
            range_row = QHBoxLayout()
            range_row.setSpacing(6)
            for text, control in (("Minimum", minimum), ("Maximum", maximum)):
                field = QVBoxLayout()
                field.setSpacing(2)
                label = QLabel(text)
                label.setObjectName("pidBoundLabel")
                field.addWidget(label)
                field.addWidget(control)
                control.setFixedHeight(36)
                range_row.addLayout(field, 1)
            gain_layout.addLayout(range_row)
            bounds_layout.addWidget(gain_card, 1, column)
            minimum.valueChanged.connect(self._refresh_bound_summaries)
            maximum.valueChanged.connect(self._refresh_bound_summaries)
        grid.addWidget(bounds_panel, 2, 0, 1, 3)
        self._refresh_bound_summaries()

        self.tuner_safety_profile = QComboBox()
        self.tuner_safety_profile.setObjectName("pidTunerSafetyProfile")
        self.tuner_safety_profile.setProperty("stablePopup", True)
        self.tuner_safety_profile.addItems(["Simulation / dry run", "Trim coils / existing scaling"])
        self.tuner_safety_profile.setCurrentIndex(0 if self.backend_mode == "simulation" else 1)
        self.tuner_safety_profile.setEnabled(False)

        candidate_panel = QFrame()
        candidate_panel.setObjectName("pidCandidatePanel")
        candidate_layout = QVBoxLayout(candidate_panel)
        candidate_layout.setContentsMargins(10, 8, 10, 8)
        candidate_layout.setSpacing(6)
        safety_row = QHBoxLayout()
        safety_label = QLabel("Control mode")
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
        tuner_viewport_layout = QVBoxLayout(self.tuner_viewport)
        tuner_viewport_layout.setContentsMargins(0, 0, 0, 0)
        slice_controls = QHBoxLayout()
        slice_label = QLabel("Cost model · Gain axis")
        slice_label.setObjectName("pidFieldLabel")
        slice_controls.addWidget(slice_label)
        self.surrogate_axis = QComboBox()
        self.surrogate_axis.setProperty("stablePopup", True)
        for name in ("Kp", "Ki", "Kd"):
            self.surrogate_axis.addItem(name, name.lower())
        self.surrogate_axis.currentIndexChanged.connect(self._surrogate_axis_changed)
        slice_controls.addWidget(self.surrogate_axis)
        slice_controls.setContentsMargins(12, 8, 12, 0)
        self.surrogate_axis.setMinimumWidth(160)
        self.surrogate_axis.setFixedHeight(40)
        slice_controls.addStretch(1)
        tuner_viewport_layout.addLayout(slice_controls)
        self.surrogate_plot = SurrogatePlotWidget(self.tuner_viewport)
        tuner_viewport_layout.addWidget(self.surrogate_plot)
        outer.addWidget(self.tuner_viewport, 1)

        actions = QHBoxLayout()
        self.prepare_tuning_button = QPushButton("Prepare session")
        self.prepare_tuning_button.setObjectName("fieldAction")
        self.prepare_tuning_button.clicked.connect(self._prepare_tuning_session)
        self.auto_tuning_button = QPushButton("Run trial budget")
        self.auto_tuning_button.setObjectName("fieldAction")
        self.auto_tuning_button.setToolTip("Start a new session and run the Trial Budget automatically; stop on a fault.")
        self.auto_tuning_button.clicked.connect(self._start_auto_tuning)
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
        self.approve_gains_button = QPushButton("Approve best gains")
        self.approve_gains_button.setToolTip('Approve the best observed gains; no separate validation run is performed.')
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
        actions.addWidget(self.auto_tuning_button)
        actions.addWidget(self.run_tuning_trial_button)
        actions.addWidget(self.stop_tuning_button)
        actions.addWidget(self.review_history_button)
        self.metrics_button = QPushButton("Response Metrics")
        self.metrics_button.setObjectName("fieldAction")
        self.metrics_button.clicked.connect(self._show_trial_metrics)
        actions.addWidget(self.metrics_button)
        actions.addStretch(1)
        actions.addWidget(self.approve_gains_button)
        actions.addWidget(self.apply_tuned_gains_button)
        page_layout.addLayout(actions)
        for button in (self.prepare_tuning_button, self.auto_tuning_button, self.run_tuning_trial_button,
                       self.stop_tuning_button, self.review_history_button, self.metrics_button,
                       self.approve_gains_button, self.apply_tuned_gains_button):
            button.setFixedHeight(38)
        return page

    def _show_tuner(self) -> None:
        kind = self._tuning_controller_config["controller_kind"] if self.tuning_session_active else self._controller_config()["controller_kind"]
        self.tuner_engine_label.setText(f"Bayesian optimization — {'Python NLAPID' if kind == 'python_nla' else 'C++ NLAPID' if kind == 'nla' else 'Conventional C++ PID trials'}")
        if self.tuning_session_active:
            self.page_stack.setCurrentWidget(self.tuner_page)
            return
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

    def _load_smoke2_preset(self) -> None:
        if self.simulation_mode != "smoke2" or self.tuning_session_active:
            return
        self.tuner_channel.setCurrentIndex(0)
        self.tuner_target.setValue(250.0)
        self.tuner_trials.setValue(20)
        self.tuner_duration.setValue(10.0)
        self.tuner_profile.setCurrentText("Balanced")
        self.min_output_input.setValue(0.0)
        self.max_output_input.setValue(400.0)
        self.max_step_input.setValue(10.0)
        for gain, limits in {"Kp": (0.0, 2.0), "Ki": (0.0, 2.0), "Kd": (0.0, 0.1)}.items():
            lower, upper = self.tuner_gain_bounds[gain]
            lower.setValue(limits[0])
            upper.setValue(limits[1])
        self.dry_run_check.setChecked(False)
        self.tuner_status.setText(
            "Smoke2 preset: TC1 → 250 A, 20 × 10 s trials. Arm PID on the control page, "
            "then run automatic tuning. The first six safe trials explore the gain bounds."
        )

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

    def _set_auto_tuning(self, enabled: bool) -> None:
        self.tuning_auto_run = enabled
        controls = [self.control_panel, self.tuner_channel, self.tuner_target,
                    self.smoke2_preset_button,
                    self.tuner_trials, self.tuner_duration, self.tuner_profile,
                    self.reset_bounds_button]
        controls.extend(widget for pair in self.tuner_gain_bounds.values() for widget in pair)
        for widget in controls:
            widget.setEnabled(not enabled)

    def _start_auto_tuning(self) -> None:
        if self.tuning_session_active:
            return
        self._prepare_tuning_session()
        if self.tuning_session_active:
            self._set_auto_tuning(True)

    def _prepare_tuning_session(self) -> None:
        for page in QApplication.allWidgets():
            if (isinstance(page, PidControlPage) and page is not self
                    and self.backend is not None and page.backend is self.backend
                    and (page.pid_enabled or page.tuning_session_active)):
                self.tuner_status.setText("Another PID page is using this backend")
                return
        if self.tuning_session_active:
            return
        hardware_requested = self.backend_mode != "simulation"
        if hardware_requested and self.tuner_channel.currentIndex() >= 12:
            self.tuner_status.setText("Select a trim coil (TC1-TC12) for hardware BO.")
            return
        if hardware_requested and not self.arm_button.isChecked():
            self.tuner_status.setText("Explicitly arm PID before preparing a hardware tuning session.")
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
        if self.tuning_surrogate_proposal is not None:
            self.tuning_surrogate_proposal.cancel()
            self.tuning_surrogate_proposal = None
        self._tuning_controller_config = self._controller_config()
        self._lock_controller_inputs(True)
        self.tuning_optimizer = BotorchPidOptimizer(
            bounds["Kp"], bounds["Ki"], bounds["Kd"], use_cuda=False,
            controller_kind=self._tuning_controller_config["controller_kind"]
        )
        self.tuning_candidate = None
        self._set_candidate_values(None)
        self.tuning_trial_candidate = None
        self.tuning_samples.clear()
        self.tuning_results.clear()
        self.tuning_surrogate_grid = None
        self._refresh_surrogate_plot()
        self.review_history_button.setEnabled(False)
        self._set_tuning_progress(state="Preparing")
        self.tuning_session_active = True
        self.prepare_tuning_button.setEnabled(False)
        self.auto_tuning_button.setEnabled(False)
        self.stop_tuning_button.setEnabled(True)
        self.approve_gains_button.setEnabled(False)
        self.apply_tuned_gains_button.setEnabled(False)
        self.tuner_status.setText(f"{self._tuning_controller_config['controller_kind'].upper()}: preparing the next gain candidate.")
        self._request_tuning_candidate()

    def _request_tuning_candidate(self) -> None:
        if self.tuning_optimizer is None or not self.tuning_session_active:
            return
        if len(self.tuning_results) >= self.tuner_trials.value():
            self._finish_tuning_session()
            return
        self.tuning_candidate = None
        self.run_tuning_trial_button.setEnabled(False)
        safe_count = len(self.tuning_optimizer.safe_results)
        initial = self.tuning_optimizer.optimizer.initial_safe_trials
        phase = 'Sobol exploration' if safe_count < initial else 'Fitting GP and optimizing next gains'
        self.tuner_status.setText(f'{phase} · {safe_count} usable observations')
        self._set_tuning_progress(state='Proposing')
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
            self._refresh_surrogate_plot()
            self.tuner_status.setText(
                "Review the proposed gains before starting the trial."
            )
            self._set_tuning_progress(
                trial=f"{len(self.tuning_results) + 1} of {self.tuner_trials.value()}",
                state="Ready",
            )
            self.run_tuning_trial_button.setEnabled(True)
            if self.tuning_auto_run:
                self._run_tuning_trial()

        surrogate_proposal = self.tuning_surrogate_proposal
        if surrogate_proposal is not None and surrogate_proposal.done():
            self.tuning_surrogate_proposal = None
            try:
                self.tuning_surrogate_grid = surrogate_proposal.result()
            except Exception as exc:
                self.tuning_surrogate_grid = {
                    "ready": False,
                    "message": f"Surrogate plot unavailable: {exc}",
                }
            self._refresh_surrogate_plot()

        if self.tuning_trial_candidate is None or self.backend is None:
            return
        try:
            status = self._trial_status()
        except Exception as exc:
            self.tuner_status.setText(f"The trial status could not be read: {exc}")
            self._stop_tuning_session()
            return
        state = str(status["state"])
        elapsed = float(status["elapsed_seconds"])
        measured = float(status["measured_field"])
        error = float(status["error"])
        effort = abs(float(status["control_output"]))
        if self._tuning_controller_config["controller_kind"] in {"nla", "python_nla"}:
            effort = abs(float(status["control_rate"]))
        # Polling may repeat an iteration; only score each completed update once.
        iteration = int(status.get("iterations", 0))
        if iteration and (not self.tuning_samples or elapsed > self.tuning_samples[-1][0]):
            self.tuning_samples.append((elapsed, measured, error, effort))
        self.tuner_status.setText("PID response trial in progress.")
        self._set_tuning_progress(
            trial=f"{len(self.tuning_results) + 1} of {self.tuner_trials.value()}",
            state=state,
            elapsed=f"{elapsed:.1f} / {self.tuner_duration.value():.1f} s",
            error=f"{error:+.3f}",
        )
        if state == "Running" and elapsed >= 1.0 and len(self.tuning_samples) >= 6:
            try:
                interim = evaluate_trial(self.tuning_samples, self.tuner_target.value(),
                                         deadband=self._tuning_controller_config.get("nla_deadband", 0))
            except ValueError:
                self._complete_tuning_trial(False)
                return
            if interim.sustained_oscillation and interim.oscillation_cycles >= 2:
                self._oscillation_stopped = True
                # Retain the penalized performance observation so BO learns to avoid it.
                self._complete_tuning_trial(True)
                return
        if state == "Completed":
            self._complete_tuning_trial(True)
        elif state in {"Faulted", "Stopped"}:
            self._complete_tuning_trial(False)

    def _start_trial(self, config: dict) -> None:
        self.backend.StartPidTrial(config)

    def _trial_status(self) -> dict:
        return self.backend.PidTrialStatus()

    def _stop_trial(self, disable: bool = True) -> None:
        self.backend.StopPidTrial(disable)

    def _run_tuning_trial(self) -> None:
        if not self.tuning_session_active or self.tuning_trial_candidate is not None:
            return
        if self.tuning_candidate is None or self.backend is None:
            return
        channel = self.tuner_channel.currentIndex()
        hardware_trial = self.backend_mode != "simulation"
        if hardware_trial and (channel >= 12 or not self.arm_button.isChecked()):
            if self.tuning_auto_run:
                self._stop_tuning_session()
            self.tuner_status.setText("Hardware BO requires TC1-TC12 and explicit PID arming.")
            return
        allocation = [0.0 for _ in CHANNEL_NAMES]
        allocation[channel] = 1.0
        minimum = min(self.min_output_input.value(), self.max_output_input.value())
        maximum = max(self.min_output_input.value(), self.max_output_input.value())
        candidate = self.tuning_candidate
        config = {
            **self._tuning_controller_config,
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
            "hardware_armed": self.arm_button.isChecked() if hardware_trial else True,
            "dry_run": self.dry_run_check.isChecked() if hardware_trial else False,
            "max_absolute_error": 1.0e12,
            "max_overshoot": 1.0e12,
            "max_control_output": 1.0e12,
            "max_saturation_seconds": 1.0e12,
        }
        try:
            if config["controller_kind"] == "nla" and not hasattr(CycloViz, "NLAPID"):
                raise RuntimeError("Rebuild CycloViz to enable C++ NLAPID trials")
            self._start_trial(config)
        except Exception as exc:
            if self.tuning_auto_run:
                self._stop_tuning_session()
            self.tuner_status.setText(f"The trial could not be started: {exc}")
            return
        self.tuning_trial_candidate = candidate
        self._oscillation_stopped = False
        self.tuning_candidate = None
        self._refresh_surrogate_plot()
        self.tuning_samples.clear()
        self.run_tuning_trial_button.setEnabled(False)
        self.stop_tuning_button.setEnabled(True)


    def _complete_tuning_trial(self, safe: bool) -> None:
        candidate = self.tuning_trial_candidate
        if candidate is None or self.tuning_optimizer is None:
            return
        if self.backend is not None:
            self._stop_trial(True)
        target = self.tuner_target.value()
        samples = self.tuning_samples
        metrics = None
        try:
            metrics = evaluate_trial(samples, target,
                                     deadband=self._tuning_controller_config.get("nla_deadband", 0)
                                     if self._tuning_controller_config["controller_kind"] != "conventional" else 0)
            score = trial_cost(metrics, self.tuner_profile.currentText())
        except ValueError:
            safe = False
            score = 1.0e12
        if not safe or not math.isfinite(score):
            safe = False
            score = 1.0e12
        settling_time = metrics.settling_time if metrics else 0.0
        steady_state_error = metrics.steady_state_error if metrics else 0.0
        result = PidTrialResult(
            candidate, score, settling_time, metrics.overshoot if metrics else 0.0,
            steady_state_error, metrics.control_effort if metrics else 0.0, safe,
            controller_kind=self._tuning_controller_config["controller_kind"], metrics=metrics,
            termination_reason="Stopped: sustained oscillation" if self._oscillation_stopped else "Completed" if safe else "Faulted / invalid",
        )
        self.tuning_optimizer.record_results([result])
        self.tuning_results.append(result)
        self.review_history_button.setEnabled(True)
        self.tuning_trial_candidate = None
        self._request_surrogate_grid()
        self._refresh_surrogate_plot()
        best = self.tuning_optimizer.best_result
        best_text = "none" if best is None else f"{best.score:.4f}"
        self.tuner_status.setText(
            f"{self._tuning_controller_config['controller_kind'].upper()} trial recorded. Cost: {score:.4f}. Best cost: {best_text}. Lower is better."
        )
        self._set_tuning_progress(
            trial=f"{len(self.tuning_results)} of {self.tuner_trials.value()}",
            state="Oscillation stopped" if self._oscillation_stopped else "Recorded" if safe else "Unsafe",
            elapsed=f"{samples[-1][0] if samples else 0.0:.1f} s",
            error=f"{steady_state_error:.3f}",
        )
        if self.tuning_auto_run and not safe:
            self._stop_tuning_session()
            self.tuner_status.setText("Automatic tuning stopped: trial faulted, stopped, or produced invalid results. Review Trial History.")
            return
        self._request_tuning_candidate()

    def _finish_tuning_session(self) -> None:
        self._lock_controller_inputs(False)
        self.tuning_session_active = False
        self._set_auto_tuning(False)
        self.auto_tuning_button.setEnabled(True)
        self.stop_tuning_button.setEnabled(False)
        self.prepare_tuning_button.setEnabled(True)
        best = self.tuning_optimizer.best_result if self.tuning_optimizer else None
        if best is None:
            self.tuner_status.setText("Tuning is complete, but no safe gain result was found.")
            return
        self.approve_gains_button.setEnabled(True)
        self.tuner_status.setText(
            f"{self._tuning_controller_config['controller_kind'].upper()} tuning is complete. The best observed cost is {best.score:.4f}."
        )
        self._set_candidate_values(best.candidate)
        self._refresh_surrogate_plot()

    def _validate_best_gains(self) -> None:
        best = self.tuning_optimizer.best_result if self.tuning_optimizer else None
        if best is None:
            return
        if best.metrics and best.metrics.sustained_oscillation:
            self.tuner_status.setText("Cannot approve gains with sustained oscillation. Review Response Metrics.")
            self.apply_tuned_gains_button.setEnabled(False)
            return
        self.apply_tuned_gains_button.setProperty("approvedCandidate", best.candidate)
        self._approved_controller_config = dict(self._tuning_controller_config)
        self.apply_tuned_gains_button.setEnabled(True)
        self.tuner_status.setText(
            "Best observed gains approved for application; no separate validation run was performed."
        )
        self._set_candidate_values(best.candidate)
        self._refresh_surrogate_plot()

    def _surrogate_axis_changed(self, _index: int) -> None:
        self.tuning_surrogate_grid = None
        self._refresh_surrogate_plot()
        self._request_surrogate_grid()

    def _request_surrogate_grid(self) -> None:
        if self.tuning_optimizer is None:
            return
        if self.tuning_surrogate_proposal is not None:
            self.tuning_surrogate_proposal.cancel()
        self.tuning_surrogate_proposal = self.tuning_executor.submit(
            self.tuning_optimizer.surrogate_slice,
            axis_x=self.surrogate_axis.currentData(),
            point_count=160,
        )

    def _refresh_surrogate_plot(self) -> None:
        if not hasattr(self, "surrogate_plot"):
            return
        best = self.tuning_optimizer.best_result if self.tuning_optimizer else None
        candidate = self.tuning_candidate or self.tuning_trial_candidate
        self.surrogate_plot.set_state(
            grid=self.tuning_surrogate_grid,
            axis_x=self.surrogate_axis.currentData(),
            results=self.tuning_results,
            candidate=candidate,
            best=best,
        )

    def _build_metrics_dialog(self) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle("BO Response Metrics")
        dialog.resize(1200, 540)
        layout = setup_pid_dialog(dialog, 'BO Response Metrics', window_controls=False)
        explanation = QLabel(
            "Settling: enter tolerance and remain there through trial end for at least 0.5 s. "
            "Transient: first entry into tolerance. Steady-state values estimate the final 20% of the run.\n"
            "Tolerance = max(0.1 A, 1% of target, NLA deadband). Overshoot is diagnostic only (zero cost weight). "
            "Oscillation penalty is always active; sustained oscillation blocks gain approval. "
            "After at least 1 s and 2 detected cycles, persistent oscillation stops the trial and its penalized result is retained. "
            "These estimates use fresh status samples; very fast oscillations can be missed."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        table = QTableWidget(len(self.tuning_results), 11)
        table.setObjectName("pidResponseMetrics")
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setHorizontalHeaderLabels(["Trial", "Controller", "Settling (s)", "Transient (s)",
            "Steady |error| (A)", "Steady RMS (A)", "Osc. amplitude (A)", "Osc. cycles",
            "Osc. penalty", "Overshoot (A)", "Response"])
        for row, result in enumerate(self.tuning_results):
            m = result.metrics
            if m is None:
                values = [row+1, result.controller_kind] + ["Unavailable"]*8 + ["Insufficient samples"]
            else:
                values = [row+1, result.controller_kind,
                    f"{m.settling_time:.3g}" if m.settled else "Not settled",
                    f"{m.transient_time:.3g}" if m.entered_tolerance else "Not reached",
                    f"{m.steady_state_error:.4g}", f"{m.steady_state_rms:.4g}",
                    f"{m.oscillation_amplitude:.4g}", f"{m.oscillation_cycles:.2g}",
                    f"{m.oscillation_penalty:.4g}", f"{m.overshoot:.4g}",
                    "Sustained oscillation" if m.sustained_oscillation else "Settled" if m.settled else "Unsettled"]
            if not result.safe:
                values[-1] = "Aborted / invalid: " + str(values[-1])
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(str(value)))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        layout.addWidget(table)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close, 0, Qt.AlignRight)
        return dialog

    def _show_trial_metrics(self) -> None:
        dialog = self._build_metrics_dialog()
        dialog.exec()
        dialog.deleteLater()

    def _show_tuning_history(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowFlag(Qt.FramelessWindowHint, True)
        dialog.setAttribute(Qt.WA_TranslucentBackground)
        dialog.setObjectName("pidHistoryDialog")
        dialog.setStyleSheet("""
            QDialog#pidHistoryDialog { background: transparent; }
            QFrame#pidHistorySurface { background: #101a29;
                border: 2px solid #516a86; border-radius: 16px; }
            QFrame#dialogTitleBar { background: #24364c; border-radius: 6px; }
            QDialog#pidHistoryDialog QLabel { color: #dbe5f1; font-family: 'Segoe UI'; font-size: 13px; }
            QTableWidget#pidTrialHistory { background: #142235; alternate-background-color: #1b2c42;
                color: #e7eef8; border: 1px solid #34465d; border-radius: 6px;
                font-family: 'Segoe UI'; font-size: 13px; selection-background-color: #315477; }
            QTableWidget#pidTrialHistory QHeaderView::section { background: #24364c;
                color: #b9cce1; border: none; padding: 8px; font-family: 'Segoe UI'; font-size: 12px; }
        """)
        dialog.setWindowTitle("PID Gain Tuning Trial History")
        dialog.resize(1120, 540)
        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(0, 0, 0, 0)
        surface = QFrame(dialog)
        surface.setObjectName("pidHistorySurface")
        outer.addWidget(surface)
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(DialogTitleBar(dialog, "PID Gain Tuning Trial History"))
        safe = [r for r in self.tuning_results if r.safe and math.isfinite(r.score)]
        best = min(safe, key=lambda r: r.score) if safe else None
        summary = QLabel(
            f"{len(self.tuning_results)} trials  ·  {len(safe)} safe  ·  "
            + (f"Best cost: {best.score:.4f}" if best else "No safe result yet")
        )
        summary.setObjectName("pidSectionTitle")
        layout.addWidget(summary)
        hint = QLabel("Lower cost is better · Current BO session · Select trial numbers to export")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        filters = QHBoxLayout()
        first, last = QSpinBox(), QSpinBox()
        for spin in (first, last):
            spin.setRange(1, max(1, len(self.tuning_results)))
        last.setValue(max(1, len(self.tuning_results)))
        filters.addWidget(QLabel('Trials'))
        filters.addWidget(first)
        filters.addWidget(QLabel('through'))
        filters.addWidget(last)
        export = QPushButton('Export trials CSV')
        details = QCheckBox('Show gains and secondary metrics')
        filters.addWidget(export)
        filters.addWidget(details)
        layout.addLayout(filters)
        table = QTableWidget(len(self.tuning_results), 11)
        table.setObjectName("pidTrialHistory")
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(36)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.setHorizontalHeaderLabels(
            [
                "Trial", "Kp", "Ki", "Kd", "Cost ↓", "Settling (s)",
                "Overshoot (A)", "Steady error (A)", "Effort", "Result", "Controller",
            ]
        )
        for row, result in enumerate(self.tuning_results):
            values = (
                row + 1, result.candidate.kp, result.candidate.ki,
                result.candidate.kd, result.score, result.settling_time if result.metrics and result.metrics.settled else 'Not settled',
                result.overshoot, result.steady_state_error,
                result.control_effort, "Oscillating" if result.metrics and result.metrics.sustained_oscillation else "Best observed" if result is best else "Completed" if result.safe else "Faulted",
                result.controller_kind.upper(),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, round(value, 4) if isinstance(value, float) else value)
                item.setTextAlignment(Qt.AlignVCenter | (Qt.AlignRight if column < 9 else Qt.AlignLeft))
                if result is best:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                item.setToolTip("Best observed safe cost" if result is best else "Included in model training" if result.safe else "Excluded from model training")
                table.setItem(row, column, item)
        table.setSortingEnabled(True)
        table.sortItems(0, Qt.DescendingOrder)
        def toggle_details(visible):
            for column in (1, 2, 3, 6, 8, 10):
                table.setColumnHidden(column, not visible)
        details.toggled.connect(toggle_details)
        toggle_details(False)
        def export_trials():
            if first.value() > last.value():
                hint.setText('First trial must be less than or equal to last trial.')
                return
            path, _ = QFileDialog.getSaveFileName(dialog, 'Export trials', 'bo-trials.csv', 'CSV (*.csv)')
            if not path:
                return
            try:
                with open(path, 'w', newline='', encoding='utf-8') as handle:
                    writer = csv.writer(handle)
                    writer.writerow(table.horizontalHeaderItem(col).text() for col in range(table.columnCount()))
                    for row in range(table.rowCount()):
                        if first.value() <= int(table.item(row, 0).text()) <= last.value():
                            writer.writerow(table.item(row, col).text() for col in range(table.columnCount()))
                hint.setText('CSV exported')
            except OSError as exc:
                hint.setText(f'Export failed: {exc}')
        export.clicked.connect(export_trials)
        layout.addWidget(table)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, 0, Qt.AlignRight)
        dialog.exec()

    def _restore_controller_config(self, approved: dict) -> None:
        self.controller_kind_input.setCurrentIndex(self.controller_kind_input.findData(approved["controller_kind"]))
        for key, widget in (("nla_deadband", self.nla_deadband_input),
                            ("nla_direction_check_interval", self.nla_window_input),
                            ("nla_trend_tolerance", self.nla_tolerance_input),
                            ("nla_integral_memory_s", self.nla_memory_input),
                            ("nla_output_max", self.max_step_input)):
            widget.setValue(approved[key])
        self.nla_direction_input.setCurrentIndex(self.nla_direction_input.findData(approved["nla_initial_direction"]))

    def _apply_tuned_gains(self) -> None:
        candidate = self.apply_tuned_gains_button.property("approvedCandidate")
        if not isinstance(candidate, PidGainCandidate):
            return
        self._restore_controller_config(self._approved_controller_config)
        self.selected_index = self.tuner_channel.currentIndex()
        self.channel_select.setCurrentIndex(self.selected_index)
        self.setpoint_input.setValue(self.tuner_target.value())
        self.kp_input.setValue(candidate.kp)
        self.ki_input.setValue(candidate.ki)
        self.kd_input.setValue(candidate.kd)
        self.run_metrics.method.setCurrentText('Bayesian optimization')
        self._show_pid_control()
        self.last_safety_message = "Validated tuning settings applied; PID remains disabled"
        self._refresh_status()

    def _stop_tuning_session(self) -> None:
        self._lock_controller_inputs(False)
        if self.backend is not None and self.tuning_trial_candidate is not None:
            self._stop_trial(True)
        self.tuning_session_active = False
        self._set_auto_tuning(False)
        self.auto_tuning_button.setEnabled(True)
        if self.tuning_proposal is not None:
            self.tuning_proposal.cancel()
            self.tuning_proposal = None
        if self.tuning_surrogate_proposal is not None:
            self.tuning_surrogate_proposal.cancel()
            self.tuning_surrogate_proposal = None
        self.tuning_trial_candidate = None
        self.tuning_candidate = None
        self._refresh_surrogate_plot()
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
        if not armed and self.tuning_session_active:
            self._stop_tuning_session()
        if not armed and self.pid_enabled:
            self._stop_pid("Disarmed")
        self.enable_button.setEnabled(armed)
        self.arm_button.setText("Disarm PID" if armed else "Arm PID")
        self.last_safety_message = "Armed" if armed else "Not armed"
        self._refresh_status()

    def _set_pid_enabled(self, enabled: bool) -> None:
        if self._service_pid_active:
            self._stop_pid("Operator stop")
            return
        if enabled and self._cpp_nla_selected():
            self._start_service_nla()
            return
        if enabled and not self._is_safe_to_run():
            self.enable_button.blockSignals(True)
            self.enable_button.setChecked(False)
            self.enable_button.blockSignals(False)
            self.pid_enabled = False
            self._refresh_status()
            return
        self.pid_enabled = enabled
        if enabled:
            self.run_metrics.start(self._run_metrics_config())
        else:
            self.run_metrics.finish('Operator stop')
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

    def _run_metrics_config(self) -> dict:
        return dict(self._controller_config(), setpoint=self.setpoint_input.value(),
                    kp=self.kp_input.value(), ki=self.ki_input.value(), kd=self.kd_input.value(),
                    channel=self.selected_index, backend=self.backend_mode,
                    simulation_mode=self.simulation_mode, dry_run=self.dry_run_check.isChecked(),
                    minimum_output=self.min_output_input.value(), maximum_output=self.max_output_input.value())

    def _tick_feedback(self) -> None:
        metric_stamp = None
        if self.backend_available and self.backend is not None:
            try:
                snapshot = self.backend.LatestSnapshot()
                metric_stamp = float(snapshot['timestamp'])
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
            metric_stamp = time.perf_counter()

        self._sync_channel_toggles()
        if self.pid_enabled and not self._is_safe_to_run():
            self._stop_pid(self.last_safety_message)
        if self.pid_enabled:
            config = self._run_metrics_config()
            if any(self.run_metrics.config.get(key) != value for key, value in config.items()):
                self.run_metrics.finish('Setpoint or controller settings changed')
                self.run_metrics.start(config)
            if metric_stamp is not None:
                self.run_metrics.sample(metric_stamp, self.actual_values[self.selected_index])
        self._tick_pid_controller()
        self._poll_tuning_workflow()
        self._append_plot_sample()
        self._refresh_plot()
        self._refresh_status()

    def _tick_pid_controller(self) -> None:
        if self._service_pid_active:
            self._poll_service_nla()
            return
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
        if self.tuning_session_active:
            self.last_safety_message = "Stop the tuning session before enabling normal PID control"
            return False
        for page in QApplication.allWidgets():
            if (isinstance(page, PidControlPage) and page is not self
                    and self.backend is not None and page.backend is self.backend
                    and (page.pid_enabled or page.tuning_session_active)):
                self.last_safety_message = "Another PID page is using this backend"
                return False
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
        self.run_metrics.finish(reason)
        service_was_active = self._service_pid_active
        if service_was_active:
            self._service_pid_active = False
            try:
                self.backend.StopPidTrial(False)
            except Exception as exc:
                reason = f"{reason}; stop failed: {exc}"
            self._lock_controller_inputs(False)
        self.pid_enabled = False
        self.enable_button.blockSignals(True)
        self.enable_button.setChecked(False)
        self.enable_button.setText("Enable PID")
        self.enable_button.blockSignals(False)
        self._reset_pid_state()
        self.last_safety_message = reason
        if not service_was_active and not self._cpp_nla_selected():
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
        error = self.setpoint_input.value() - actual
        state = "active" if self.pid_enabled else "standby"
        status_values = {
            "Channel": channel,
            "State": state.title(),
            "Error": f"{error:+.2f} A",
            "Actual": f"{actual:.2f} A",
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
        if self.backend is not None:
            self.backend_available = True
            try:
                health = self.backend.Health()
                self.backend_connection = str(health["connection"])
                self.backend_destination = str(health["endpoint"])
            except Exception:
                self.backend_connection = "Connected"
                self.backend_destination = self.zmq_endpoint
            return
        if not self.manage_backend:
            self.backend_available = False
            self.backend_connection = "Not Connected"
            self.backend_destination = "Shared Field Control backend unavailable"
            return
        if CycloViz is None or not hasattr(CycloViz, "ControlService"):
            return
        try:
            self.backend = CycloViz.ControlService()
            self.owns_backend = True
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
            self.owns_backend = False
            self.backend_available = False
            self.backend_connection = "Not Connected"
            self.backend_destination = f"{self.backend_mode.upper()} unavailable: {exc}"

    def closeEvent(self, event) -> None:
        self.stop_backend()
        super().closeEvent(event)

    def stop_backend(self) -> None:
        self.timer.stop()
        self.run_metrics.finish('Page closed')
        if self._service_pid_active:
            self._stop_pid("Page closed")
        self._stop_tuning_session()
        self.tuning_executor.shutdown(wait=False, cancel_futures=True)
        if self.backend is not None and self.owns_backend:
            try:
                self.backend.Stop()
            except Exception:
                pass
        self.backend_available = False
