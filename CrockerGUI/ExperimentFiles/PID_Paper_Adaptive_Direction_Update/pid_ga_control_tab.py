# -*- coding: utf-8 -*-
"""Tesla-style PID and genetic-algorithm controller workspace.

The GUI imports the PID and GA engines from separate, non-Qt modules.  That
allows PID/GA development without modifying Manual or Sequence code.

Safety note:
    The tab starts in preview mode.  It calculates PID output but does not write
    that output to hardware unless an explicit ``output_callback`` is supplied
    by the integration layer and ARM HARDWARE OUTPUT is checked.
"""

from __future__ import annotations

import math
import time
from collections import deque
from typing import Callable

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from controller_context import ControlMode, ControllerContext
from controller_theme import (
    Card,
    T,
    TeslaTabBar,
    TrendPlot,
    info_label_css,
    secondary_button_css,
)
from ga_pid_tuner import GAPIDTuner, GATuningConfig, GainBounds, PIDCandidate
from pid_controller import (
    AdaptiveDirectionPIDController,
    AdaptiveDirectionSettings,
    PIDGains,
    PIDLimits,
    PIDResult,
)


PIDOutputCallback = Callable[[int, float, PIDResult], bool | None]


class PIDGAControlTab(QWidget):
    """Nested PID and GA pages with independent graphs and shared controller context."""

    candidate_requested = pyqtSignal(object)
    pid_output_calculated = pyqtSignal(int, float, object)

    def __init__(
        self,
        context: ControllerContext,
        output_callback: PIDOutputCallback | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.context = context
        self.output_callback = output_callback

        self.pid = AdaptiveDirectionPIDController()
        self.ga_tuner: GAPIDTuner | None = None
        self._pid_running = False
        self._actuator_index = min(9, max(0, len(self.context.channel_names) - 1))
        self._pid_channel = self._actuator_index
        self._last_pid_time = 0.0
        # The GUI may poll faster than the beam packet stream.  Track the last
        # processed receive timestamp so one beam sample can produce at most one
        # PID/TC command; otherwise the same held measurement could be integrated
        # and applied repeatedly before the plant has supplied new feedback.
        self._last_processed_beam_timestamp = 0.0
        self._baseline_target = float("nan")
        self._last_proposed_target = float("nan")

        self._plot_t0 = time.monotonic()
        self._plot_t = deque(maxlen=1000)
        self._plot_setpoint = deque(maxlen=1000)
        self._plot_actual = deque(maxlen=1000)
        self._plot_abs_error = deque(maxlen=1000)
        self._plot_deadband = deque(maxlen=1000)

        # GA history is intentionally independent from the PID response plot.
        # Each submitted candidate contributes one point: candidate fitness and
        # best-so-far fitness versus evaluation number.
        self._ga_evaluation_count = 0
        self._ga_evaluations = deque(maxlen=1000)
        self._ga_fitness_history = deque(maxlen=1000)
        self._ga_best_history = deque(maxlen=1000)

        self._build_ui()
        self._connect_context()
        self.refresh()

        self._pid_timer = QTimer(self)
        self._pid_timer.timeout.connect(self._pid_step)

        self._display_timer = QTimer(self)
        self._display_timer.timeout.connect(self._refresh_live_readouts)
        self._display_timer.start(100)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        """Build separate PID and GA workspaces inside the controller page.

        The public widget remains ``PIDGAControlTab`` so the integration in
        ``MagneticFieldControllerWindow.py`` does not change.  Internally, the
        page now contains two Tesla-style tabs:

        * PID CONTROL keeps the existing PID channel selector, live readouts,
          response graph, parameters, and start/stop controls.
        * GA AUTO-TUNE contains only the genetic-algorithm controls and its own
          candidate-fitness graph.
        """
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.control_tabs = QTabWidget()
        self.control_tabs.setTabBar(TeslaTabBar())
        self.control_tabs.tabBar().setExpanding(True)
        self.control_tabs.setDocumentMode(True)
        self.control_tabs.setStyleSheet(
            "QTabWidget::pane { border: none; background: transparent; }"
        )
        self.control_tabs.addTab(self._build_pid_page(), "PID CONTROL")
        self.control_tabs.addTab(self._build_ga_page(), "GA AUTO-TUNE")
        outer.addWidget(self.control_tabs)

        # Keep the GA seed-gain readout synchronized with the gain fields that
        # remain on the PID page.
        for spin in (self.kp_spin, self.ki_spin, self.kd_spin):
            spin.valueChanged.connect(lambda _value: self._refresh_ga_context())
        self._refresh_ga_context()

    @staticmethod
    def _new_scroll_page() -> tuple[QWidget, QVBoxLayout]:
        """Create one independently scrollable nested-tab page."""
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page_layout.addWidget(scroll)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 14, 18, 18)
        layout.setSpacing(14)
        scroll.setWidget(body)
        return page, layout

    def _build_pid_page(self) -> QWidget:
        page, layout = self._new_scroll_page()

        title = QLabel("PID CONTROL")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "font-size: 20px; font-weight: 500; letter-spacing: 1px;"
        )
        layout.addWidget(title)

        notice = QLabel(
            "PAPER-SCHEMATIC MODE — Beam-current error is e = setpoint − measured. "
            "The PID uses |e|, while an independent direction d = +1 or −1 is kept when |e| decreases "
            "and reversed when |e| increases. Hardware output remains blocked until ARM HARDWARE OUTPUT is selected."
        )
        notice.setWordWrap(True)
        notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        notice.setStyleSheet(info_label_css(T.amber))
        layout.addWidget(notice)

        # This is the same PID content that previously occupied the left side of
        # the combined PID/GA page, now allowed to use the full page width.
        layout.addWidget(self._build_channel_selector_card())
        layout.addWidget(self._build_readout_card())
        layout.addWidget(self._build_plot_card())
        layout.addWidget(self._build_pid_card())
        layout.addStretch()
        return page

    def _build_ga_page(self) -> QWidget:
        page, layout = self._new_scroll_page()

        title = QLabel("GENETIC ALGORITHM — PID AUTO-TUNE")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "font-size: 20px; font-weight: 500; letter-spacing: 1px;"
        )
        layout.addWidget(title)

        notice = QLabel(
            "GA WORKSPACE — Candidate generation, fitness submission, progress, and fitness history are isolated "
            "from the PID controls. Lower fitness is better. The starting gains are read from the PID CONTROL tab."
        )
        notice.setWordWrap(True)
        notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        notice.setStyleSheet(info_label_css(T.cyan))
        layout.addWidget(notice)

        layout.addWidget(self._build_ga_context_card())
        layout.addWidget(self._build_ga_plot_card())
        layout.addWidget(self._build_ga_card())
        layout.addStretch()
        return page

    def _build_ga_context_card(self) -> QWidget:
        card = Card(radius=9)
        grid = QGridLayout(card)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)

        channel_heading = QLabel("SELECTED ACTUATOR")
        channel_heading.setStyleSheet(
            f"color: {T.muted}; font-size: 11px; font-weight: 600;"
        )
        seed_heading = QLabel("GAINS LOADED IN PID TAB (Kp, Ki, Kd)")
        seed_heading.setStyleSheet(
            f"color: {T.muted}; font-size: 11px; font-weight: 600;"
        )
        grid.addWidget(channel_heading, 0, 0)
        grid.addWidget(seed_heading, 0, 1)

        self.ga_channel_display = QLabel("—")
        self.ga_channel_display.setStyleSheet(
            f"color: {T.cyan}; font-size: 18px; font-weight: 600;"
        )
        self.ga_seed_display = QLabel("—")
        self.ga_seed_display.setStyleSheet(
            f"color: {T.text}; font-size: 16px; font-weight: 600;"
        )
        grid.addWidget(self.ga_channel_display, 1, 0)
        grid.addWidget(self.ga_seed_display, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 3)
        return card

    def _build_ga_plot_card(self) -> QWidget:
        card = Card(radius=9)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 10, 8)
        layout.setSpacing(8)

        title = QLabel("GA FITNESS HISTORY")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {T.muted}; font-size: 13px;")
        layout.addWidget(title)

        readouts = QHBoxLayout()
        readouts.setSpacing(10)
        last_label = QLabel("LAST CANDIDATE")
        last_label.setStyleSheet(f"color: {T.orange}; font-size: 11px;")
        self.ga_last_fitness_display = self._component_display(T.orange)
        best_label = QLabel("BEST SO FAR")
        best_label.setStyleSheet(f"color: {T.green}; font-size: 11px;")
        self.ga_best_fitness_plot_display = self._component_display(T.green)
        readouts.addStretch()
        readouts.addWidget(last_label)
        readouts.addWidget(self.ga_last_fitness_display)
        readouts.addSpacing(16)
        readouts.addWidget(best_label)
        readouts.addWidget(self.ga_best_fitness_plot_display)
        readouts.addStretch()
        layout.addLayout(readouts)

        self.ga_plot = TrendPlot(
            y_axis_label="FITNESS SCORE",
            x_axis_label="EVALUATION",
            target_color=T.green,
            actual_color=T.orange,
        )
        self.ga_plot.setMinimumHeight(240)
        layout.addWidget(self.ga_plot)

        explanation = QLabel(
            "Orange = submitted candidate fitness. Green = best fitness found so far. Fitness is lower-is-better."
        )
        explanation.setAlignment(Qt.AlignmentFlag.AlignCenter)
        explanation.setStyleSheet(f"color: {T.muted}; font-size: 11px;")
        layout.addWidget(explanation)
        return card

    def _build_channel_selector_card(self) -> QWidget:
        """Separate the beam controlled variable from the magnetic actuator."""
        card = Card(radius=9)
        grid = QGridLayout(card)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)

        variable_heading = QLabel("CONTROLLED VARIABLE")
        variable_heading.setStyleSheet(
            f"color: {T.muted}; font-size: 11px; font-weight: 600;"
        )
        actuator_heading = QLabel("ACTUATOR / CONTROL CHANNEL")
        actuator_heading.setStyleSheet(
            f"color: {T.muted}; font-size: 11px; font-weight: 600;"
        )
        feedback_heading = QLabel("BEAM FEEDBACK")
        feedback_heading.setStyleSheet(
            f"color: {T.muted}; font-size: 11px; font-weight: 600;"
        )
        grid.addWidget(variable_heading, 0, 0)
        grid.addWidget(actuator_heading, 0, 1)
        grid.addWidget(feedback_heading, 0, 2)

        controlled_value = QLabel("BEAM CURRENT")
        controlled_value.setStyleSheet(
            f"color: {T.cyan}; font-size: 18px; font-weight: 600;"
        )
        grid.addWidget(controlled_value, 1, 0)

        self.actuator_selector = QComboBox()
        self.actuator_selector.addItems(self.context.channel_names[:12])
        self.actuator_selector.setCurrentIndex(self._actuator_index)
        self.actuator_selector.setMinimumWidth(220)
        self.actuator_selector.setToolTip(
            "The PID feedback is beam current. This selection chooses only the trim-coil actuator."
        )
        self.actuator_selector.setStyleSheet(
            f"QComboBox {{ color: {T.cyan}; font-size: 16px; font-weight: 600; padding: 7px 10px; }}"
        )
        self.actuator_selector.currentIndexChanged.connect(
            self._on_actuator_selector_changed
        )
        grid.addWidget(self.actuator_selector, 1, 1)

        self.beam_source_status = QLabel("NO DATA")
        self.beam_source_status.setStyleSheet(
            f"color: {T.red}; font-size: 16px; font-weight: 600;"
        )
        grid.addWidget(self.beam_source_status, 1, 2)

        explanation = QLabel(
            "The actuator is independent from the channel selected on the Magnetic Field page. "
            "The first paper configuration uses TC10, but TC1–TC12 remain selectable for controlled tests."
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet(f"color: {T.muted}; font-size: 12px;")
        grid.addWidget(explanation, 2, 0, 1, 3)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 2)
        return card

    def _build_readout_card(self) -> QWidget:
        card = Card(radius=9)
        grid = QGridLayout(card)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        def add_metric(row: int, col: int, heading: str, color: str) -> QLabel:
            box = QWidget()
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(4, 2, 4, 2)
            box_layout.setSpacing(3)
            title = QLabel(heading)
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setStyleSheet(f"color: {color}; font-size: 11px;")
            value = QLabel("—")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setMinimumHeight(34)
            value.setStyleSheet(
                f"color: {color}; font-size: 21px; font-weight: 600;"
            )
            box_layout.addWidget(title)
            box_layout.addWidget(value)
            grid.addWidget(box, row, col)
            grid.setColumnStretch(col, 1)
            return value

        self.controlled_display = add_metric(0, 0, "CONTROLLED VARIABLE", T.cyan)
        self.actuator_display = add_metric(0, 1, "ACTUATOR", T.cyan)
        self.setpoint_display = add_metric(0, 2, "SETPOINT", T.cyan)
        self.actual_display = add_metric(0, 3, "MEASURED BEAM", T.orange)
        self.error_display = add_metric(1, 0, "SIGNED ERROR e", T.amber)
        self.abs_error_display = add_metric(1, 1, "ERROR MAGNITUDE |e|", T.amber)
        self.trend_display = add_metric(1, 2, "|e| TREND", T.text)
        self.direction_display = add_metric(1, 3, "ADAPTIVE DIRECTION d", T.text)

        # Backward-compatible name used by some earlier integration snippets.
        self.channel_display = self.actuator_display
        return card

    def _build_plot_card(self) -> QWidget:
        card = Card(radius=9)
        outer = QHBoxLayout(card)
        outer.setContentsMargins(12, 8, 10, 8)
        outer.setSpacing(12)

        response_panel = QWidget()
        response_layout = QVBoxLayout(response_panel)
        response_layout.setContentsMargins(0, 0, 0, 0)
        response_title = QLabel("BEAM-CURRENT SETPOINT RESPONSE")
        response_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        response_title.setStyleSheet(f"color: {T.muted}; font-size: 13px;")
        response_layout.addWidget(response_title)
        self.plot = TrendPlot(y_axis_label="BEAM CURRENT (nA)")
        self.plot.setMinimumHeight(235)
        response_layout.addWidget(self.plot)
        response_legend = QLabel("Cyan = beam setpoint     Orange = measured beam current")
        response_legend.setAlignment(Qt.AlignmentFlag.AlignCenter)
        response_legend.setStyleSheet(f"color: {T.muted}; font-size: 11px;")
        response_layout.addWidget(response_legend)
        outer.addWidget(response_panel, 1)

        error_panel = QWidget()
        error_layout = QVBoxLayout(error_panel)
        error_layout.setContentsMargins(0, 0, 0, 0)
        error_title = QLabel("ABSOLUTE ERROR AND DEADBAND")
        error_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        error_title.setStyleSheet(f"color: {T.muted}; font-size: 13px;")
        error_layout.addWidget(error_title)
        self.error_plot = TrendPlot(
            y_axis_label="|ERROR| (nA)",
            target_color=T.green,
            actual_color=T.amber,
        )
        self.error_plot.setMinimumHeight(235)
        error_layout.addWidget(self.error_plot)
        error_legend = QLabel("Amber = |signed error|     Green = deadband")
        error_legend.setAlignment(Qt.AlignmentFlag.AlignCenter)
        error_legend.setStyleSheet(f"color: {T.muted}; font-size: 11px;")
        error_layout.addWidget(error_legend)
        outer.addWidget(error_panel, 1)
        return card

    def _build_pid_card(self) -> QWidget:
        card = Card(radius=9)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        title = QLabel("ADAPTIVE-DIRECTION PID PARAMETERS")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title)

        note = QLabel(
            "Signed error is retained for diagnostics, but P, I, and D are calculated from |e|. "
            "Direction is evaluated only after the direction-check interval so the measured plant delay does not cause rapid sign reversals. "
            "A PID update is executed only when a new beam sample arrives; the poll timer never reuses a held sample for another TC move."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {T.muted};")
        layout.addWidget(note)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self.setpoint_spin = self._double_spin(-1_000_000.0, 1_000_000.0, 4, 0.1)
        self.setpoint_spin.setSuffix(" nA")
        self.kp_spin = self._double_spin(0.0, 1_000_000.0, 6, 0.001)
        self.ki_spin = self._double_spin(0.0, 1_000_000.0, 6, 0.0001)
        self.kd_spin = self._double_spin(0.0, 1_000_000.0, 6, 0.0001)

        self.deadband_spin = self._double_spin(0.0, 1_000_000.0, 4, 0.01)
        self.deadband_spin.setValue(0.05)
        self.deadband_spin.setSuffix(" nA")
        self.trend_tolerance_spin = self._double_spin(0.0, 1_000_000.0, 4, 0.01)
        self.trend_tolerance_spin.setValue(0.01)
        self.trend_tolerance_spin.setSuffix(" nA")
        self.direction_check_spin = self._double_spin(0.0, 60.0, 2, 0.1)
        self.direction_check_spin.setValue(1.0)
        self.direction_check_spin.setSuffix(" s")
        self.initial_direction_combo = QComboBox()
        self.initial_direction_combo.addItem("+1 — INCREASE TC TARGET", 1)
        self.initial_direction_combo.addItem("−1 — DECREASE TC TARGET", -1)

        self.output_min_spin = self._double_spin(0.0, 9999.99, 4, 0.01)
        self.output_max_spin = self._double_spin(0.0, 9999.99, 4, 0.05)
        self.output_min_spin.setValue(0.0)
        self.output_max_spin.setValue(1.0)
        self.output_min_spin.setSuffix(" A/update")
        self.output_max_spin.setSuffix(" A/update")
        self.integral_min_spin = self._double_spin(0.0, 9999.99, 4, 0.01)
        self.integral_max_spin = self._double_spin(0.0, 9999.99, 4, 0.05)
        self.integral_min_spin.setValue(0.0)
        self.integral_max_spin.setValue(1.0)

        self.loop_period_spin = QSpinBox()
        self.loop_period_spin.setRange(10, 5000)
        self.loop_period_spin.setValue(100)
        self.loop_period_spin.setSuffix(" ms")
        self.derivative_tau_spin = self._double_spin(0.0, 10.0, 4, 0.01)
        self.derivative_tau_spin.setValue(0.05)
        self.derivative_tau_spin.setSuffix(" s")
        self.tc_min_spin = self._double_spin(0.0, 9999.99, 2, 1.0)
        self.tc_max_spin = self._double_spin(0.0, 9999.99, 2, 1.0)
        self.tc_min_spin.setValue(0.0)
        self.tc_max_spin.setValue(800.0)
        self.tc_min_spin.setSuffix(" A")
        self.tc_max_spin.setSuffix(" A")
        self.beam_stale_spin = self._double_spin(0.05, 60.0, 2, 0.1)
        self.beam_stale_spin.setValue(1.0)
        self.beam_stale_spin.setSuffix(" s")

        fields = [
            ("Beam Setpoint", self.setpoint_spin, 0, 0),
            ("Kp", self.kp_spin, 0, 2),
            ("Ki", self.ki_spin, 0, 4),
            ("Kd", self.kd_spin, 0, 6),
            ("Deadband", self.deadband_spin, 1, 0),
            ("Trend Tolerance", self.trend_tolerance_spin, 1, 2),
            ("Direction Check", self.direction_check_spin, 1, 4),
            ("Initial Direction", self.initial_direction_combo, 1, 6),
            ("ΔTC Magnitude Min", self.output_min_spin, 2, 0),
            ("ΔTC Magnitude Max", self.output_max_spin, 2, 2),
            ("Integral Min", self.integral_min_spin, 2, 4),
            ("Integral Max", self.integral_max_spin, 2, 6),
            ("PID Poll Period", self.loop_period_spin, 3, 0),
            ("Derivative Filter τ", self.derivative_tau_spin, 3, 2),
            ("TC Target Min", self.tc_min_spin, 3, 4),
            ("TC Target Max", self.tc_max_spin, 3, 6),
            ("Beam Stale Limit", self.beam_stale_spin, 4, 0),
        ]
        for label_text, widget, row, col in fields:
            label = QLabel(label_text)
            label.setStyleSheet(f"color: {T.muted};")
            grid.addWidget(label, row, col)
            grid.addWidget(widget, row, col + 1)
        layout.addLayout(grid)

        behavior_row = QHBoxLayout()
        self.reset_i_deadband_check = QCheckBox("RESET INTEGRAL INSIDE DEADBAND")
        self.reset_i_reverse_check = QCheckBox("RESET INTEGRAL WHEN DIRECTION REVERSES")
        behavior_row.addWidget(self.reset_i_deadband_check)
        behavior_row.addWidget(self.reset_i_reverse_check)
        behavior_row.addStretch()
        layout.addLayout(behavior_row)

        component_grid = QGridLayout()
        self.output_display = self._component_display(T.cyan)
        self.magnitude_display = self._component_display(T.amber)
        self.p_display = self._component_display(T.text)
        self.i_display = self._component_display(T.text)
        self.d_display = self._component_display(T.text)
        for col, (name, display) in enumerate(
            (
                ("SIGNED ΔTC", self.output_display),
                ("PID MAGNITUDE", self.magnitude_display),
                ("P(|e|)", self.p_display),
                ("I(|e|)", self.i_display),
                ("D(|e|)", self.d_display),
            )
        ):
            label = QLabel(name)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(f"color: {T.muted}; font-size: 11px;")
            component_grid.addWidget(label, 0, col)
            component_grid.addWidget(display, 1, col)
        layout.addLayout(component_grid)

        target_grid = QGridLayout()
        self.baseline_display = self._component_display(T.cyan)
        self.current_target_display = self._component_display(T.text)
        self.proposed_target_display = self._component_display(T.orange)
        for col, (name, display) in enumerate(
            (
                ("CAPTURED BASELINE TC TARGET", self.baseline_display),
                ("CURRENT TC TARGET", self.current_target_display),
                ("NEXT PROPOSED TC TARGET", self.proposed_target_display),
            )
        ):
            label = QLabel(name)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(f"color: {T.muted}; font-size: 11px;")
            target_grid.addWidget(label, 0, col)
            target_grid.addWidget(display, 1, col)
        layout.addLayout(target_grid)

        controls = QHBoxLayout()
        self.load_actual_button = QPushButton("LOAD ACTUAL BEAM AS SETPOINT")
        self.load_actual_button.setStyleSheet(secondary_button_css())
        self.load_actual_button.clicked.connect(self._load_actual_as_setpoint)
        controls.addWidget(self.load_actual_button)

        self.capture_baseline_button = QPushButton("CAPTURE TC BASELINE")
        self.capture_baseline_button.setStyleSheet(secondary_button_css())
        self.capture_baseline_button.clicked.connect(self._capture_baseline)
        controls.addWidget(self.capture_baseline_button)

        self.reset_button = QPushButton("RESET PID STATE")
        self.reset_button.setStyleSheet(secondary_button_css())
        self.reset_button.clicked.connect(self.reset_pid)
        controls.addWidget(self.reset_button)
        controls.addStretch()

        self.arm_output_check = QCheckBox("ARM HARDWARE OUTPUT")
        self.arm_output_check.setToolTip(
            "When checked, signed ΔTC commands are added to the selected TC target through the existing control queue."
        )
        controls.addWidget(self.arm_output_check)

        self.start_pid_button = QPushButton("START PID")
        self.start_pid_button.setStyleSheet(secondary_button_css(T.green))
        self.start_pid_button.clicked.connect(self.start_pid)
        controls.addWidget(self.start_pid_button)

        self.stop_pid_button = QPushButton("STOP PID")
        self.stop_pid_button.setStyleSheet(secondary_button_css(T.red))
        self.stop_pid_button.clicked.connect(self.stop_pid)
        controls.addWidget(self.stop_pid_button)
        layout.addLayout(controls)

        self.pid_status_label = QLabel("PID IDLE")
        self.pid_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pid_status_label.setStyleSheet(info_label_css())
        layout.addWidget(self.pid_status_label)
        return card

    def _build_ga_card(self) -> QWidget:
        card = Card(radius=9)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        title = QLabel("GENETIC ALGORITHM — PID GAIN SEARCH")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title)

        note = QLabel(
            "The GA engine is connected, but plant evaluation is intentionally external. START GA creates a candidate; "
            "a future test runner should apply it, collect the response, and submit a lower-is-better fitness score. "
            "The development score input below lets you exercise that interface manually now."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {T.muted};")
        layout.addWidget(note)

        config_grid = QGridLayout()
        config_grid.setHorizontalSpacing(10)
        config_grid.setVerticalSpacing(7)

        self.population_spin = QSpinBox()
        self.population_spin.setRange(4, 500)
        self.population_spin.setValue(18)
        self.generations_spin = QSpinBox()
        self.generations_spin.setRange(1, 500)
        self.generations_spin.setValue(25)

        self.kp_min_spin = self._double_spin(0.0, 1_000_000.0, 6, 0.01)
        self.kp_max_spin = self._double_spin(0.0, 1_000_000.0, 6, 0.01)
        self.ki_min_spin = self._double_spin(0.0, 1_000_000.0, 6, 0.01)
        self.ki_max_spin = self._double_spin(0.0, 1_000_000.0, 6, 0.01)
        self.kd_min_spin = self._double_spin(0.0, 1_000_000.0, 6, 0.001)
        self.kd_max_spin = self._double_spin(0.0, 1_000_000.0, 6, 0.001)
        self.kp_max_spin.setValue(10.0)
        self.ki_max_spin.setValue(5.0)
        self.kd_max_spin.setValue(2.0)

        ga_fields = [
            ("Population", self.population_spin, 0, 0),
            ("Generations", self.generations_spin, 0, 2),
            ("Kp Min", self.kp_min_spin, 1, 0),
            ("Kp Max", self.kp_max_spin, 1, 2),
            ("Ki Min", self.ki_min_spin, 2, 0),
            ("Ki Max", self.ki_max_spin, 2, 2),
            ("Kd Min", self.kd_min_spin, 3, 0),
            ("Kd Max", self.kd_max_spin, 3, 2),
        ]
        for text, widget, row, col in ga_fields:
            label = QLabel(text)
            label.setStyleSheet(f"color: {T.muted};")
            config_grid.addWidget(label, row, col)
            config_grid.addWidget(widget, row, col + 1)
        layout.addLayout(config_grid)

        progress_grid = QGridLayout()
        self.ga_generation_display = self._component_display(T.cyan)
        self.ga_candidate_display = self._component_display(T.cyan)
        self.ga_current_display = self._component_display(T.text)
        self.ga_best_display = self._component_display(T.green)
        progress_items = [
            ("GENERATION", self.ga_generation_display),
            ("CANDIDATE", self.ga_candidate_display),
            ("CURRENT GAINS", self.ga_current_display),
            ("BEST", self.ga_best_display),
        ]
        for col, (text, display) in enumerate(progress_items):
            label = QLabel(text)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(f"color: {T.muted}; font-size: 11px;")
            progress_grid.addWidget(label, 0, col)
            progress_grid.addWidget(display, 1, col)
        layout.addLayout(progress_grid)

        controls = QHBoxLayout()
        self.start_ga_button = QPushButton("START GA")
        self.start_ga_button.setStyleSheet(secondary_button_css(T.green))
        self.start_ga_button.clicked.connect(self.start_ga)
        controls.addWidget(self.start_ga_button)

        self.abort_ga_button = QPushButton("ABORT GA")
        self.abort_ga_button.setStyleSheet(secondary_button_css(T.red))
        self.abort_ga_button.clicked.connect(self.abort_ga)
        controls.addWidget(self.abort_ga_button)

        controls.addStretch()
        score_label = QLabel("Development Fitness")
        score_label.setStyleSheet(f"color: {T.muted};")
        controls.addWidget(score_label)
        self.fitness_spin = self._double_spin(0.0, 1.0e12, 6, 1.0)
        self.fitness_spin.setValue(100.0)
        controls.addWidget(self.fitness_spin)

        self.submit_fitness_button = QPushButton("SUBMIT SCORE")
        self.submit_fitness_button.setStyleSheet(secondary_button_css(T.amber))
        self.submit_fitness_button.clicked.connect(
            lambda: self.submit_candidate_fitness(self.fitness_spin.value())
        )
        controls.addWidget(self.submit_fitness_button)

        self.apply_best_button = QPushButton("APPLY BEST GAINS")
        self.apply_best_button.setStyleSheet(secondary_button_css(T.cyan))
        self.apply_best_button.clicked.connect(self.apply_best_gains)
        controls.addWidget(self.apply_best_button)
        layout.addLayout(controls)

        self.ga_status_label = QLabel("GA IDLE")
        self.ga_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ga_status_label.setStyleSheet(info_label_css())
        layout.addWidget(self.ga_status_label)
        return card

    @staticmethod
    def _double_spin(
        minimum: float,
        maximum: float,
        decimals: int,
        step: float,
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(float(minimum), float(maximum))
        spin.setDecimals(int(decimals))
        spin.setSingleStep(float(step))
        spin.setKeyboardTracking(False)
        return spin

    @staticmethod
    def _component_display(color: str) -> QLabel:
        label = QLabel("—")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumHeight(34)
        label.setStyleSheet(
            f"color: {color}; background: #0E151A; border: 1px solid #27323A; "
            "border-radius: 6px; padding: 5px; font-size: 13px; font-weight: 600;"
        )
        return label

    # ------------------------------------------------------------ Context
    def _connect_context(self) -> None:
        self.context.target_changed.connect(self._on_target_changed)
        self.context.beam_measurement_changed.connect(
            lambda _sample: self._refresh_live_readouts()
        )
        self.context.mode_changed.connect(self._on_mode_changed)

    def _on_actuator_selector_changed(self, index: int) -> None:
        if index < 0 or index == self._actuator_index:
            return
        if self._pid_running:
            self.stop_pid(reason="PID STOPPED — ACTUATOR CHANGED")
        self._actuator_index = int(index)
        self._pid_channel = self._actuator_index
        self._baseline_target = float("nan")
        self._last_proposed_target = float("nan")
        self._reset_plot()
        self.refresh()

    def _on_target_changed(self, index: int, _value: float) -> None:
        if int(index) == self._actuator_index:
            self._refresh_live_readouts()

    def _on_mode_changed(self, mode: str) -> None:
        if self._pid_running and mode != ControlMode.PID.value:
            self.stop_pid(
                reason=f"PID STOPPED — MODE CHANGED TO {mode}",
                restore_manual=False,
            )

    def refresh(self) -> None:
        if hasattr(self, "actuator_selector"):
            self.actuator_selector.blockSignals(True)
            self.actuator_selector.setCurrentIndex(self._actuator_index)
            self.actuator_selector.blockSignals(False)
        self._refresh_live_readouts()
        self._refresh_ga_progress()

    def _beam_stale_limit(self) -> float:
        if hasattr(self, "beam_stale_spin"):
            return max(0.05, float(self.beam_stale_spin.value()))
        return 1.0

    def _beam_value(self) -> float:
        return self.context.beam_current(max_age_s=self._beam_stale_limit())

    def _load_actual_as_setpoint(self) -> None:
        actual = self._beam_value()
        if not math.isfinite(actual):
            self.pid_status_label.setText(
                "SETPOINT NOT LOADED — VALID BEAM FEEDBACK IS NOT AVAILABLE"
            )
            return
        self.setpoint_spin.setValue(actual)
        self._refresh_live_readouts()

    def _capture_baseline(self) -> None:
        self._baseline_target = self.context.target(self._actuator_index)
        self.baseline_display.setText(f"{self._baseline_target:.2f} A")
        self.pid_status_label.setText(
            f"BASELINE CAPTURED — {self.context.channel_name(self._actuator_index)} "
            f"= {self._baseline_target:.2f} A"
        )

    @staticmethod
    def _direction_text(direction: int) -> str:
        return "+1  INCREASE TC" if int(direction) >= 0 else "−1  DECREASE TC"

    def _set_trend_display(self, trend: str) -> None:
        """Make the absolute-error decision visually unambiguous."""
        text = str(trend or "UNKNOWN").upper()
        if text == "DECREASING":
            color = T.green
        elif text == "INCREASING":
            color = T.red
        elif text == "DEADBAND":
            color = T.cyan
        elif text in ("STEADY", "INITIALIZING", "SETPOINT CHANGED"):
            color = T.amber
        else:
            color = T.text
        self.trend_display.setText(text)
        self.trend_display.setStyleSheet(
            f"color: {color}; font-size: 21px; font-weight: 600;"
        )

    def _refresh_live_readouts(self) -> None:
        if not hasattr(self, "actuator_display"):
            return

        actuator_name = self.context.channel_name(self._actuator_index)
        self.controlled_display.setText("BEAM CURRENT")
        self.actuator_display.setText(actuator_name)
        setpoint = self.setpoint_spin.value()
        self.setpoint_display.setText(f"{setpoint:.4f} nA")

        snapshot = self.context.beam_snapshot(max_age_s=self._beam_stale_limit())
        actual = float(snapshot.get("value_nA", float("nan")))
        if bool(snapshot.get("valid")) and math.isfinite(actual):
            self.actual_display.setText(f"{actual:.4f} nA")
            signed_error = setpoint - actual
            magnitude = abs(signed_error)
            self.error_display.setText(f"{signed_error:+.4f} nA")
            self.abs_error_display.setText(f"{magnitude:.4f} nA")
            self.beam_source_status.setText(
                f"{snapshot.get('status', 'LIVE')}  |  {float(snapshot.get('age_s', 0.0)):.2f} s"
            )
            self.beam_source_status.setStyleSheet(
                f"color: {T.green}; font-size: 14px; font-weight: 600;"
            )
        else:
            self.actual_display.setText("—")
            self.error_display.setText("—")
            self.abs_error_display.setText("—")
            self.beam_source_status.setText(str(snapshot.get("status", "NO DATA")))
            self.beam_source_status.setStyleSheet(
                f"color: {T.red}; font-size: 14px; font-weight: 600;"
            )

        result = self.pid.last_result
        if self._pid_running:
            self._set_trend_display(result.error_trend)
            self.direction_display.setText(self._direction_text(result.direction))
        else:
            self._set_trend_display("IDLE")
            direction = int(self.initial_direction_combo.currentData())
            self.direction_display.setText(self._direction_text(direction))

        current_target = self.context.target(self._actuator_index)
        self.current_target_display.setText(f"{current_target:.2f} A")
        if math.isfinite(self._baseline_target):
            self.baseline_display.setText(f"{self._baseline_target:.2f} A")
        else:
            self.baseline_display.setText("—")
        if math.isfinite(self._last_proposed_target):
            self.proposed_target_display.setText(
                f"{self._last_proposed_target:.2f} A"
            )
        else:
            self.proposed_target_display.setText(f"{current_target:.2f} A")

    # --------------------------------------------------------------- PID
    def _pid_settings(
        self,
    ) -> tuple[PIDGains, PIDLimits, AdaptiveDirectionSettings]:
        gains = PIDGains(
            kp=self.kp_spin.value(),
            ki=self.ki_spin.value(),
            kd=self.kd_spin.value(),
        )
        limits = PIDLimits(
            output_min=self.output_min_spin.value(),
            output_max=self.output_max_spin.value(),
            integral_min=self.integral_min_spin.value(),
            integral_max=self.integral_max_spin.value(),
            derivative_filter_tau=self.derivative_tau_spin.value(),
        )
        settings = AdaptiveDirectionSettings(
            deadband=self.deadband_spin.value(),
            trend_tolerance=self.trend_tolerance_spin.value(),
            direction_check_interval=self.direction_check_spin.value(),
            initial_direction=int(self.initial_direction_combo.currentData()),
            reset_integral_in_deadband=self.reset_i_deadband_check.isChecked(),
            reset_integral_on_direction_change=self.reset_i_reverse_check.isChecked(),
        )
        return gains, limits, settings

    def start_pid(self) -> None:
        actual = self._beam_value()
        if not math.isfinite(actual):
            self.pid_status_label.setText(
                "PID NOT STARTED — CALIBRATED BEAM FEEDBACK IS NOT AVAILABLE OR IS STALE"
            )
            return
        if not 0 <= self._actuator_index < 12:
            self.pid_status_label.setText("PID NOT STARTED — SELECT TC1 THROUGH TC12")
            return
        if self.tc_min_spin.value() >= self.tc_max_spin.value():
            self.pid_status_label.setText(
                "PID NOT STARTED — TC TARGET MIN MUST BE BELOW TC TARGET MAX"
            )
            return
        if self.output_min_spin.value() > self.output_max_spin.value():
            self.pid_status_label.setText(
                "PID NOT STARTED — ΔTC MAGNITUDE MIN EXCEEDS MAX"
            )
            return
        if self.integral_min_spin.value() > self.integral_max_spin.value():
            self.pid_status_label.setText(
                "PID NOT STARTED — INTEGRAL MIN EXCEEDS MAX"
            )
            return

        try:
            gains, limits, settings = self._pid_settings()
            self.pid.set_gains(gains)
            self.pid.set_limits(limits)
            self.pid.set_settings(settings)
        except ValueError as exc:
            self.pid_status_label.setText(f"PID NOT STARTED — {exc}")
            return

        self._pid_channel = self._actuator_index
        self.context.set_target_limits(
            self._pid_channel,
            self.tc_min_spin.value(),
            self.tc_max_spin.value(),
        )
        self._baseline_target = self.context.target(self._pid_channel)
        self._last_proposed_target = self._baseline_target
        self.pid.reset(
            setpoint=self.setpoint_spin.value(),
            measurement=actual,
            direction=settings.initial_direction,
        )
        self._last_pid_time = time.monotonic()
        self._last_processed_beam_timestamp = 0.0
        self._pid_timer.setInterval(self.loop_period_spin.value())
        self._pid_running = True
        self.context.set_mode(ControlMode.PID)
        self._reset_plot()
        self._pid_timer.start()
        self.actuator_selector.setEnabled(False)
        self.initial_direction_combo.setEnabled(False)

        if self.arm_output_check.isChecked() and self.output_callback is None:
            self.pid_status_label.setText(
                "PID PREVIEW ACTIVE — NO HARDWARE CALLBACK CONNECTED"
            )
        elif self.arm_output_check.isChecked():
            self.pid_status_label.setText(
                "PID ACTIVE — HARDWARE OUTPUT ARMED — ADAPTIVE DIRECTION INITIALIZING"
            )
        else:
            self.pid_status_label.setText(
                "PID PREVIEW ACTIVE — HARDWARE OUTPUT BLOCKED — ADAPTIVE DIRECTION INITIALIZING"
            )
        self._refresh_live_readouts()

    def stop_pid(
        self,
        *,
        reason: str = "PID STOPPED",
        restore_manual: bool = True,
    ) -> None:
        self._pid_timer.stop()
        self._pid_running = False
        self._last_processed_beam_timestamp = 0.0
        if hasattr(self, "actuator_selector"):
            self.actuator_selector.setEnabled(True)
        if hasattr(self, "initial_direction_combo"):
            self.initial_direction_combo.setEnabled(True)
        self.pid_status_label.setText(reason)
        if restore_manual and self.context.can_write(ControlMode.PID):
            self.context.set_mode(ControlMode.MANUAL)
        self._refresh_live_readouts()

    def reset_pid(self) -> None:
        actual = self._beam_value()
        direction = int(self.initial_direction_combo.currentData())
        self.pid.reset(
            setpoint=self.setpoint_spin.value() if math.isfinite(actual) else None,
            measurement=actual if math.isfinite(actual) else None,
            direction=direction,
        )
        self.output_display.setText("0.0000 A")
        self.magnitude_display.setText("0.0000 A")
        self.p_display.setText("0.0000")
        self.i_display.setText("0.0000")
        self.d_display.setText("0.0000")
        self._last_proposed_target = self.context.target(self._actuator_index)
        self.pid_status_label.setText("PID STATE RESET")
        self._refresh_live_readouts()

    def _pid_step(self) -> None:
        if not self._pid_running:
            return
        if not self.context.can_write(ControlMode.PID):
            self.stop_pid(
                reason="PID STOPPED — CONTROL MODE LOST",
                restore_manual=False,
            )
            return
        if self._actuator_index != self._pid_channel:
            self.stop_pid(reason="PID STOPPED — ACTUATOR CHANGED")
            return

        now = time.monotonic()
        snapshot = self.context.beam_snapshot(max_age_s=self._beam_stale_limit())
        actual = float(snapshot.get("value_nA", float("nan")))
        sample_timestamp = float(snapshot.get("timestamp", 0.0))
        if not bool(snapshot.get("valid")) or not math.isfinite(actual):
            self.stop_pid(reason="PID STOPPED — BEAM FEEDBACK LOST OR STALE")
            return

        # Execute the control law once per genuinely new beam sample.  The main
        # GUI can display/poll faster than its packet fan-out, so reusing the same
        # sample here would otherwise apply several TC increments with no new
        # evidence about whether |error| improved or worsened.
        if (
            sample_timestamp <= 0.0
            or math.isclose(
                sample_timestamp,
                self._last_processed_beam_timestamp,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        ):
            return

        if self._last_processed_beam_timestamp > 0.0:
            dt = max(1e-6, sample_timestamp - self._last_processed_beam_timestamp)
        else:
            # The first available sample has no prior receive timestamp in this
            # PID run.  Use the configured poll period only for that first step.
            dt = max(1e-6, self.loop_period_spin.value() / 1000.0)
        self._last_processed_beam_timestamp = sample_timestamp
        self._last_pid_time = now

        # Permit deliberate live gain/deadband changes while running, while the
        # adaptive direction state itself remains intact.
        try:
            gains, limits, settings = self._pid_settings()
            self.pid.set_gains(gains)
            self.pid.set_limits(limits)
            self.pid.set_settings(settings)
            result = self.pid.update(self.setpoint_spin.value(), actual, dt)
        except ValueError as exc:
            self.stop_pid(reason=f"PID STOPPED — {exc}")
            return

        self.output_display.setText(f"{result.output:+.4f} A")
        self.magnitude_display.setText(f"{result.pid_magnitude:.4f} A")
        self.p_display.setText(f"{result.proportional:.6f}")
        self.i_display.setText(f"{result.integral:.6f}")
        self.d_display.setText(f"{result.derivative:.6f}")
        self.error_display.setText(f"{result.error:+.4f} nA")
        self.abs_error_display.setText(f"{result.error_magnitude:.4f} nA")
        self._set_trend_display(result.error_trend)
        self.direction_display.setText(self._direction_text(result.direction))

        current_target = self.context.target(self._pid_channel)
        requested_target = current_target + result.output
        proposed_target = self.context.clamp_target(
            self._pid_channel, requested_target
        )
        self._last_proposed_target = proposed_target
        self.current_target_display.setText(f"{current_target:.2f} A")
        self.proposed_target_display.setText(f"{proposed_target:.2f} A")

        elapsed = now - self._plot_t0
        self._plot_t.append(elapsed)
        self._plot_setpoint.append(self.setpoint_spin.value())
        self._plot_actual.append(actual)
        self._plot_abs_error.append(result.error_magnitude)
        self._plot_deadband.append(self.deadband_spin.value())
        self.plot.set_data(
            self._plot_t,
            self._plot_setpoint,
            self._plot_actual,
        )
        self.error_plot.set_data(
            self._plot_t,
            self._plot_deadband,
            self._plot_abs_error,
        )

        self.pid_output_calculated.emit(
            self._pid_channel, result.output, result
        )

        output_mode = "PID PREVIEW ACTIVE"
        if self.arm_output_check.isChecked() and self.output_callback is not None:
            try:
                accepted = self.output_callback(
                    self._pid_channel, result.output, result
                )
            except Exception as exc:  # pragma: no cover - hardware boundary
                self.stop_pid(
                    reason=f"PID STOPPED — OUTPUT CALLBACK FAILED: {exc}"
                )
                return
            if accepted is False:
                self.stop_pid(
                    reason="PID STOPPED — OUTPUT CALLBACK REJECTED COMMAND"
                )
                return
            output_mode = "PID ACTIVE — OUTPUT ARMED"
            self.current_target_display.setText(
                f"{self.context.target(self._pid_channel):.2f} A"
            )
        elif self.arm_output_check.isChecked():
            output_mode = "PID PREVIEW ACTIVE — NO HARDWARE CALLBACK"

        flags = [output_mode, f"d={result.direction:+d}", f"|e| {result.error_trend}"]
        if result.in_deadband:
            flags.append("TARGET HELD IN DEADBAND")
        if result.direction_changed:
            flags.append("DIRECTION REVERSED")
        if result.saturated:
            flags.append("PID MAGNITUDE LIMITED")
        self.pid_status_label.setText(" — ".join(flags))

    def _reset_plot(self) -> None:
        self._plot_t0 = time.monotonic()
        self._plot_t.clear()
        self._plot_setpoint.clear()
        self._plot_actual.clear()
        self._plot_abs_error.clear()
        self._plot_deadband.clear()
        if hasattr(self, "plot"):
            self.plot.clear()
        if hasattr(self, "error_plot"):
            self.error_plot.clear()

    def _refresh_ga_context(self) -> None:
        if hasattr(self, "ga_channel_display"):
            self.ga_channel_display.setText(
                self.context.channel_name(self._actuator_index)
            )
        if hasattr(self, "ga_seed_display") and all(
            hasattr(self, name) for name in ("kp_spin", "ki_spin", "kd_spin")
        ):
            self.ga_seed_display.setText(
                f"{self.kp_spin.value():.6g}, {self.ki_spin.value():.6g}, {self.kd_spin.value():.6g}"
            )

    # ---------------------------------------------------------------- GA
    def _reset_ga_plot(self) -> None:
        self._ga_evaluation_count = 0
        self._ga_evaluations.clear()
        self._ga_fitness_history.clear()
        self._ga_best_history.clear()
        if hasattr(self, "ga_plot"):
            self.ga_plot.clear()
        if hasattr(self, "ga_last_fitness_display"):
            self.ga_last_fitness_display.setText("—")
        if hasattr(self, "ga_best_fitness_plot_display"):
            self.ga_best_fitness_plot_display.setText("—")

    def _record_ga_fitness(self, fitness: float) -> None:
        score = float(fitness)
        if not math.isfinite(score):
            return

        self._ga_evaluation_count += 1
        self._ga_evaluations.append(float(self._ga_evaluation_count))
        self._ga_fitness_history.append(score)

        best_score = score
        if self.ga_tuner is not None:
            best = self.ga_tuner.best_candidate()
            if best is not None and best.fitness is not None:
                candidate_best = float(best.fitness)
                if math.isfinite(candidate_best):
                    best_score = candidate_best
        self._ga_best_history.append(best_score)

        self.ga_last_fitness_display.setText(f"{score:.6g}")
        self.ga_best_fitness_plot_display.setText(f"{best_score:.6g}")
        self.ga_plot.set_data(
            self._ga_evaluations,
            self._ga_best_history,
            self._ga_fitness_history,
        )

    def _ga_configuration(self) -> tuple[GainBounds, GATuningConfig]:
        bounds = GainBounds(
            kp=(self.kp_min_spin.value(), self.kp_max_spin.value()),
            ki=(self.ki_min_spin.value(), self.ki_max_spin.value()),
            kd=(self.kd_min_spin.value(), self.kd_max_spin.value()),
        ).validated()
        config = GATuningConfig(
            population_size=self.population_spin.value(),
            generations=self.generations_spin.value(),
        ).validated()
        return bounds, config

    def start_ga(self) -> None:
        if self._pid_running:
            self.stop_pid(reason="PID STOPPED — GA TUNING STARTED", restore_manual=False)
        try:
            bounds, config = self._ga_configuration()
            self.ga_tuner = GAPIDTuner(bounds=bounds, config=config)
            candidate = self.ga_tuner.initialize(
                PIDGains(self.kp_spin.value(), self.ki_spin.value(), self.kd_spin.value())
            )
        except (ValueError, RuntimeError) as exc:
            self.ga_status_label.setText(f"GA NOT STARTED — {exc}")
            return

        self._reset_ga_plot()
        self.context.set_mode(ControlMode.GA_TUNING)
        self._present_candidate(candidate)
        self.ga_status_label.setText(
            "GA READY — APPLY/TEST CURRENT CANDIDATE, THEN SUBMIT ITS FITNESS"
        )

    def abort_ga(self) -> None:
        self.ga_tuner = None
        self.ga_status_label.setText("GA ABORTED")
        self._refresh_ga_progress()
        if self.context.can_write(ControlMode.GA_TUNING):
            self.context.set_mode(ControlMode.MANUAL)

    def submit_candidate_fitness(self, fitness: float) -> None:
        if self.ga_tuner is None:
            self.ga_status_label.setText("START GA BEFORE SUBMITTING FITNESS")
            return
        try:
            next_candidate = self.ga_tuner.submit_fitness(float(fitness))
        except RuntimeError as exc:
            self.ga_status_label.setText(str(exc).upper())
            return

        self._record_ga_fitness(float(fitness))

        if self.ga_tuner.finished:
            best = self.ga_tuner.best_candidate()
            if best is None:
                self.ga_status_label.setText("GA FINISHED — NO VALID CANDIDATE")
            else:
                self.ga_status_label.setText(
                    f"GA COMPLETE — BEST FITNESS {float(best.fitness):.6g}"
                )
            self.context.set_mode(ControlMode.MANUAL)
            self._refresh_ga_progress()
            return

        if next_candidate is not None:
            self._present_candidate(next_candidate)
            self.ga_status_label.setText("NEXT CANDIDATE READY — AWAITING FITNESS")

    def _present_candidate(self, candidate: PIDCandidate) -> None:
        self.kp_spin.setValue(candidate.gains.kp)
        self.ki_spin.setValue(candidate.gains.ki)
        self.kd_spin.setValue(candidate.gains.kd)
        self._refresh_ga_progress()
        self.candidate_requested.emit(candidate)

    def apply_best_gains(self) -> None:
        if self.ga_tuner is None or self.ga_tuner.best_candidate() is None:
            self.ga_status_label.setText("NO EVALUATED GA CANDIDATE IS AVAILABLE")
            return
        best = self.ga_tuner.best_candidate()
        assert best is not None
        self.kp_spin.setValue(best.gains.kp)
        self.ki_spin.setValue(best.gains.ki)
        self.kd_spin.setValue(best.gains.kd)
        self.ga_status_label.setText(
            f"BEST GAINS LOADED — Kp={best.gains.kp:.6g}, Ki={best.gains.ki:.6g}, Kd={best.gains.kd:.6g}"
        )

    def _refresh_ga_progress(self) -> None:
        if self.ga_tuner is None:
            self.ga_generation_display.setText("—")
            self.ga_candidate_display.setText("—")
            self.ga_current_display.setText("—")
            self.ga_best_display.setText("—")
            return

        generation, generations, candidate, population = self.ga_tuner.progress()
        self.ga_generation_display.setText(f"{generation} / {generations}")
        self.ga_candidate_display.setText(f"{candidate} / {population}")
        try:
            current = self.ga_tuner.current_candidate()
            self.ga_current_display.setText(
                f"{current.gains.kp:.3g}, {current.gains.ki:.3g}, {current.gains.kd:.3g}"
            )
        except RuntimeError:
            self.ga_current_display.setText("COMPLETE")

        best = self.ga_tuner.best_candidate()
        if best is None:
            self.ga_best_display.setText("—")
        else:
            self.ga_best_display.setText(
                f"{float(best.fitness):.4g} | {best.gains.kp:.3g}, {best.gains.ki:.3g}, {best.gains.kd:.3g}"
            )


__all__ = ["PIDGAControlTab", "PIDOutputCallback"]
