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
from copy import deepcopy
from source.Python.Data.file_writer import file_writer, write_text
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QBrush, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
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

from python.app.widgets.ScreenSafeComboBox import ScreenSafeComboBox as QComboBox

from python.app.Automation.GA.ControllerContext import ControlMode, ControllerContext
from python.app.Automation.GA.Theme import (
    Card,
    T,
    TeslaTabBar,
    info_label_css,
    secondary_button_css,
)
from python.app.Automation.GA.TrendPlot import AxisTrendPlot as TrendPlot
from source.Python.Optimization.genetic_optimizer import GAPIDTuner, GATuningConfig, GainBounds, PIDCandidate
from source.Python.Automation.ga_evaluation import (
    GACandidateEvaluator,
    GAEvaluationConfig,
    GAEvaluationResult,
    GAFitnessWeights,
    append_summary_csv,
    write_evaluation_csv,
)
from source.Python.Automation.ga_recovery import (
    GARecoveryConfig,
    GARecoveryManager,
    GARecoveryReference,
)
from source.Python.Control.NLAPID import (
    NLAPID as AdaptiveDirectionPIDController,
    AdaptiveDirectionSettings,
    PIDGains,
    PIDLimits,
    PIDResult,
)


PIDOutputCallback = Callable[[int, float, PIDResult], bool | None]


class _DisabledPIDLogger:
    """No-op replacement used while PID SQLite recording is disabled.

    It intentionally creates no thread, opens no database, and writes no files.
    The small interface mirrors the real logger so the PID/GA code remains
    unchanged and logging can be restored later without touching the controller.
    """

    db_path = "PID SQLite logging disabled"
    dropped_records = 0

    @staticmethod
    def utc_now_text() -> str:
        return ""

    @staticmethod
    def new_session_id(_prefix: str = "PID") -> None:
        return None

    @staticmethod
    def log_event(*_args, **_kwargs) -> bool:
        return False

    @staticmethod
    def log_sample(*_args, **_kwargs) -> bool:
        return False

    @staticmethod
    def close() -> None:
        return None

    @staticmethod
    def status() -> dict:
        return {
            "disabled": True,
            "last_error": "",
            "db_path": "PID SQLite logging disabled",
            "sample_rate_hz": 0.0,
            "dropped": 0,
            "written_samples": 0,
            "skipped": 0,
            "queued": 0,
        }


class NoWheelComboBox(QComboBox):
    """Combo box that cannot change selection from the mouse wheel.

    A normal ``QComboBox`` changes its current item when the pointer is over the
    widget and the mouse wheel is moved. That behavior is convenient for
    ordinary forms, but it is unsafe for selecting a live trim-coil actuator.
    The operator must open the list deliberately and then press the separate
    confirmation button before the active PID actuator is changed.
    """

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API name
        event.ignore()


class PIDGainRadar(QWidget):
    """Compact Tesla-style radar chart for Kp, Ki and Kd.

    Each axis uses its own engineering display scale so small Ki/Kd values are
    still visible next to Kp. The numeric values and scale limits are drawn on
    the chart, so the visualization never hides the real gain magnitudes.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._values = [0.0, 0.0, 0.0]
        self._base_scales = [0.05, 0.001, 0.001]
        self.setMinimumSize(170, 170)

    def set_gains(self, kp: float, ki: float, kd: float) -> None:
        self._values = [max(0.0, float(kp)), max(0.0, float(ki)), max(0.0, float(kd))]
        self.update()

    def _scales(self) -> list[float]:
        scales = []
        for base, value in zip(self._base_scales, self._values):
            scales.append(max(base, value * 1.25, 1e-12))
        return scales

    @staticmethod
    def _point(cx: float, cy: float, radius: float, angle_deg: float) -> QPointF:
        a = math.radians(angle_deg)
        return QPointF(cx + radius * math.cos(a), cy + radius * math.sin(a))

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(T.panel))

        w, h = self.width(), self.height()
        cx, cy = w * 0.50, h * 0.52
        radius = max(36.0, min(w, h) * 0.34)
        angles = [-90.0, 30.0, 150.0]  # Kp, Kd, Ki

        # Tesla-style grid: restrained gray lines, no purple/magenta accents.
        grid_pen = QPen(QColor(T.border), 1)
        painter.setPen(grid_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for fraction in (0.25, 0.50, 0.75, 1.0):
            poly = QPolygonF([self._point(cx, cy, radius * fraction, a) for a in angles])
            poly.append(poly[0])
            painter.drawPolyline(poly)
        for a in angles:
            painter.drawLine(QPointF(cx, cy), self._point(cx, cy, radius, a))

        scales = self._scales()
        normalized = [min(1.0, v / sc) for v, sc in zip(self._values, scales)]
        # angles correspond Kp, Kd, Ki; reorder normalized from Kp, Ki, Kd.
        ordered = [normalized[0], normalized[2], normalized[1]]
        data_poly = QPolygonF([
            self._point(cx, cy, radius * value, angle)
            for value, angle in zip(ordered, angles)
        ])
        data_poly.append(data_poly[0])
        fill = QColor(T.cyan)
        fill.setAlpha(55)
        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(QColor(T.cyan_bright), 2))
        painter.drawPolygon(data_poly)

        painter.setBrush(QBrush(QColor(T.orange)))
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(3):
            painter.drawEllipse(data_poly[i], 4.0, 4.0)

        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        painter.setPen(QColor(T.text))
        labels = [("Kp", angles[0]), ("Kd", angles[1]), ("Ki", angles[2])]
        for text, a in labels:
            pt = self._point(cx, cy, radius + 20, a)
            painter.drawText(int(pt.x() - 14), int(pt.y() - 8), 28, 18,
                             int(Qt.AlignmentFlag.AlignCenter), text)

        painter.setFont(QFont("Segoe UI", 7))
        painter.setPen(QColor(T.dim))
        scale_text = f"axis max: Kp {scales[0]:.3g}   Ki {scales[1]:.3g}   Kd {scales[2]:.3g}"
        painter.drawText(6, h - 20, w - 12, 16, int(Qt.AlignmentFlag.AlignCenter), scale_text)


class PIDGAControlTab(QWidget):
    """Nested PID and GA pages with independent graphs and shared controller context."""

    candidate_requested = Signal(object)
    pid_output_calculated = Signal(int, float, object)

    def __init__(
        self,
        context: ControllerContext,
        output_callback: PIDOutputCallback | None = None,
        parent: QWidget | None = None,
        pid_engine=None,
    ):
        super().__init__(parent)
        self.context = context
        self.output_callback = output_callback

        self.pid = pid_engine if pid_engine is not None else AdaptiveDirectionPIDController()
        self.ga_tuner: GAPIDTuner | None = None
        self._pid_running = False
        self._actuator_index = min(9, max(0, len(self.context.channel_names) - 1))
        # The combo box is only a pending choice. ``_actuator_index`` remains
        # the active actuator until the operator presses APPLY TC SELECTION.
        self._pending_actuator_index = self._actuator_index
        self._pid_channel = self._actuator_index
        self._last_pid_time = 0.0
        # The GUI may poll faster than the beam packet stream.  Track the last
        # processed receive timestamp so one beam sample can produce at most one
        # PID/TC command; otherwise the same held measurement could be integrated
        # and applied repeatedly before the plant has supplied new feedback.
        self._last_processed_beam_timestamp = 0.0
        self._baseline_target = float("nan")
        self._last_proposed_target = float("nan")

        # PID SQLite recording is temporarily disabled for performance testing.
        # This no-op object creates no thread, process, queue, or database file.
        # The existing PID and GA control paths are otherwise unchanged.
        self.pid_logger = _DisabledPIDLogger()
        self._pid_log_session_id: str | None = None
        self._pid_log_t0 = 0.0
        self._pid_log_sample_index = 0
        self._pid_log_last_record_mono = 0.0
        self._pid_log_interval_s = 0.20
        self.destroyed.connect(
            lambda _obj=None, logger=self.pid_logger: logger.close()
        )

        self._plot_t0 = time.monotonic()
        self._plot_t = deque(maxlen=1000)
        self._plot_setpoint = deque(maxlen=1000)
        self._plot_actual = deque(maxlen=1000)
        self._plot_abs_error = deque(maxlen=1000)
        self._plot_deadband = deque(maxlen=1000)
        self._plot_tc_target = deque(maxlen=1000)
        self._plot_tc_actual = deque(maxlen=1000)

        # GA history is intentionally independent from the PID response plot.
        # Each submitted candidate contributes one point: candidate fitness and
        # best-so-far fitness versus evaluation number.
        self._ga_evaluation_count = 0
        self._ga_evaluations = deque(maxlen=1000)
        self._ga_fitness_history = deque(maxlen=1000)
        self._ga_best_history = deque(maxlen=1000)
        self._ga_safety_history = deque(maxlen=1000)
        # The GA graph may subtract a labelled common offset when full scores
        # are tightly clustered (for example near the 1,000,000 safety
        # penalty).  The genetic algorithm and CSV logs always keep the full
        # unmodified score.
        self._ga_plot_offset = 0.0

        # Live candidate-response traces are separate from the one-point-per-
        # candidate fitness history.  They update on every new beam sample and
        # continue through baseline/reference recovery so the operator can see
        # exactly why a candidate is progressing, being penalized, or waiting.
        self._ga_live_t0 = time.monotonic()
        self._ga_live_t = deque(maxlen=2500)
        self._ga_live_setpoint = deque(maxlen=2500)
        self._ga_live_beam = deque(maxlen=2500)
        self._ga_live_abs_error = deque(maxlen=2500)
        self._ga_live_deadband = deque(maxlen=2500)
        self._ga_live_tc_target = deque(maxlen=2500)
        self._ga_live_tc_actual = deque(maxlen=2500)

        # A known-good recovery profile can contain only the active actuator or
        # every powered/enabled trim coil.  The pure manager is isolated from Qt
        # and hardware; this page only captures references and routes its one
        # bounded command per tick through the existing armed output callback.
        self.ga_recovery_manager = GARecoveryManager()
        self._ga_recovery_reference: GARecoveryReference | None = None

        # Automatic GA evaluation is implemented as a small supervisory state
        # machine.  The evaluator itself lives in ga_test_runner.py and has no
        # Qt or hardware dependency; this tab only coordinates the existing PID
        # loop, baseline restoration, and candidate progression.
        self.ga_evaluator = GACandidateEvaluator()
        self._ga_auto_active = False
        self._ga_starting_pid = False
        self._ga_sequence_state = "IDLE"
        self._ga_baseline_target = float("nan")
        self._ga_baseline_beam = float("nan")
        self._ga_saved_gains: PIDGains | None = None
        self._ga_saved_target_limits: tuple[float, float] | None = None
        self._ga_pending_candidate: PIDCandidate | None = None
        self._ga_run_complete = False
        self._ga_abort_after_restore = False
        self._ga_abort_reason = ""
        self._ga_restore_started = 0.0
        self._ga_restore_stable_since: float | None = None
        self._ga_run_dir: Path | None = None
        self._ga_last_result: GAEvaluationResult | None = None

        self._build_ui()
        self._connect_context()
        self.refresh()

        self._pid_timer = QTimer(self)
        self._pid_timer.timeout.connect(self._pid_step)

        self._display_timer = QTimer(self)
        # UI/plot painting is limited to 5 Hz and only the visible PID/GA page
        # is repainted. PID calculations remain independent and still process
        # every genuinely new beam sample. This prevents plotting and label
        # updates from starving the GUI event loop.
        self._display_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._display_timer.timeout.connect(self._refresh_display)
        self._display_timer.start(200)

        self._ga_sequence_timer = QTimer(self)
        self._ga_sequence_timer.setInterval(100)
        self._ga_sequence_timer.timeout.connect(self._ga_sequence_tick)

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
        self.control_tabs.currentChanged.connect(lambda _index: self._refresh_display())
        outer.addWidget(self.control_tabs)

        # Keep the GA seed-gain readout synchronized with the gain fields that
        # remain on the PID page.
        for spin in (self.kp_spin, self.ki_spin, self.kd_spin):
            spin.valueChanged.connect(lambda _value: self._refresh_ga_context())
            spin.valueChanged.connect(lambda _value: self._refresh_pid_radar())
        self._refresh_ga_context()
        self._refresh_pid_radar()

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
        """Build the compact, no-scroll PID workspace.

        The first column is reserved for operator settings and commands.  The
        center column contains the three synchronized trend plots and receives
        most of the horizontal space so the shared time domain is easier to
        inspect.  All live monitoring/readback values are grouped into compact
        tables below the PID-gain radar in the right column.
        """
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(8, 6, 8, 8)
        outer.setSpacing(8)

        left_widget = QWidget()
        left = QVBoxLayout(left_widget)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(6)
        left.addWidget(self._build_channel_selector_card())
        left.addWidget(self._build_pid_card(), 1)

        center_widget = QWidget()
        center = QVBoxLayout(center_widget)
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(0)
        center.addWidget(self._build_plot_card(), 1)

        right_widget = QWidget()
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(6)
        right.addWidget(self._build_radar_card())
        right.addWidget(self._build_monitoring_tables_card(), 1)

        # Wider center column = wider shared time axis for all three plots.
        outer.addWidget(left_widget, 23)
        outer.addWidget(center_widget, 58)
        outer.addWidget(right_widget, 19)
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
            "GA WORKSPACE — Automatic candidate testing, baseline restoration, fitness progress, and history are isolated "
            "from the PID controller engine. Lower fitness is better. The seed gains and actuator are read from the PID CONTROL tab."
        )
        notice.setWordWrap(True)
        notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        notice.setStyleSheet(info_label_css(T.cyan))
        layout.addWidget(notice)

        layout.addWidget(self._build_ga_context_card())

        # The live candidate response is intentionally visible beside the
        # fitness history.  The fitness graph receives one point only when a
        # candidate ends; the three live plots update during warm-up, scoring,
        # safety termination, and reference recovery.
        plots_widget = QWidget()
        plots_layout = QHBoxLayout(plots_widget)
        plots_layout.setContentsMargins(0, 0, 0, 0)
        plots_layout.setSpacing(10)
        plots_layout.addWidget(self._build_ga_live_plot_card(), 7)
        plots_layout.addWidget(self._build_ga_plot_card(), 3)
        layout.addWidget(plots_widget)

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

    def _build_ga_live_plot_card(self) -> QWidget:
        """Three real-time traces for the candidate currently being tested."""
        card = Card(radius=9)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(3)

        summary = QHBoxLayout()
        summary.setSpacing(8)
        title = QLabel("LIVE GA CANDIDATE RESPONSE")
        title.setStyleSheet(
            f"color: {T.text}; font-size: 12px; font-weight: 600;"
        )
        summary.addWidget(title)
        summary.addStretch(1)
        for name, attribute, color in (
            ("CANDIDATE", "ga_live_candidate_display", T.cyan),
            ("PHASE", "ga_live_phase_display", T.amber),
            ("LIVE SCORE", "ga_live_score_display", T.green),
        ):
            label = QLabel(name)
            label.setStyleSheet(f"color: {T.muted}; font-size: 9px;")
            display = self._component_display(color)
            display.setMinimumWidth(74)
            display.setMaximumHeight(26)
            setattr(self, attribute, display)
            summary.addWidget(label)
            summary.addWidget(display)
        outer.addLayout(summary)

        self.ga_live_event_label = QLabel(
            "The live plots update when an automatic candidate begins."
        )
        self.ga_live_event_label.setWordWrap(True)
        self.ga_live_event_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ga_live_event_label.setStyleSheet(
            f"color: {T.muted}; background: #0E151A; border: 1px solid {T.border}; "
            "border-radius: 5px; padding: 4px; font-size: 10px;"
        )
        outer.addWidget(self.ga_live_event_label)

        def legend_item(text: str, color: str) -> QWidget:
            item = QWidget()
            item.setStyleSheet("background: transparent;")
            row = QHBoxLayout(item)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            swatch = QFrame()
            swatch.setFixedSize(16, 3)
            swatch.setStyleSheet(
                f"background: {color}; border: none; border-radius: 1px;"
            )
            label = QLabel(text)
            label.setStyleSheet(f"color: {T.muted}; font-size: 9px;")
            row.addWidget(swatch)
            row.addWidget(label)
            return item

        def add_plot(
            title_text: str,
            plot: TrendPlot,
            entries: tuple[tuple[str, str], ...],
        ) -> None:
            header = QWidget()
            header.setFixedHeight(21)
            header.setStyleSheet("background: #080D11;")
            row = QHBoxLayout(header)
            row.setContentsMargins(7, 0, 7, 0)
            row.setSpacing(8)
            label = QLabel(title_text)
            label.setStyleSheet(
                f"color: {T.text}; font-size: 9px; font-weight: 600;"
            )
            row.addWidget(label)
            row.addStretch(1)
            for text, color in entries:
                row.addWidget(legend_item(text, color))
            outer.addWidget(header)
            plot.setMinimumHeight(135)
            outer.addWidget(plot, 1)

        self.ga_live_beam_plot = TrendPlot(
            y_axis_label="BEAM CURRENT (nA)",
            x_axis_label="CANDIDATE / RECOVERY TIME (s)",
            target_color=T.cyan,
            actual_color=T.orange,
        )
        add_plot(
            "BEAM-CURRENT RESPONSE",
            self.ga_live_beam_plot,
            (("SETPOINT", T.cyan), ("MEASURED BEAM", T.orange)),
        )

        self.ga_live_error_plot = TrendPlot(
            y_axis_label="|ERROR| (nA)",
            x_axis_label="CANDIDATE / RECOVERY TIME (s)",
            target_color=T.green,
            actual_color=T.amber,
        )
        add_plot(
            "ABSOLUTE ERROR",
            self.ga_live_error_plot,
            (("|ERROR|", T.amber), ("DEADBAND", T.green)),
        )

        self.ga_live_tc_plot = TrendPlot(
            y_axis_label="TC CURRENT (A)",
            x_axis_label="CANDIDATE / RECOVERY TIME (s)",
            target_color=T.cyan,
            actual_color=T.orange,
        )
        add_plot(
            "ACTIVE TRIM-COIL TARGET AND READBACK",
            self.ga_live_tc_plot,
            (("TC TARGET", T.cyan), ("MEASURED TC", T.orange)),
        )
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
        self.ga_last_fitness_display.setMinimumWidth(112)
        best_label = QLabel("BEST SO FAR")
        best_label.setStyleSheet(f"color: {T.green}; font-size: 11px;")
        self.ga_best_fitness_plot_display = self._component_display(T.green)
        self.ga_best_fitness_plot_display.setMinimumWidth(112)
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

        self.ga_plot_explanation = QLabel(
            "One point is added only after a candidate finishes. Orange = final "
            "candidate fitness; green = best so far. Lower is better."
        )
        self.ga_plot_explanation.setWordWrap(True)
        self.ga_plot_explanation.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ga_plot_explanation.setStyleSheet(
            f"color: {T.muted}; font-size: 11px;"
        )
        layout.addWidget(self.ga_plot_explanation)
        return card

    def _build_channel_selector_card(self) -> QWidget:
        """Build only the controlled-variable and actuator-selection settings."""
        card = Card(radius=9)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(9, 7, 9, 7)
        layout.setSpacing(5)

        title = QLabel("CONTROL SETUP")
        title.setStyleSheet(f"color: {T.text}; font-size: 12px; font-weight: 600;")
        layout.addWidget(title)

        variable_row = QHBoxLayout()
        variable_row.setContentsMargins(0, 0, 0, 0)
        variable_label = QLabel("CONTROLLED VARIABLE")
        variable_label.setStyleSheet(f"color: {T.muted}; font-size: 10px;")
        variable_value = QLabel("BEAM CURRENT")
        variable_value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        variable_value.setStyleSheet(
            f"color: {T.cyan}; font-size: 12px; font-weight: 600;"
        )
        variable_row.addWidget(variable_label)
        variable_row.addStretch(1)
        variable_row.addWidget(variable_value)
        layout.addLayout(variable_row)

        selector_label = QLabel("PENDING TRIM-COIL ACTUATOR")
        selector_label.setStyleSheet(f"color: {T.muted}; font-size: 10px;")
        layout.addWidget(selector_label)

        selector_row = QHBoxLayout()
        selector_row.setContentsMargins(0, 0, 0, 0)
        selector_row.setSpacing(6)

        self.actuator_selector = NoWheelComboBox()
        self.actuator_selector.addItems(self.context.channel_names[:12])
        self.actuator_selector.setCurrentIndex(self._actuator_index)
        self.actuator_selector.setMinimumWidth(105)
        self.actuator_selector.setToolTip(
            "Choose a pending trim-coil actuator. The active actuator does not "
            "change until APPLY is pressed. Mouse-wheel changes are disabled."
        )
        self.actuator_selector.setStyleSheet(
            f"QComboBox {{ color: {T.cyan}; font-size: 12px; font-weight: 600; padding: 3px 6px; }}"
        )
        self.actuator_selector.currentIndexChanged.connect(
            self._on_actuator_choice_changed
        )
        selector_row.addWidget(self.actuator_selector, 1)

        self.apply_actuator_button = QPushButton("TC10 ACTIVE")
        self.apply_actuator_button.setStyleSheet(self._compact_pid_button_css(T.amber))
        self.apply_actuator_button.setFixedHeight(25)
        self.apply_actuator_button.setMaximumWidth(96)
        self.apply_actuator_button.setToolTip(
            "Confirm the pending trim-coil selection. Changing the actuator "
            "disarms hardware output and clears PID history."
        )
        self.apply_actuator_button.clicked.connect(self._apply_actuator_selection)
        selector_row.addWidget(self.apply_actuator_button)
        layout.addLayout(selector_row)

        self.active_actuator_label = QLabel("ACTIVE ACTUATOR: TC10")
        self.active_actuator_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.active_actuator_label.setStyleSheet(
            f"color: {T.green}; font-size: 10px; font-weight: 600;"
        )
        layout.addWidget(self.active_actuator_label)
        return card

    def _build_monitoring_tables_card(self) -> QWidget:
        """Collect live PID/readback values in a scrollable monitoring table.

        The radar remains fixed above this card.  The table itself scrolls
        vertically inside the card, which lets the monitoring text be larger
        without increasing the full PID-page height or forcing page scrolling.
        """
        card = Card(radius=9)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(7, 6, 5, 6)
        layout.setSpacing(4)

        title = QLabel("LIVE MONITORING")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color: {T.text}; font-size: 12px; font-weight: 600;"
        )
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setObjectName("pidMonitoringScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # Keep the scrollbar visible so the operator immediately knows that
        # more monitoring rows are available inside this card.
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        scroll.setStyleSheet(
            f"""
            QScrollArea#pidMonitoringScroll {{
                background: transparent;
                border: none;
            }}
            QScrollArea#pidMonitoringScroll > QWidget > QWidget {{
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: #0A1014;
                width: 10px;
                margin: 1px;
                border: 1px solid {T.border_soft};
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: #3A4851;
                min-height: 34px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {T.cyan};
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            """
        )
        scroll.verticalScrollBar().setSingleStep(24)

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(1, 0, 4, 2)
        body_layout.setSpacing(5)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(7)
        grid.setVerticalSpacing(0)
        grid.setColumnStretch(0, 44)
        grid.setColumnStretch(1, 56)

        row = 0

        def section(text: str) -> None:
            nonlocal row
            heading = QLabel(text)
            heading.setMinimumHeight(22)
            heading.setStyleSheet(
                f"color: {T.cyan}; font-size: 10px; font-weight: 600; "
                f"padding: 4px 3px 2px 3px; border-bottom: 1px solid {T.border};"
            )
            grid.addWidget(heading, row, 0, 1, 2)
            row += 1

        def value_label(color: str = T.text) -> QLabel:
            value = QLabel("—")
            value.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            value.setMinimumHeight(22)
            value.setStyleSheet(
                f"color: {color}; font-size: 11px; font-weight: 600; "
                "padding: 2px 3px; border-bottom: 1px solid #1B252C;"
            )
            return value

        def add_row(name: str, value: QLabel) -> None:
            nonlocal row
            label = QLabel(name)
            label.setMinimumHeight(22)
            label.setStyleSheet(
                f"color: {T.muted}; font-size: 10px; padding: 2px 3px; "
                "border-bottom: 1px solid #1B252C;"
            )
            grid.addWidget(label, row, 0)
            grid.addWidget(value, row, 1)
            row += 1

        section("BEAM / ERROR")
        self.controlled_display = value_label(T.cyan)
        self.actuator_display = value_label(T.cyan)
        self.setpoint_display = value_label(T.cyan)
        self.actual_display = value_label(T.orange)
        self.error_display = value_label(T.amber)
        self.abs_error_display = value_label(T.amber)
        self.trend_display = value_label(T.text)
        self.direction_display = value_label(T.text)
        self.beam_source_status = value_label(T.red)
        for name, display in (
            ("Controlled variable", self.controlled_display),
            ("Active actuator", self.actuator_display),
            ("Beam setpoint", self.setpoint_display),
            ("Measured beam", self.actual_display),
            ("Signed error e", self.error_display),
            ("Error magnitude |e|", self.abs_error_display),
            ("|e| trend", self.trend_display),
            ("Direction d", self.direction_display),
            ("Beam source / age", self.beam_source_status),
        ):
            add_row(name, display)

        section("PID RESPONSE")
        self.output_display = value_label(T.cyan)
        self.magnitude_display = value_label(T.amber)
        self.p_display = value_label(T.text)
        self.i_display = value_label(T.text)
        self.d_display = value_label(T.text)
        for name, display in (
            ("Signed ΔTC", self.output_display),
            ("PID magnitude", self.magnitude_display),
            ("P(|e|)", self.p_display),
            ("I(|e|)", self.i_display),
            ("D(|e|)", self.d_display),
        ):
            add_row(name, display)

        section("SELECTED TRIM COIL")
        self.baseline_display = value_label(T.cyan)
        self.current_target_display = value_label(T.text)
        self.proposed_target_display = value_label(T.orange)
        self.tc_actual_display = value_label(T.orange)
        for name, display in (
            ("Captured baseline", self.baseline_display),
            ("Current target", self.current_target_display),
            ("Next proposed target", self.proposed_target_display),
            ("Measured current", self.tc_actual_display),
        ):
            add_row(name, display)

        section("SYSTEM")
        self.compact_actuator_status = self.actuator_display
        self.compact_mode_status = value_label(T.amber)
        self.compact_beam_status = value_label(T.red)
        add_row("Hardware output", self.compact_mode_status)
        add_row("Beam-data state", self.compact_beam_status)

        section("DATA LOGGING")
        self.pid_sqlite_status_display = value_label(T.cyan)
        self.pid_sqlite_status_display.setToolTip(str(self.pid_logger.db_path))
        add_row("PID SQLite", self.pid_sqlite_status_display)

        body_layout.addLayout(grid)

        self.pid_status_label = QLabel("PID IDLE")
        self.pid_status_label.setWordWrap(True)
        self.pid_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pid_status_label.setMinimumHeight(38)
        self.pid_status_label.setStyleSheet(
            f"color: {T.text}; background: #0E151A; border: 1px solid {T.border}; "
            "border-radius: 5px; padding: 6px; font-size: 11px; font-weight: 600;"
        )
        body_layout.addWidget(self.pid_status_label)
        body_layout.addStretch(1)

        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        # Compatibility name retained for integrations that still reference it.
        self.channel_display = self.actuator_display
        return card

    def _build_plot_card(self) -> QWidget:
        """Three vertically stacked trends with explicit color legends.

        The legend is placed in each compact title row instead of below the
        graph, so the three plots retain a wide, shared time domain without
        increasing the page height.
        """
        card = Card(radius=9)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(8, 4, 8, 5)
        outer.setSpacing(2)

        def legend_item(text: str, color: str) -> QWidget:
            item = QWidget()
            item.setStyleSheet("background: transparent;")
            row = QHBoxLayout(item)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)

            swatch = QFrame()
            swatch.setFixedSize(18, 3)
            swatch.setStyleSheet(
                f"background: {color}; border: none; border-radius: 1px;"
            )
            label = QLabel(text)
            label.setStyleSheet(
                f"color: {T.muted}; font-size: 9px; font-weight: 500;"
            )
            row.addWidget(swatch)
            row.addWidget(label)
            return item

        def add_plot(
            title_text: str,
            plot: TrendPlot,
            legend_entries: tuple[tuple[str, str], ...],
        ) -> None:
            header = QWidget()
            header.setFixedHeight(22)
            header.setStyleSheet("background: #080D11;")
            header_layout = QHBoxLayout(header)
            header_layout.setContentsMargins(8, 0, 8, 0)
            header_layout.setSpacing(10)

            title = QLabel(title_text)
            title.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            title.setStyleSheet(
                f"color: {T.text}; font-size: 10px; font-weight: 600;"
            )
            header_layout.addWidget(title)
            header_layout.addStretch(1)
            for legend_text, legend_color in legend_entries:
                header_layout.addWidget(legend_item(legend_text, legend_color))

            outer.addWidget(header)
            plot.setMinimumHeight(140)
            plot.setMaximumHeight(16777215)
            outer.addWidget(plot, 1)

        self.plot = TrendPlot(
            y_axis_label="BEAM CURRENT (nA)",
            target_color=T.cyan,
            actual_color=T.orange,
        )
        add_plot(
            "BEAM-CURRENT SETPOINT RESPONSE",
            self.plot,
            (("SETPOINT", T.cyan), ("MEASURED BEAM", T.orange)),
        )

        self.error_plot = TrendPlot(
            y_axis_label="|ERROR| (nA)",
            target_color=T.green,
            actual_color=T.amber,
        )
        add_plot(
            "ABSOLUTE ERROR AND DEADBAND",
            self.error_plot,
            (("|ERROR|", T.amber), ("DEADBAND", T.green)),
        )

        self.tc_plot_title = QLabel("SELECTED TC TARGET AND MEASURED CURRENT")
        # The title is retained as an attribute because the active-TC update
        # code changes it whenever the confirmed actuator changes.
        self.tc_plot_title.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.tc_plot_title.setStyleSheet(
            f"color: {T.text}; font-size: 10px; font-weight: 600;"
        )

        tc_header = QWidget()
        tc_header.setFixedHeight(22)
        tc_header.setStyleSheet("background: #080D11;")
        tc_header_layout = QHBoxLayout(tc_header)
        tc_header_layout.setContentsMargins(8, 0, 8, 0)
        tc_header_layout.setSpacing(10)
        tc_header_layout.addWidget(self.tc_plot_title)
        tc_header_layout.addStretch(1)
        tc_header_layout.addWidget(legend_item("TC TARGET", T.cyan))
        tc_header_layout.addWidget(legend_item("MEASURED TC", T.orange))
        outer.addWidget(tc_header)

        self.tc_plot = TrendPlot(
            y_axis_label="TC CURRENT (A)",
            target_color=T.cyan,
            actual_color=T.orange,
        )
        self.tc_plot.setMinimumHeight(140)
        self.tc_plot.setMaximumHeight(16777215)
        outer.addWidget(self.tc_plot, 1)

        # Compatibility attribute retained for older integrations. The visible
        # legend now lives in the compact graph header.
        self.tc_plot_legend = QLabel("")
        self.tc_plot_legend.hide()
        return card

    def _build_tc_plot_card(self) -> QWidget:
        """Build a separate trend plot for the confirmed PID actuator.

        The beam-current and absolute-error plots remain together above. This
        third graph is intentionally isolated so the operator can clearly see
        the selected trim-coil target and readback without mixing amperes with
        the beam-current units.
        """
        card = Card(radius=9)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 10, 8)
        layout.setSpacing(6)

        self.tc_plot_title = QLabel("SELECTED TC TARGET AND READBACK")
        self.tc_plot_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tc_plot_title.setStyleSheet(f"color: {T.muted}; font-size: 13px;")
        layout.addWidget(self.tc_plot_title)

        self.tc_plot = TrendPlot(
            y_axis_label="TC CURRENT (A)",
            target_color=T.cyan,
            actual_color=T.orange,
        )
        self.tc_plot.setMinimumHeight(245)
        layout.addWidget(self.tc_plot)

        self.tc_plot_legend = QLabel(
            "Cyan = confirmed TC target     Orange = confirmed TC measured current"
        )
        self.tc_plot_legend.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tc_plot_legend.setStyleSheet(f"color: {T.muted}; font-size: 11px;")
        layout.addWidget(self.tc_plot_legend)
        return card

    def _build_radar_card(self) -> QWidget:
        card = Card(radius=9)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(4)

        title = QLabel("PID GAINS")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {T.text}; font-size: 12px; font-weight: 600;")
        layout.addWidget(title)

        self.pid_radar = PIDGainRadar()
        self.pid_radar.setMinimumHeight(170)
        self.pid_radar.setMaximumHeight(230)
        layout.addWidget(self.pid_radar, 1)

        values = QGridLayout()
        values.setContentsMargins(0, 0, 0, 0)
        values.setHorizontalSpacing(4)

        def radar_value(color: str) -> QLabel:
            display = QLabel("—")
            display.setAlignment(Qt.AlignmentFlag.AlignCenter)
            display.setMinimumHeight(22)
            display.setStyleSheet(
                f"color: {color}; background: #0E151A; border: 1px solid #27323A; "
                "border-radius: 5px; padding: 2px; font-size: 10px; font-weight: 600;"
            )
            return display

        self.radar_kp_display = radar_value(T.cyan)
        self.radar_ki_display = radar_value(T.green)
        self.radar_kd_display = radar_value(T.orange)
        for col, (name, display) in enumerate((
            ("Kp", self.radar_kp_display),
            ("Ki", self.radar_ki_display),
            ("Kd", self.radar_kd_display),
        )):
            label = QLabel(name)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(f"color: {T.muted}; font-size: 9px;")
            values.addWidget(label, 0, col)
            values.addWidget(display, 1, col)
        layout.addLayout(values)
        return card

    def _build_compact_status_card(self) -> QWidget:
        card = Card(radius=9)
        grid = QGridLayout(card)
        grid.setContentsMargins(8, 7, 8, 7)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)

        heading = QLabel("PID STATUS")
        heading.setStyleSheet(f"color: {T.text}; font-size: 11px; font-weight: 600;")
        grid.addWidget(heading, 0, 0, 1, 2)

        self.compact_actuator_status = QLabel("—")
        self.compact_mode_status = QLabel("PREVIEW")
        self.compact_beam_status = QLabel("NO DATA")
        rows = (
            ("ACTUATOR", self.compact_actuator_status),
            ("OUTPUT", self.compact_mode_status),
            ("BEAM DATA", self.compact_beam_status),
        )
        for row, (name, value) in enumerate(rows, start=1):
            label = QLabel(name)
            label.setStyleSheet(f"color: {T.muted}; font-size: 9px;")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setStyleSheet(f"color: {T.cyan}; font-size: 10px; font-weight: 600;")
            grid.addWidget(label, row, 0)
            grid.addWidget(value, row, 1)
        return card

    def _refresh_pid_radar(self) -> None:
        if not hasattr(self, "pid_radar"):
            return
        kp, ki, kd = self.kp_spin.value(), self.ki_spin.value(), self.kd_spin.value()
        self.pid_radar.set_gains(kp, ki, kd)
        self.radar_kp_display.setText(f"{kp:.6g}")
        self.radar_ki_display.setText(f"{ki:.6g}")
        self.radar_kd_display.setText(f"{kd:.6g}")

    def _build_pid_card(self) -> QWidget:
        """Build the settings-only PID column.

        Live error, PID terms, target values, and status messages are created in
        ``_build_monitoring_tables_card`` below the radar chart instead of being
        mixed with operator settings.
        """
        card = Card(radius=9)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(9, 7, 9, 7)
        layout.setSpacing(5)

        title = QLabel("ADAPTIVE-DIRECTION PID SETTINGS")
        title.setStyleSheet("font-size: 12px; font-weight: 600;")
        layout.addWidget(title)

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
        self.initial_direction_combo.addItem("+1 — INCREASE TC", 1)
        self.initial_direction_combo.addItem("−1 — DECREASE TC", -1)
        self.initial_direction_combo.setToolTip(
            "Initial adaptive direction: +1 increases the selected TC target; "
            "−1 decreases the selected TC target."
        )

        # The operator-facing output and integral limit controls were removed.
        # LabVIEW remains responsible for the physical current ramp, while the
        # TC min/max fields below remain the absolute Python-side target bounds.
        # A finite automatic numerical guard is derived from that TC range in
        # ``_pid_settings`` because the PID engine still requires finite values
        # for anti-windup and floating-point safety.

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

        # The shared application theme uses comfortable full-size editors.
        # This dense PID settings grid needs narrower spin buttons and less
        # right-side padding so suffixes and values never collide in two-column
        # mode. The change is local to this PID page only.
        for editor in (
            self.setpoint_spin,
            self.kp_spin,
            self.ki_spin,
            self.kd_spin,
            self.deadband_spin,
            self.trend_tolerance_spin,
            self.direction_check_spin,
            self.loop_period_spin,
            self.derivative_tau_spin,
            self.tc_min_spin,
            self.tc_max_spin,
            self.beam_stale_spin,
        ):
            self._style_compact_pid_editor(editor)
        self._style_compact_pid_combo(self.initial_direction_combo)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        row = 0

        def section(text: str) -> None:
            nonlocal row
            heading = QLabel(text)
            heading.setStyleSheet(
                f"color: {T.cyan}; font-size: 9px; font-weight: 600; "
                f"padding-top: 3px; border-bottom: 1px solid {T.border};"
            )
            grid.addWidget(heading, row, 0, 1, 4)
            row += 1

        def pair(
            left_name: str,
            left_widget: QWidget,
            right_name: str | None = None,
            right_widget: QWidget | None = None,
        ) -> None:
            nonlocal row
            left_label = QLabel(left_name)
            left_label.setStyleSheet(f"color: {T.muted}; font-size: 9px;")
            grid.addWidget(left_label, row, 0)
            grid.addWidget(left_widget, row, 1)
            if right_name is not None and right_widget is not None:
                right_label = QLabel(right_name)
                right_label.setStyleSheet(f"color: {T.muted}; font-size: 9px;")
                grid.addWidget(right_label, row, 2)
                grid.addWidget(right_widget, row, 3)
            row += 1

        section("REFERENCE AND GAINS")
        pair("Setpoint", self.setpoint_spin, "Kp", self.kp_spin)
        pair("Ki", self.ki_spin, "Kd", self.kd_spin)

        section("ERROR AND DIRECTION")
        pair("Deadband", self.deadband_spin, "Trend tol.", self.trend_tolerance_spin)
        pair("Dir. check", self.direction_check_spin, "Initial dir.", self.initial_direction_combo)

        section("TIMING AND ACTUATOR LIMITS")
        pair("Loop", self.loop_period_spin, "D filter τ", self.derivative_tau_spin)
        pair("TC min", self.tc_min_spin, "TC max", self.tc_max_spin)
        pair("Beam stale", self.beam_stale_spin)
        layout.addLayout(grid)

        behavior_row = QHBoxLayout()
        behavior_row.setContentsMargins(0, 0, 0, 0)
        self.reset_i_deadband_check = QCheckBox("RESET I IN DEADBAND")
        self.reset_i_reverse_check = QCheckBox("RESET I ON REVERSE")
        compact_check_css = f"color: {T.text}; font-size: 9px; spacing: 5px;"
        self.reset_i_deadband_check.setStyleSheet(compact_check_css)
        self.reset_i_reverse_check.setStyleSheet(compact_check_css)
        behavior_row.addWidget(self.reset_i_deadband_check)
        behavior_row.addWidget(self.reset_i_reverse_check)
        layout.addLayout(behavior_row)

        command_heading = QLabel("PID COMMANDS")
        command_heading.setStyleSheet(
            f"color: {T.cyan}; font-size: 9px; font-weight: 600; "
            f"padding-top: 3px; border-bottom: 1px solid {T.border};"
        )
        layout.addWidget(command_heading)

        utility_controls = QHBoxLayout()
        utility_controls.setSpacing(4)
        self.load_actual_button = QPushButton("BEAM → SET")
        self.load_actual_button.setToolTip("Load the measured beam current into the setpoint field.")
        self.load_actual_button.setStyleSheet(self._compact_pid_button_css())
        self.load_actual_button.clicked.connect(self._load_actual_as_setpoint)
        utility_controls.addWidget(self.load_actual_button)

        self.capture_baseline_button = QPushButton("CAPTURE BASE")
        self.capture_baseline_button.setToolTip("Capture the current selected-TC target as the PID baseline.")
        self.capture_baseline_button.setStyleSheet(self._compact_pid_button_css())
        self.capture_baseline_button.clicked.connect(self._capture_baseline)
        utility_controls.addWidget(self.capture_baseline_button)

        self.reset_button = QPushButton("RESET PID")
        self.reset_button.setStyleSheet(self._compact_pid_button_css())
        self.reset_button.clicked.connect(self.reset_pid)
        utility_controls.addWidget(self.reset_button)
        layout.addLayout(utility_controls)

        run_controls = QHBoxLayout()
        run_controls.setSpacing(4)
        self.arm_output_check = QCheckBox("ARM OUTPUT")
        self.arm_output_check.setStyleSheet(f"color: {T.text}; font-size: 9px; spacing: 5px;")
        self.arm_output_check.setToolTip(
            "When checked, signed ΔTC commands are added to the selected TC "
            "target through the existing control queue."
        )
        run_controls.addWidget(self.arm_output_check)
        run_controls.addStretch(1)

        self.start_pid_button = QPushButton("START PID")
        self.start_pid_button.setStyleSheet(self._compact_pid_button_css(T.green))
        self.start_pid_button.clicked.connect(self.start_pid)
        run_controls.addWidget(self.start_pid_button)

        self.stop_pid_button = QPushButton("STOP PID")
        self.stop_pid_button.setStyleSheet(self._compact_pid_button_css(T.red))
        self.stop_pid_button.clicked.connect(self.stop_pid)
        run_controls.addWidget(self.stop_pid_button)
        layout.addLayout(run_controls)
        layout.addStretch(1)
        return card

    def _build_ga_card(self) -> QWidget:
        card = Card(radius=9)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        title = QLabel("GENETIC ALGORITHM — AUTOMATIC PID GAIN SEARCH")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title)

        note = QLabel(
            "Automatic mode loads each Kp/Ki/Kd candidate, runs the existing PID, "
            "scores the measured beam and selected-TC response, restores the original "
            "TC baseline, and then advances to the next candidate. The automatic run "
            "will not start until both ARM OUTPUT on the PID page and ARM AUTO GA below "
            "are checked. Lower fitness is better."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {T.muted};")
        layout.addWidget(note)

        config_grid = QGridLayout()
        config_grid.setHorizontalSpacing(10)
        config_grid.setVerticalSpacing(7)

        self.population_spin = QSpinBox()
        self.population_spin.setRange(4, 500)
        self.population_spin.setValue(4)
        self.generations_spin = QSpinBox()
        self.generations_spin.setRange(1, 500)
        self.generations_spin.setValue(2)

        self.kp_min_spin = self._double_spin(0.0, 1_000_000.0, 6, 0.001)
        self.kp_max_spin = self._double_spin(0.0, 1_000_000.0, 6, 0.001)
        self.ki_min_spin = self._double_spin(0.0, 1_000_000.0, 6, 0.0001)
        self.ki_max_spin = self._double_spin(0.0, 1_000_000.0, 6, 0.0001)
        self.kd_min_spin = self._double_spin(0.0, 1_000_000.0, 6, 0.0001)
        self.kd_max_spin = self._double_spin(0.0, 1_000_000.0, 6, 0.0001)

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
        for label_text, widget, row, col in ga_fields:
            label = QLabel(label_text)
            label.setStyleSheet(f"color: {T.muted};")
            config_grid.addWidget(label, row, col)
            config_grid.addWidget(widget, row, col + 1)

        layout.addLayout(config_grid)

        timing_title = QLabel("AUTOMATIC EVALUATION AND SAFETY")
        timing_title.setStyleSheet(
            f"color: {T.cyan}; font-size: 12px; font-weight: 600;"
        )
        layout.addWidget(timing_title)

        timing_grid = QGridLayout()
        timing_grid.setHorizontalSpacing(10)
        timing_grid.setVerticalSpacing(7)
        self.ga_warmup_spin = self._double_spin(0.0, 600.0, 1, 0.5)
        self.ga_warmup_spin.setValue(5.0)
        self.ga_evaluation_spin = self._double_spin(0.1, 3600.0, 1, 1.0)
        self.ga_evaluation_spin.setValue(30.0)
        self.ga_steady_window_spin = self._double_spin(0.0, 600.0, 1, 0.5)
        self.ga_steady_window_spin.setValue(5.0)
        self.ga_max_excursion_spin = self._double_spin(0.01, 100.0, 3, 0.05)
        self.ga_max_excursion_spin.setValue(0.50)
        self.ga_max_beam_error_spin = self._double_spin(0.01, 1_000.0, 3, 0.10)
        self.ga_max_beam_error_spin.setValue(3.0)
        self.ga_min_valid_beam_spin = self._double_spin(0.0, 1_000.0, 3, 0.01)
        self.ga_min_valid_beam_spin.setValue(0.05)
        self.ga_min_valid_beam_spin.setToolTip(
            "A candidate is immediately penalized when the absolute measured beam "
            "falls below this value. The controller then restores the captured "
            "recovery reference instead of treating zero beam as an ordinary error."
        )
        self.ga_max_saturation_spin = self._double_spin(0.0, 600.0, 1, 0.5)
        self.ga_max_saturation_spin.setValue(5.0)
        self.ga_max_tc_rate_spin = self._double_spin(0.01, 100.0, 2, 0.1)
        self.ga_max_tc_rate_spin.setValue(1.0)
        self.ga_max_tc_rate_spin.setToolTip(
            "Independent automatic-GA trim-coil ramp-rate limit. The allowed "
            "increment is this rate multiplied by the measured beam-sample dt."
        )
        self.ga_restore_step_spin = self._double_spin(0.01, 10.0, 3, 0.01)
        self.ga_restore_step_spin.setValue(0.02)
        self.ga_restore_tolerance_spin = self._double_spin(0.001, 10.0, 3, 0.01)
        self.ga_restore_tolerance_spin.setValue(0.50)
        self.ga_baseline_beam_tolerance_spin = self._double_spin(0.001, 100.0, 3, 0.01)
        self.ga_baseline_beam_tolerance_spin.setValue(0.20)
        self.ga_baseline_beam_tolerance_spin.setToolTip(
            "The next candidate starts only after beam current returns near the "
            "beam value captured in the recovery reference."
        )
        self.ga_recovery_beam_fraction_spin = self._double_spin(0.0, 100.0, 1, 5.0)
        self.ga_recovery_beam_fraction_spin.setValue(50.0)
        self.ga_recovery_beam_fraction_spin.setSuffix(" %")
        self.ga_recovery_beam_fraction_spin.setToolTip(
            "During recovery, beam must first return above this percentage of the "
            "captured reference beam before it can be declared recovered."
        )
        self.ga_restore_hold_spin = self._double_spin(0.0, 60.0, 1, 0.5)
        self.ga_restore_hold_spin.setValue(2.0)
        self.ga_restore_timeout_spin = self._double_spin(1.0, 600.0, 1, 1.0)
        self.ga_restore_timeout_spin.setValue(20.0)

        timing_fields = [
            ("Warm-up before scoring (s)", self.ga_warmup_spin, 0, 0),
            ("Scored interval (s)", self.ga_evaluation_spin, 0, 2),
            ("Steady-state window (s)", self.ga_steady_window_spin, 1, 0),
            ("Max TC excursion (±A)", self.ga_max_excursion_spin, 1, 2),
            ("Beam-error abort (nA)", self.ga_max_beam_error_spin, 2, 0),
            ("Beam-output loss threshold (nA)", self.ga_min_valid_beam_spin, 2, 2),
            ("Max continuous saturation (s)", self.ga_max_saturation_spin, 3, 0),
            ("Max GA TC rate (A/s)", self.ga_max_tc_rate_spin, 3, 2),
            ("Recovery step (A/update)", self.ga_restore_step_spin, 4, 0),
            ("Measured-TC tolerance (A)", self.ga_restore_tolerance_spin, 4, 2),
            ("Beam-reference tolerance (nA)", self.ga_baseline_beam_tolerance_spin, 5, 0),
            ("Minimum recovered beam (%)", self.ga_recovery_beam_fraction_spin, 5, 2),
            ("Reference stable hold (s)", self.ga_restore_hold_spin, 6, 0),
            ("Recovery timeout (s)", self.ga_restore_timeout_spin, 6, 2),
        ]
        for label_text, widget, row, col in timing_fields:
            label = QLabel(label_text)
            label.setStyleSheet(f"color: {T.muted};")
            timing_grid.addWidget(label, row, col)
            timing_grid.addWidget(widget, row, col + 1)
        layout.addLayout(timing_grid)

        recovery_title = QLabel("BEAM-RECOVERY REFERENCE")
        recovery_title.setStyleSheet(
            f"color: {T.cyan}; font-size: 12px; font-weight: 600;"
        )
        layout.addWidget(recovery_title)
        recovery_row = QHBoxLayout()
        scope_label = QLabel("Recovery channels")
        scope_label.setStyleSheet(f"color: {T.muted};")
        recovery_row.addWidget(scope_label)
        self.ga_recovery_scope_combo = QComboBox()
        self.ga_recovery_scope_combo.addItem("ACTIVE TC ONLY", "active")
        self.ga_recovery_scope_combo.addItem(
            "ALL POWERED + ENABLED TCs", "enabled"
        )
        self.ga_recovery_scope_combo.currentIndexChanged.connect(
            self._invalidate_ga_recovery_reference
        )
        recovery_row.addWidget(self.ga_recovery_scope_combo)
        self.ga_capture_recovery_button = QPushButton("CAPTURE CURRENT REFERENCE")
        self.ga_capture_recovery_button.setStyleSheet(secondary_button_css(T.cyan))
        self.ga_capture_recovery_button.clicked.connect(
            self._capture_ga_recovery_reference
        )
        recovery_row.addWidget(self.ga_capture_recovery_button)
        self.ga_recovery_reference_display = QLabel("NOT CAPTURED")
        self.ga_recovery_reference_display.setWordWrap(True)
        self.ga_recovery_reference_display.setStyleSheet(
            f"color: {T.amber}; font-size: 11px; font-weight: 600;"
        )
        recovery_row.addWidget(self.ga_recovery_reference_display, 1)
        layout.addLayout(recovery_row)

        recovery_note = QLabel(
            "If a candidate drives the beam below the loss threshold, that candidate "
            "receives a safety penalty. PID stops, the captured trim-coil reference is "
            "restored at the configured step, and the GA continues only after the "
            "measured beam and trim-coil readbacks are stable again."
        )
        recovery_note.setWordWrap(True)
        recovery_note.setStyleSheet(f"color: {T.muted}; font-size: 10px;")
        layout.addWidget(recovery_note)

        weight_title = QLabel("FITNESS WEIGHTS")
        weight_title.setStyleSheet(
            f"color: {T.cyan}; font-size: 12px; font-weight: 600;"
        )
        layout.addWidget(weight_title)
        weight_grid = QGridLayout()
        weight_grid.setHorizontalSpacing(10)
        self.ga_w_track_spin = self._double_spin(0.0, 1_000.0, 3, 0.1)
        self.ga_w_ss_spin = self._double_spin(0.0, 1_000.0, 3, 0.1)
        self.ga_w_move_spin = self._double_spin(0.0, 1_000.0, 3, 0.05)
        self.ga_w_sat_spin = self._double_spin(0.0, 1_000.0, 3, 0.5)
        self.ga_w_osc_spin = self._double_spin(0.0, 1_000.0, 3, 0.1)
        self.ga_w_track_spin.setValue(1.0)
        self.ga_w_ss_spin.setValue(2.0)
        self.ga_w_move_spin.setValue(0.25)
        self.ga_w_sat_spin.setValue(5.0)
        self.ga_w_osc_spin.setValue(1.0)
        for col, (name, widget) in enumerate(
            (
                ("TRACK", self.ga_w_track_spin),
                ("STEADY", self.ga_w_ss_spin),
                ("MOVE", self.ga_w_move_spin),
                ("SAT", self.ga_w_sat_spin),
                ("OSC", self.ga_w_osc_spin),
            )
        ):
            label = QLabel(name)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(f"color: {T.muted}; font-size: 10px;")
            weight_grid.addWidget(label, 0, col)
            weight_grid.addWidget(widget, 1, col)
        layout.addLayout(weight_grid)

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
        for col, (label_text, display) in enumerate(progress_items):
            label = QLabel(label_text)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(f"color: {T.muted}; font-size: 11px;")
            progress_grid.addWidget(label, 0, col)
            progress_grid.addWidget(display, 1, col)

        self.ga_phase_display = self._component_display(T.amber)
        self.ga_time_display = self._component_display(T.cyan)
        self.ga_samples_display = self._component_display(T.text)
        self.ga_terms_display = self._component_display(T.orange)
        detail_items = [
            ("AUTO PHASE", self.ga_phase_display),
            ("ELAPSED / TOTAL", self.ga_time_display),
            ("SCORED SAMPLES", self.ga_samples_display),
            ("LAST TERMS", self.ga_terms_display),
        ]
        for col, (label_text, display) in enumerate(detail_items):
            label = QLabel(label_text)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(f"color: {T.muted}; font-size: 11px;")
            progress_grid.addWidget(label, 2, col)
            progress_grid.addWidget(display, 3, col)
        layout.addLayout(progress_grid)

        mode_controls = QHBoxLayout()
        self.auto_ga_arm_check = QCheckBox("ARM AUTO GA")
        self.auto_ga_arm_check.setStyleSheet(
            f"color: {T.red}; font-size: 12px; font-weight: 600;"
        )
        self.auto_ga_arm_check.setToolTip(
            "Required in addition to ARM OUTPUT on the PID page. Automatic GA "
            "will command the selected trim coil and restore its captured baseline "
            "between candidates."
        )
        mode_controls.addWidget(self.auto_ga_arm_check)
        self.manual_ga_mode_check = QCheckBox("MANUAL SCORE MODE")
        self.manual_ga_mode_check.setStyleSheet(f"color: {T.muted};")
        self.manual_ga_mode_check.setToolTip(
            "Development-only mode: generate candidates and type fitness scores manually."
        )
        self.manual_ga_mode_check.toggled.connect(self._set_manual_score_controls)
        mode_controls.addWidget(self.manual_ga_mode_check)
        mode_controls.addStretch()
        layout.addLayout(mode_controls)

        controls = QHBoxLayout()
        self.start_ga_button = QPushButton("START GA")
        self.start_ga_button.setStyleSheet(secondary_button_css(T.green))
        self.start_ga_button.clicked.connect(self.start_ga)
        controls.addWidget(self.start_ga_button)

        self.abort_ga_button = QPushButton("ABORT + RESTORE")
        self.abort_ga_button.setStyleSheet(secondary_button_css(T.red))
        self.abort_ga_button.clicked.connect(self.abort_ga)
        controls.addWidget(self.abort_ga_button)

        controls.addStretch()
        score_label = QLabel("Manual Fitness")
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

        self.ga_status_label = QLabel(
            "GA IDLE — ENTER Kp/Ki/Kd MIN/MAX SEARCH BOUNDS"
        )
        self.ga_status_label.setWordWrap(True)
        self.ga_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ga_status_label.setStyleSheet(info_label_css())
        layout.addWidget(self.ga_status_label)

        self._ga_config_widgets = [
            self.population_spin,
            self.generations_spin,
            self.kp_min_spin,
            self.kp_max_spin,
            self.ki_min_spin,
            self.ki_max_spin,
            self.kd_min_spin,
            self.kd_max_spin,
            self.ga_warmup_spin,
            self.ga_evaluation_spin,
            self.ga_steady_window_spin,
            self.ga_max_excursion_spin,
            self.ga_max_beam_error_spin,
            self.ga_min_valid_beam_spin,
            self.ga_max_saturation_spin,
            self.ga_max_tc_rate_spin,
            self.ga_restore_step_spin,
            self.ga_restore_tolerance_spin,
            self.ga_baseline_beam_tolerance_spin,
            self.ga_recovery_beam_fraction_spin,
            self.ga_restore_hold_spin,
            self.ga_restore_timeout_spin,
            self.ga_w_track_spin,
            self.ga_w_ss_spin,
            self.ga_w_move_spin,
            self.ga_w_sat_spin,
            self.ga_w_osc_spin,
            self.ga_recovery_scope_combo,
            self.ga_capture_recovery_button,
            self.manual_ga_mode_check,
        ]
        self._set_manual_score_controls()
        return card

    def _set_manual_score_controls(self, _checked=False) -> None:
        manual = bool(
            hasattr(self, "manual_ga_mode_check")
            and self.manual_ga_mode_check.isChecked()
        )
        enabled = manual and not self._ga_auto_active
        if hasattr(self, "fitness_spin"):
            self.fitness_spin.setEnabled(enabled)
        if hasattr(self, "submit_fitness_button"):
            self.submit_fitness_button.setEnabled(enabled)
        if hasattr(self, "auto_ga_arm_check"):
            self.auto_ga_arm_check.setEnabled(not manual and not self._ga_auto_active)

    def _ga_recovery_channel_indices(self) -> list[int]:
        """Return the trim coils included in the captured recovery profile."""
        scope = (
            self.ga_recovery_scope_combo.currentData()
            if hasattr(self, "ga_recovery_scope_combo")
            else "active"
        )
        if scope == "enabled":
            indices = [
                index
                for index in range(min(12, len(self.context.channel_names)))
                if self.context.power_states[index]
                and self.context.enable_states[index]
            ]
            if indices:
                return indices
        return [self._actuator_index]

    def _invalidate_ga_recovery_reference(self, _value=None) -> None:
        if self._ga_auto_active:
            return
        self._ga_recovery_reference = None
        self.ga_recovery_manager.reset()
        if hasattr(self, "ga_recovery_reference_display"):
            self.ga_recovery_reference_display.setText("NOT CAPTURED")
            self.ga_recovery_reference_display.setStyleSheet(
                f"color: {T.amber}; font-size: 11px; font-weight: 600;"
            )

    def _capture_ga_recovery_reference(
        self,
        _checked=False,
        *,
        show_status: bool = True,
    ) -> bool:
        """Capture known-good target, readback, and beam references.

        The measured-current reference is intentionally stored separately from
        the command target.  A systematic target/readback offset therefore does
        not make recovery impossible (for example, a 600 A target whose normal
        readback is approximately 596 A).
        """
        snapshot = self.context.beam_snapshot(max_age_s=self._beam_stale_limit())
        beam = float(snapshot.get("value_nA", float("nan")))
        minimum_beam = (
            self.ga_min_valid_beam_spin.value()
            if hasattr(self, "ga_min_valid_beam_spin")
            else 0.0
        )
        if not bool(snapshot.get("valid")) or not math.isfinite(beam):
            if show_status and hasattr(self, "ga_status_label"):
                self.ga_status_label.setText(
                    "RECOVERY REFERENCE NOT CAPTURED — FRESH BEAM DATA IS REQUIRED"
                )
            return False
        if abs(beam) < minimum_beam:
            if show_status and hasattr(self, "ga_status_label"):
                self.ga_status_label.setText(
                    f"RECOVERY REFERENCE NOT CAPTURED — |BEAM| {abs(beam):.4g} nA "
                    f"IS BELOW THE {minimum_beam:.4g} nA VALID-BEAM THRESHOLD"
                )
            return False

        indices = self._ga_recovery_channel_indices()
        for index in indices:
            if not self.context.power_states[index] or not self.context.enable_states[index]:
                if show_status and hasattr(self, "ga_status_label"):
                    self.ga_status_label.setText(
                        f"RECOVERY REFERENCE NOT CAPTURED — "
                        f"{self.context.channel_name(index)} MUST BE ON AND ENABLED"
                    )
                return False

        try:
            reference = GARecoveryManager.capture(
                targets_a=self.context.targets_snapshot(),
                actual_values_a=list(self.context.actual_values),
                beam_nA=beam,
                channel_indices=indices,
                timestamp_s=time.monotonic(),
            )
        except ValueError as exc:
            if show_status and hasattr(self, "ga_status_label"):
                self.ga_status_label.setText(
                    f"RECOVERY REFERENCE NOT CAPTURED — {str(exc).upper()}"
                )
            return False

        self._ga_recovery_reference = reference
        if hasattr(self, "ga_recovery_reference_display"):
            if len(reference.targets_a) == 1:
                index, target = reference.targets_a[0]
                actual = reference.actual_map[index]
                text = (
                    f"{self.context.channel_name(index)} TARGET {target:.2f} A | "
                    f"READBACK REF {actual:.2f} A | BEAM {beam:.3f} nA"
                )
            else:
                names = ", ".join(
                    self.context.channel_name(index)
                    for index, _target in reference.targets_a[:4]
                )
                suffix = "…" if len(reference.targets_a) > 4 else ""
                text = (
                    f"{len(reference.targets_a)} TCs ({names}{suffix}) | "
                    f"BEAM {beam:.3f} nA"
                )
            self.ga_recovery_reference_display.setText(text)
            self.ga_recovery_reference_display.setStyleSheet(
                f"color: {T.green}; font-size: 11px; font-weight: 600;"
            )
        if show_status and hasattr(self, "ga_status_label"):
            self.ga_status_label.setText(
                "KNOWN-GOOD RECOVERY REFERENCE CAPTURED — TARGETS, NORMAL "
                "READBACKS, AND BEAM CURRENT STORED"
            )
        return True

    @staticmethod
    def _style_compact_pid_editor(editor: QAbstractSpinBox) -> None:
        """Use narrow up/down buttons in the dense PID settings grid only."""
        editor.setFixedHeight(24)
        editor.setMinimumWidth(0)
        editor.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        editor.setStyleSheet(
            f"""
            QDoubleSpinBox, QSpinBox {{
                background: #0E151A;
                color: {T.text};
                border: 1px solid #3A4851;
                border-radius: 4px;
                padding: 1px 12px 1px 5px;
                min-height: 20px;
                max-height: 20px;
                font-size: 10px;
            }}
            QDoubleSpinBox:focus, QSpinBox:focus {{
                border-color: {T.cyan};
            }}
            QDoubleSpinBox::up-button, QSpinBox::up-button {{
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 9px;
                height: 10px;
                border-left: 1px solid {T.border_soft};
                border-bottom: 1px solid {T.border_soft};
                border-top-right-radius: 3px;
                background: #11191F;
            }}
            QDoubleSpinBox::down-button, QSpinBox::down-button {{
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 9px;
                height: 10px;
                border-left: 1px solid {T.border_soft};
                border-bottom-right-radius: 3px;
                background: #11191F;
            }}
            QDoubleSpinBox::up-button:hover, QSpinBox::up-button:hover,
            QDoubleSpinBox::down-button:hover, QSpinBox::down-button:hover {{
                background: #172129;
                border-left-color: {T.cyan};
            }}
            """
        )

    @staticmethod
    def _style_compact_pid_combo(combo: QComboBox) -> None:
        """Keep the PID direction dropdown compact and prevent text overlap."""
        combo.setFixedHeight(24)
        combo.setMinimumWidth(0)
        combo.setStyleSheet(
            f"""
            QComboBox {{
                background: #0E151A;
                color: {T.text};
                border: 1px solid #3A4851;
                border-radius: 4px;
                padding: 1px 13px 1px 5px;
                min-height: 20px;
                max-height: 20px;
                font-size: 10px;
            }}
            QComboBox:focus {{ border-color: {T.cyan}; }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 11px;
                border-left: 1px solid {T.border_soft};
                background: #11191F;
            }}
            QComboBox::drop-down:hover {{
                background: #172129;
                border-left-color: {T.cyan};
            }}
            """
        )

    @staticmethod
    def _compact_pid_button_css(accent: str = T.cyan) -> str:
        """Compact command-button style used only by the PID workspace."""
        return f"""
            QPushButton {{
                background: #11191F;
                color: {T.text};
                border: 1px solid #3A4851;
                border-radius: 5px;
                padding: 3px 6px;
                min-height: 19px;
                max-height: 23px;
                font-size: 10px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background: #172129;
                border-color: {accent};
            }}
            QPushButton:pressed, QPushButton:checked {{
                background: #20303B;
                border-color: {accent};
            }}
            QPushButton:disabled {{
                color: #59646B;
                border-color: #293239;
            }}
        """

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
        # Do not update dozens of Qt labels for every 100 Hz beam packet. The
        # independent 5 Hz display timer presents the latest snapshot while the
        # PID control timer continues to process fresh feedback independently.
        self.context.mode_changed.connect(self._on_mode_changed)

    def _on_actuator_choice_changed(self, index: int) -> None:
        """Record a pending combo-box choice without changing the actuator."""
        if not 0 <= int(index) < min(12, len(self.context.channel_names)):
            return
        self._pending_actuator_index = int(index)
        self._update_actuator_selection_controls()

        if self._pending_actuator_index != self._actuator_index:
            pending_name = self.context.channel_name(self._pending_actuator_index)
            self.pid_status_label.setText(
                f"{pending_name} SELECTED IN LIST BUT NOT ACTIVE — PRESS APPLY TC SELECTION"
            )
        elif not self._pid_running:
            active_name = self.context.channel_name(self._actuator_index)
            self.pid_status_label.setText(
                f"{active_name} REMAINS THE ACTIVE PID ACTUATOR — NO CHANGE PENDING"
            )

    def _apply_actuator_selection(self) -> None:
        """Confirm the pending trim-coil selection with safety resets."""
        if self._pid_running:
            self.pid_status_label.setText(
                "TC CHANGE BLOCKED — STOP PID BEFORE CHANGING THE ACTUATOR"
            )
            return

        pending = int(self._pending_actuator_index)
        if not 0 <= pending < min(12, len(self.context.channel_names)):
            self.pid_status_label.setText("TC CHANGE BLOCKED — INVALID ACTUATOR")
            return
        if pending == self._actuator_index:
            self._update_actuator_selection_controls()
            return

        previous_name = self.context.channel_name(self._actuator_index)
        new_name = self.context.channel_name(pending)
        output_was_armed = self.arm_output_check.isChecked()

        # A newly selected actuator must never inherit an armed hardware state
        # or accumulated PID history from the previous trim coil.
        self.arm_output_check.setChecked(False)
        self._actuator_index = pending
        self._pid_channel = pending
        self._invalidate_ga_recovery_reference()
        self._baseline_target = float("nan")
        self._last_proposed_target = float("nan")
        self._last_processed_beam_timestamp = 0.0

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
        self._reset_plot()
        self._refresh_live_readouts()
        self._refresh_ga_context()
        self._update_actuator_selection_controls()

        disarm_text = " — HARDWARE OUTPUT DISARMED" if output_was_armed else ""
        self.pid_status_label.setText(
            f"ACTUATOR CHANGED: {previous_name} → {new_name}{disarm_text} — VERIFY BEFORE STARTING PID"
        )

    def _update_actuator_selection_controls(self) -> None:
        """Show the distinction between the pending and active actuator."""
        if not hasattr(self, "actuator_selector"):
            return

        active_name = self.context.channel_name(self._actuator_index)
        pending_name = self.context.channel_name(self._pending_actuator_index)
        pending_change = self._pending_actuator_index != self._actuator_index

        if hasattr(self, "active_actuator_label"):
            if pending_change:
                self.active_actuator_label.setText(
                    f"ACTIVE: {active_name}     |     PENDING: {pending_name}"
                )
                self.active_actuator_label.setStyleSheet(
                    f"color: {T.amber}; font-size: 12px; font-weight: 600;"
                )
            else:
                self.active_actuator_label.setText(f"ACTIVE ACTUATOR: {active_name}")
                self.active_actuator_label.setStyleSheet(
                    f"color: {T.green}; font-size: 12px; font-weight: 600;"
                )

        if hasattr(self, "apply_actuator_button"):
            if pending_change:
                self.apply_actuator_button.setText(f"APPLY {pending_name}")
            else:
                self.apply_actuator_button.setText(f"{active_name} ACTIVE")
            self.apply_actuator_button.setEnabled(
                pending_change and not self._pid_running and not self._ga_auto_active
            )

    def _on_target_changed(self, index: int, _value: float) -> None:
        # The 5 Hz display timer will show the latest target. Avoid forcing a
        # full monitoring-table repaint for every PID target update.
        _ = (index, _value)

    def _on_mode_changed(self, mode: str) -> None:
        if self._pid_running and mode != ControlMode.PID.value:
            reason = f"CONTROL MODE CHANGED TO {mode}"
            if self._ga_auto_active:
                self._abort_automatic_ga(reason, attempt_restore=False)
            else:
                self.stop_pid(
                    reason=f"PID STOPPED — {reason}",
                    restore_manual=False,
                )

    def refresh(self) -> None:
        if hasattr(self, "actuator_selector"):
            self.actuator_selector.blockSignals(True)
            self.actuator_selector.setCurrentIndex(self._pending_actuator_index)
            self.actuator_selector.blockSignals(False)
            self._update_actuator_selection_controls()
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
            f"color: {color}; font-size: 10px; font-weight: 600; "
            "padding: 1px 2px; border-bottom: 1px solid #1B252C;"
        )

    def _refresh_display(self) -> None:
        """Refresh readouts and only the currently visible plot workspace."""
        self._refresh_live_readouts()
        if not hasattr(self, "control_tabs") or self.control_tabs.currentIndex() == 0:
            self._refresh_pid_plots()
        else:
            self._refresh_ga_live_plots()

    def _refresh_pid_plots(self) -> None:
        if not self._plot_t:
            return
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
        self.tc_plot.set_data(
            self._plot_t,
            self._plot_tc_target,
            self._plot_tc_actual,
        )

    def _refresh_ga_live_plots(self) -> None:
        if not self._ga_live_t or not hasattr(self, "ga_live_beam_plot"):
            return
        self.ga_live_beam_plot.set_data(
            self._ga_live_t,
            self._ga_live_setpoint,
            self._ga_live_beam,
        )
        self.ga_live_error_plot.set_data(
            self._ga_live_t,
            self._ga_live_deadband,
            self._ga_live_abs_error,
        )
        self.ga_live_tc_plot.set_data(
            self._ga_live_t,
            self._ga_live_tc_target,
            self._ga_live_tc_actual,
        )

    def _refresh_live_readouts(self) -> None:
        if not hasattr(self, "actuator_display"):
            return

        actuator_name = self.context.channel_name(self._actuator_index)
        if hasattr(self, "compact_actuator_status"):
            self.compact_actuator_status.setText(actuator_name)
        if hasattr(self, "compact_mode_status"):
            armed = bool(self.arm_output_check.isChecked()) if hasattr(self, "arm_output_check") else False
            self.compact_mode_status.setText("ARMED" if armed else "PREVIEW")
            self.compact_mode_status.setStyleSheet(
                f"color: {T.green if armed else T.amber}; font-size: 10px; font-weight: 600; "
                "padding: 1px 2px; border-bottom: 1px solid #1B252C;"
            )
        self.controlled_display.setText("BEAM CURRENT")
        self.actuator_display.setText(actuator_name)
        if hasattr(self, "tc_plot_title"):
            self.tc_plot_title.setText(
                f"{actuator_name} TARGET AND MEASURED CURRENT"
            )
        if hasattr(self, "tc_plot_legend"):
            self.tc_plot_legend.setText(
                f"Cyan = {actuator_name} confirmed target     Orange = {actuator_name} measured current"
            )
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
                f"color: {T.green}; font-size: 9px; font-weight: 600; "
                "padding: 1px 2px; border-bottom: 1px solid #1B252C;"
            )
            if hasattr(self, "compact_beam_status"):
                self.compact_beam_status.setText("OK")
                self.compact_beam_status.setStyleSheet(
                    f"color: {T.green}; font-size: 10px; font-weight: 600; "
                    "padding: 1px 2px; border-bottom: 1px solid #1B252C;"
                )
        else:
            self.actual_display.setText("—")
            self.error_display.setText("—")
            self.abs_error_display.setText("—")
            self.beam_source_status.setText(str(snapshot.get("status", "NO DATA")))
            self.beam_source_status.setStyleSheet(
                f"color: {T.red}; font-size: 9px; font-weight: 600; "
                "padding: 1px 2px; border-bottom: 1px solid #1B252C;"
            )
            if hasattr(self, "compact_beam_status"):
                self.compact_beam_status.setText("NO DATA")
                self.compact_beam_status.setStyleSheet(
                    f"color: {T.red}; font-size: 10px; font-weight: 600; "
                    "padding: 1px 2px; border-bottom: 1px solid #1B252C;"
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
        tc_actual = self.context.actual(self._actuator_index)
        if math.isfinite(tc_actual):
            self.tc_actual_display.setText(f"{tc_actual:.2f} A")
        else:
            self.tc_actual_display.setText("—")
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

        if hasattr(self, "pid_sqlite_status_display"):
            logger_status = self.pid_logger.status()
            if logger_status.get("disabled", False):
                text = "DISABLED"
                color = T.dim
                tooltip = (
                    "PID SQLite recording is disabled. No PID database, "
                    "logging thread, or logging queue is active."
                )
            elif logger_status["last_error"]:
                text = "ERROR"
                color = T.red
                tooltip = (
                    f"{logger_status['last_error']}\n"
                    f"{logger_status['db_path']}"
                )
            else:
                rate_hz = float(logger_status.get("sample_rate_hz", 5.0))
                text = (
                    f"RECORDING {rate_hz:.0f} Hz" if self._pid_running else "READY"
                )
                if logger_status["dropped"]:
                    text += f" | DROP {logger_status['dropped']}"
                    color = T.amber
                else:
                    color = T.green if self._pid_running else T.cyan
                tooltip = (
                    f"{logger_status['db_path']}\n"
                    f"logging rate: {rate_hz:.1f} samples/s\n"
                    f"written samples: {logger_status['written_samples']}\n"
                    f"decimated control samples: {logger_status.get('skipped', 0)}\n"
                    f"queued: {logger_status['queued']}"
                )
            self.pid_sqlite_status_display.setText(text)
            self.pid_sqlite_status_display.setToolTip(tooltip)
            self.pid_sqlite_status_display.setStyleSheet(
                f"color: {color}; font-size: 10px; font-weight: 600; "
                "padding: 1px 2px; border-bottom: 1px solid #1B252C;"
            )

    # --------------------------------------------------------------- PID
    def _pid_settings(
        self,
    ) -> tuple[PIDGains, PIDLimits, AdaptiveDirectionSettings]:
        gains = PIDGains(
            kp=self.kp_spin.value(),
            ki=self.ki_spin.value(),
            kd=self.kd_spin.value(),
        )
        # No separate operator-adjustable output or integral limits are used.
        # The PID magnitude and integral state receive only a broad automatic
        # numerical guard equal to the configured TC operating span. Therefore,
        # the effective actuator restriction is the visible TC min/max range;
        # the physical current-change rate remains enforced by the LabVIEW ramp.
        tc_low = float(self.tc_min_spin.value())
        tc_high = float(self.tc_max_spin.value())
        tc_span = max(1.0e-6, tc_high - tc_low)
        limits = PIDLimits(
            output_min=0.0,
            output_max=tc_span,
            integral_min=0.0,
            integral_max=tc_span,
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

    def _start_pid_log_session(
        self,
        gains: PIDGains,
        limits: PIDLimits,
        settings: AdaptiveDirectionSettings,
        initial_beam_na: float,
    ) -> None:
        """Create a PID run identifier and queue a start event."""
        tc_actual = self.context.actual(self._pid_channel)
        self._pid_log_t0 = time.monotonic()
        self._pid_log_sample_index = 0
        self._pid_log_last_record_mono = 0.0
        prefix = "GA_PID" if self._ga_auto_active else "PID"
        self._pid_log_session_id = self.pid_logger.new_session_id(prefix)
        self.pid_logger.log_event(
            "PID_START",
            session_id=self._pid_log_session_id,
            details={
                "selected_tc_index": int(self._pid_channel),
                "selected_tc_number": int(self._pid_channel) + 1,
                "selected_tc_name": self.context.channel_name(self._pid_channel),
                "initial_setpoint_nA": float(self.setpoint_spin.value()),
                "initial_measured_beam_nA": float(initial_beam_na),
                "initial_tc_target_A": float(self.context.target(self._pid_channel)),
                "initial_tc_measured_A": (
                    float(tc_actual) if math.isfinite(tc_actual) else None
                ),
                "Kp": float(gains.kp),
                "Ki": float(gains.ki),
                "Kd": float(gains.kd),
                "deadband_nA": float(settings.deadband),
                "trend_tolerance_nA": float(settings.trend_tolerance),
                "direction_check_s": float(settings.direction_check_interval),
                "initial_direction": int(settings.initial_direction),
                "loop_period_ms": int(self.loop_period_spin.value()),
                "derivative_filter_tau_s": float(limits.derivative_filter_tau),
                "output_min_A": float(limits.output_min),
                "output_max_A": float(limits.output_max),
                "integral_min_As": float(limits.integral_min),
                "integral_max_As": float(limits.integral_max),
                "tc_min_A": float(self.tc_min_spin.value()),
                "tc_max_A": float(self.tc_max_spin.value()),
                "hardware_armed": bool(self.arm_output_check.isChecked()),
                "ga_auto_active": bool(self._ga_auto_active),
                "database": str(self.pid_logger.db_path),
            },
        )

    def _stop_pid_log_session(self, reason: str) -> None:
        if self._pid_log_session_id is None:
            return
        self.pid_logger.log_event(
            "PID_STOP",
            session_id=self._pid_log_session_id,
            details={
                "reason": str(reason),
                "samples_queued": int(self._pid_log_sample_index),
                "logger_dropped_records": int(self.pid_logger.dropped_records),
            },
        )
        self._pid_log_session_id = None

    def _log_pid_sample(
        self,
        *,
        now: float,
        dt: float,
        sample_timestamp: float,
        snapshot: dict,
        gains: PIDGains,
        limits: PIDLimits,
        settings: AdaptiveDirectionSettings,
        result: PIDResult,
        current_target: float,
        proposed_target: float,
        applied_target: float,
        measured_tc: float,
        command_delta: float,
        target_limited: bool,
        output_accepted: bool | None,
        status_text: str,
    ) -> None:
        """Queue one complete PID sample for the background SQLite writer."""
        session_id = self._pid_log_session_id
        if session_id is None:
            return

        # Decimate before building the 50+ field record. This avoids repeated
        # timestamp formatting, widget reads, and dictionary allocation on the
        # GUI thread. Direction reversals are always retained.
        force_record = bool(result.direction_changed)
        if (
            not force_record
            and self._pid_log_last_record_mono > 0.0
            and float(now) - self._pid_log_last_record_mono < self._pid_log_interval_s
        ):
            return
        self._pid_log_last_record_mono = float(now)
        self._pid_log_sample_index += 1
        active_mode = getattr(self.context.active_mode, "value", self.context.active_mode)
        self.pid_logger.log_sample(
            {
                "timestamp_utc": self.pid_logger.utc_now_text(),
                "timestamp_epoch_s": time.time(),
                "session_id": session_id,
                "sample_index": int(self._pid_log_sample_index),
                "session_elapsed_s": max(
                    0.0, float(now) - float(self._pid_log_t0)
                ),
                "beam_sample_timestamp": float(sample_timestamp),
                "beam_age_s": float(snapshot.get("age_s", float("nan"))),
                "beam_status": str(snapshot.get("status", "")),
                "selected_tc_index": int(self._pid_channel),
                "selected_tc_number": int(self._pid_channel) + 1,
                "selected_tc_name": self.context.channel_name(self._pid_channel),
                "setpoint_nA": float(self.setpoint_spin.value()),
                "beam_nA": float(snapshot["value_nA"]),
                "signed_error_nA": float(result.error),
                "abs_error_nA": float(result.error_magnitude),
                "deadband_nA": float(settings.deadband),
                "trend_tolerance_nA": float(settings.trend_tolerance),
                "direction_check_s": float(settings.direction_check_interval),
                "initial_direction": int(settings.initial_direction),
                "direction": int(result.direction),
                "direction_changed": int(bool(result.direction_changed)),
                "error_trend": str(result.error_trend),
                "in_deadband": int(bool(result.in_deadband)),
                "kp": float(gains.kp),
                "ki": float(gains.ki),
                "kd": float(gains.kd),
                "p_term_a": float(result.proportional),
                "i_term_a": float(result.integral),
                "d_term_a": float(result.derivative),
                "pid_magnitude_a": float(result.pid_magnitude),
                "raw_pid_output_a": float(result.output),
                "signed_delta_tc_a": float(command_delta),
                "loop_dt_s": float(dt),
                "loop_period_ms": int(self.loop_period_spin.value()),
                "derivative_filter_tau_s": float(limits.derivative_filter_tau),
                "output_min_a": float(limits.output_min),
                "output_max_a": float(limits.output_max),
                "integral_min_as": float(limits.integral_min),
                "integral_max_as": float(limits.integral_max),
                "tc_min_a": float(self.tc_min_spin.value()),
                "tc_max_a": float(self.tc_max_spin.value()),
                "baseline_target_a": (
                    float(self._baseline_target)
                    if math.isfinite(self._baseline_target)
                    else None
                ),
                "tc_target_before_a": float(current_target),
                "tc_target_proposed_a": float(proposed_target),
                "tc_target_after_a": float(applied_target),
                "tc_measured_a": (
                    float(measured_tc) if math.isfinite(measured_tc) else None
                ),
                "target_limited": int(bool(target_limited)),
                "pid_saturated": int(bool(result.saturated)),
                "hardware_armed": int(bool(self.arm_output_check.isChecked())),
                "output_applied": int(bool(output_accepted)),
                "control_mode": str(active_mode),
                "ga_auto_active": int(bool(self._ga_auto_active)),
                "pid_status": str(status_text),
            }
        )

    def start_pid(self) -> None:
        if self._ga_auto_active and not self._ga_starting_pid:
            self.pid_status_label.setText(
                "PID START IS MANAGED BY THE ACTIVE AUTOMATIC GA SEQUENCE"
            )
            return
        if self._pending_actuator_index != self._actuator_index:
            pending_name = self.context.channel_name(self._pending_actuator_index)
            active_name = self.context.channel_name(self._actuator_index)
            self.pid_status_label.setText(
                f"PID NOT STARTED — {pending_name} IS ONLY PENDING; PRESS APPLY {pending_name} "
                f"OR RETURN THE LIST TO ACTIVE {active_name}"
            )
            return
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
        self._start_pid_log_session(gains, limits, settings, actual)
        self._pid_timer.start()
        self.actuator_selector.setEnabled(False)
        self.apply_actuator_button.setEnabled(False)
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
        self._stop_pid_log_session(reason)
        self._pid_timer.stop()
        self._pid_running = False
        self._last_processed_beam_timestamp = 0.0
        if hasattr(self, "actuator_selector"):
            self.actuator_selector.setEnabled(not self._ga_auto_active)
        if hasattr(self, "initial_direction_combo"):
            self.initial_direction_combo.setEnabled(not self._ga_auto_active)
        self._update_actuator_selection_controls()
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
            reason = "CONTROL MODE LOST"
            if self._ga_auto_active:
                self._abort_automatic_ga(reason, attempt_restore=False)
            else:
                self.stop_pid(
                    reason=f"PID STOPPED — {reason}",
                    restore_manual=False,
                )
            return
        if self._actuator_index != self._pid_channel:
            reason = "ACTUATOR CHANGED"
            if self._ga_auto_active:
                self._abort_automatic_ga(reason, attempt_restore=False)
            else:
                self.stop_pid(reason=f"PID STOPPED — {reason}")
            return

        now = time.monotonic()
        snapshot = self.context.beam_snapshot(max_age_s=self._beam_stale_limit())
        actual = float(snapshot.get("value_nA", float("nan")))
        sample_timestamp = float(snapshot.get("timestamp", 0.0))
        if not bool(snapshot.get("valid")) or not math.isfinite(actual):
            reason = "BEAM FEEDBACK LOST OR STALE"
            if self._ga_auto_active:
                self._abort_automatic_ga(reason, attempt_restore=True)
            else:
                self.stop_pid(reason=f"PID STOPPED — {reason}")
            return

        # Execute the control law only once per genuinely new beam sample.
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
            dt = max(1e-6, self.loop_period_spin.value() / 1000.0)
        self._last_processed_beam_timestamp = sample_timestamp
        self._last_pid_time = now

        # TC min/max are the only operator-adjustable Python-side output
        # boundaries. Apply edits made during a running PID test on the next
        # genuinely fresh beam sample.
        tc_min = float(self.tc_min_spin.value())
        tc_max = float(self.tc_max_spin.value())
        if tc_min >= tc_max:
            reason = "TC TARGET MIN MUST BE BELOW TC TARGET MAX"
            if self._ga_auto_active:
                self._abort_automatic_ga(reason, attempt_restore=True)
            else:
                self.stop_pid(reason=f"PID STOPPED — {reason}")
            return
        current_limits = tuple(self.context.target_limits[self._pid_channel])
        if (
            not math.isclose(current_limits[0], tc_min, rel_tol=0.0, abs_tol=1.0e-12)
            or not math.isclose(current_limits[1], tc_max, rel_tol=0.0, abs_tol=1.0e-12)
        ):
            self.context.set_target_limits(self._pid_channel, tc_min, tc_max)

        current_target = self.context.target(self._pid_channel)
        if self._ga_auto_active and self.ga_evaluator.active:
            safety_reason = self.ga_evaluator.safety_reason(
                beam_nA=actual,
                tc_target_a=current_target,
                tc_actual_a=self.context.actual(self._pid_channel),
            )
            if safety_reason is not None:
                evaluation = self.ga_evaluator.abort(
                    safety_reason,
                    timestamp_s=sample_timestamp,
                )
                self._complete_automatic_candidate(evaluation)
                return

        try:
            gains, limits, settings = self._pid_settings()
            self.pid.set_gains(gains)
            self.pid.set_limits(limits)
            self.pid.set_settings(settings)
            result = self.pid.update(self.setpoint_spin.value(), actual, dt)
        except ValueError as exc:
            reason = str(exc)
            if self._ga_auto_active:
                self._abort_automatic_ga(reason, attempt_restore=True)
            else:
                self.stop_pid(reason=f"PID STOPPED — {reason}")
            return

        requested_target = current_target + result.output
        proposed_target = self.context.clamp_target(
            self._pid_channel, requested_target
        )
        # A hard limit means the command reached an absolute TC boundary or the
        # configured baseline ± excursion boundary. That is genuine actuator
        # saturation for the candidate evaluator.
        hard_target_limited = not math.isclose(
            proposed_target, requested_target, rel_tol=0.0, abs_tol=1e-12
        )
        # The GA rate limit is normal command shaping. It remains visible in
        # the status and logs, but it must not be counted as continuous
        # saturation and terminate otherwise valid candidates.
        rate_limited = False

        # Send only the increment that reaches the TC-limited target. This is
        # essential now that there is no separate ΔTC output limit in the GUI:
        # TC min/max remain authoritative even when the raw PID magnitude is
        # larger than the remaining distance to an actuator boundary.
        command_delta = proposed_target - current_target
        if self._ga_auto_active and self.ga_evaluator.active:
            ga_low, ga_high = self.ga_evaluator.target_bounds
            ga_limited_target = max(ga_low, min(ga_high, proposed_target))
            if not math.isclose(
                ga_limited_target, proposed_target, rel_tol=0.0, abs_tol=1e-12
            ):
                hard_target_limited = True
            proposed_target = ga_limited_target
            command_delta = proposed_target - current_target
            max_ga_step = max(0.0001, self.ga_max_tc_rate_spin.value() * dt)
            step_limited_delta = max(-max_ga_step, min(max_ga_step, command_delta))
            if not math.isclose(
                step_limited_delta, command_delta, rel_tol=0.0, abs_tol=1e-12
            ):
                rate_limited = True
            command_delta = step_limited_delta
            proposed_target = current_target + command_delta

        target_limited = bool(hard_target_limited or rate_limited)

        self.output_display.setText(f"{command_delta:+.4f} A")
        self.magnitude_display.setText(f"{result.pid_magnitude:.4f} A")
        self.p_display.setText(f"{result.proportional:.6f}")
        self.i_display.setText(f"{result.integral:.6f}")
        self.d_display.setText(f"{result.derivative:.6f}")
        self.error_display.setText(f"{result.error:+.4f} nA")
        self.abs_error_display.setText(f"{result.error_magnitude:.4f} nA")
        self._set_trend_display(result.error_trend)
        self.direction_display.setText(self._direction_text(result.direction))

        self._last_proposed_target = proposed_target
        self.current_target_display.setText(f"{current_target:.2f} A")
        self.proposed_target_display.setText(f"{proposed_target:.2f} A")

        elapsed = now - self._plot_t0
        self._plot_t.append(elapsed)
        self._plot_setpoint.append(self.setpoint_spin.value())
        self._plot_actual.append(actual)
        self._plot_abs_error.append(result.error_magnitude)
        self._plot_deadband.append(self.deadband_spin.value())
        self.pid_output_calculated.emit(
            self._pid_channel, command_delta, result
        )

        output_mode = "PID PREVIEW ACTIVE"
        output_accepted: bool | None = None
        if self.arm_output_check.isChecked() and self.output_callback is not None:
            try:
                accepted = self.output_callback(
                    self._pid_channel, command_delta, result
                )
            except Exception as exc:  # pragma: no cover - hardware boundary
                reason = f"OUTPUT CALLBACK FAILED: {exc}"
                if self._ga_auto_active:
                    self._abort_automatic_ga(reason, attempt_restore=False)
                else:
                    self.stop_pid(reason=f"PID STOPPED — {reason}")
                return
            if accepted is False:
                output_accepted = False
                reason = "OUTPUT CALLBACK REJECTED COMMAND"
                if self._ga_auto_active:
                    self._abort_automatic_ga(reason, attempt_restore=False)
                else:
                    self.stop_pid(reason=f"PID STOPPED — {reason}")
                return
            output_accepted = True
            output_mode = "PID ACTIVE — OUTPUT ARMED"
            self.current_target_display.setText(
                f"{self.context.target(self._pid_channel):.2f} A"
            )
        elif self.arm_output_check.isChecked():
            output_mode = "PID PREVIEW ACTIVE — NO HARDWARE CALLBACK"

        tc_target = self.context.target(self._pid_channel)
        tc_actual = self.context.actual(self._pid_channel)
        self._plot_tc_target.append(tc_target)
        self._plot_tc_actual.append(tc_actual)

        flags = [output_mode, f"d={result.direction:+d}", f"|e| {result.error_trend}"]
        if result.in_deadband:
            flags.append("TARGET HELD IN DEADBAND")
        if result.direction_changed:
            flags.append("DIRECTION REVERSED")
        if result.saturated or hard_target_limited:
            flags.append("PID/GA HARD LIMIT")
        if rate_limited:
            flags.append("GA RATE LIMITED")
        status_text = " — ".join(flags)
        self.pid_status_label.setText(status_text)

        self._log_pid_sample(
            now=now,
            dt=dt,
            sample_timestamp=sample_timestamp,
            snapshot=snapshot,
            gains=gains,
            limits=limits,
            settings=settings,
            result=result,
            current_target=current_target,
            proposed_target=proposed_target,
            applied_target=tc_target,
            measured_tc=tc_actual,
            command_delta=command_delta,
            target_limited=bool(target_limited),
            output_accepted=output_accepted,
            status_text=status_text,
        )

        if self._ga_auto_active and self.ga_evaluator.active:
            self._append_ga_live_response(
                timestamp_s=now,
                beam_nA=actual,
                setpoint_nA=self.setpoint_spin.value(),
                tc_target_a=tc_target,
                tc_actual_a=tc_actual,
            )
            if not math.isfinite(tc_actual):
                self._abort_automatic_ga(
                    "MEASURED-TC READBACK WAS LOST DURING AUTOMATIC GA",
                    attempt_restore=True,
                )
                return
            update = self.ga_evaluator.observe(
                timestamp_s=sample_timestamp,
                beam_nA=actual,
                tc_target_a=tc_target,
                tc_actual_a=tc_actual,
                pid_delta_a=command_delta,
                # Normal GA rate limiting is not a saturation violation.
                saturated=bool(result.saturated or hard_target_limited),
            )
            self._refresh_ga_runner_status(sample_timestamp)
            provisional = self.ga_evaluator.provisional_score()
            if hasattr(self, "ga_live_score_display"):
                if provisional is None:
                    self.ga_live_score_display.setText("WARM-UP")
                else:
                    self.ga_live_score_display.setText(f"{provisional[0]:.5g}")
            if update.result is not None:
                if hasattr(self, "ga_live_score_display"):
                    self.ga_live_score_display.setText(
                        self._format_ga_fitness(update.result.score)
                    )
                self._complete_automatic_candidate(update.result)
                return

    def _reset_plot(self) -> None:
        self._plot_t0 = time.monotonic()
        self._plot_t.clear()
        self._plot_setpoint.clear()
        self._plot_actual.clear()
        self._plot_abs_error.clear()
        self._plot_deadband.clear()
        self._plot_tc_target.clear()
        self._plot_tc_actual.clear()
        if hasattr(self, "plot"):
            self.plot.clear()
        if hasattr(self, "error_plot"):
            self.error_plot.clear()
        if hasattr(self, "tc_plot"):
            self.tc_plot.clear()

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
    def _set_ga_live_event(self, text: str, color: str | None = None) -> None:
        if not hasattr(self, "ga_live_event_label"):
            return
        accent = color or T.muted
        self.ga_live_event_label.setText(str(text))
        self.ga_live_event_label.setStyleSheet(
            f"color: {accent}; background: #0E151A; border: 1px solid {T.border}; "
            "border-radius: 5px; padding: 4px; font-size: 10px; font-weight: 600;"
        )

    def _reset_ga_live_response(self, candidate_text: str = "—") -> None:
        self._ga_live_t0 = time.monotonic()
        self._ga_live_t.clear()
        self._ga_live_setpoint.clear()
        self._ga_live_beam.clear()
        self._ga_live_abs_error.clear()
        self._ga_live_deadband.clear()
        self._ga_live_tc_target.clear()
        self._ga_live_tc_actual.clear()
        for name in (
            "ga_live_beam_plot",
            "ga_live_error_plot",
            "ga_live_tc_plot",
        ):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.clear()
        if hasattr(self, "ga_live_candidate_display"):
            self.ga_live_candidate_display.setText(candidate_text)
        if hasattr(self, "ga_live_phase_display"):
            self.ga_live_phase_display.setText("PREPARING")
        if hasattr(self, "ga_live_score_display"):
            self.ga_live_score_display.setText("—")
        self._set_ga_live_event(
            f"{candidate_text} is preparing. Live beam, error, and trim-coil "
            "traces will update on each new feedback sample.",
            T.cyan,
        )

    def _append_ga_live_response(
        self,
        *,
        timestamp_s: float,
        beam_nA: float,
        setpoint_nA: float,
        tc_target_a: float,
        tc_actual_a: float,
    ) -> None:
        values = (
            float(timestamp_s),
            float(beam_nA),
            float(setpoint_nA),
            float(tc_target_a),
            float(tc_actual_a),
        )
        if not all(math.isfinite(value) for value in values):
            return
        elapsed = max(0.0, values[0] - self._ga_live_t0)
        self._ga_live_t.append(elapsed)
        self._ga_live_setpoint.append(values[2])
        self._ga_live_beam.append(values[1])
        self._ga_live_abs_error.append(abs(values[2] - values[1]))
        self._ga_live_deadband.append(self.deadband_spin.value())
        self._ga_live_tc_target.append(values[3])
        self._ga_live_tc_actual.append(values[4])

    @staticmethod
    def _format_ga_fitness(score: float) -> str:
        """Show enough digits to distinguish nearby GA fitness values."""
        value = float(score)
        magnitude = abs(value)
        if magnitude >= 100_000.0:
            return f"{value:,.3f}"
        if magnitude >= 1_000.0:
            return f"{value:,.4f}"
        if magnitude >= 1.0:
            return f"{value:.6f}".rstrip("0").rstrip(".")
        return f"{value:.8g}"

    @staticmethod
    def _ga_common_plot_offset(values: list[float]) -> float:
        """Return a readable common offset for tightly clustered scores.

        This changes only graph coordinates. The complete score is still sent
        to the genetic algorithm and written to the GA CSV files.
        """
        finite = [float(value) for value in values if math.isfinite(float(value))]
        if not finite:
            return 0.0

        low = min(finite)
        high = max(finite)
        spread = max(0.0, high - low)
        center_scale = max(abs(low), abs(high), 1.0e-12)

        # A zero-referenced graph is useful when scores span a large fraction
        # of their magnitude. A local offset is useful when a large common
        # component (especially the safety penalty) flattens small differences.
        clustered = low > 0.0 and spread <= 0.40 * center_scale
        if not clustered:
            return 0.0

        if spread > 0.0:
            approximate_tick = spread / 4.0
        else:
            # Identical values cannot form a trend, but a local window still
            # makes the equality obvious and exposes any later change.
            approximate_tick = max(center_scale * 1.0e-6, 1.0e-9)

        exponent = math.floor(math.log10(max(approximate_tick, 1.0e-15)))
        resolution = 10.0 ** exponent
        offset = math.floor(low / resolution) * resolution
        return float(offset) if math.isfinite(offset) else 0.0

    def _update_ga_fitness_plot(self) -> None:
        """Repaint GA history using full scores or a labelled local zoom."""
        if not self._ga_fitness_history:
            return

        all_scores = list(self._ga_fitness_history) + list(self._ga_best_history)
        offset = self._ga_common_plot_offset(all_scores)
        self._ga_plot_offset = offset

        plotted_candidates = [value - offset for value in self._ga_fitness_history]
        plotted_best = [value - offset for value in self._ga_best_history]
        self.ga_plot.y_axis_label = "FITNESS Δ" if offset else "FITNESS SCORE"
        self.ga_plot.set_data(
            self._ga_evaluations,
            plotted_best,
            plotted_candidates,
        )

        low = min(all_scores)
        high = max(all_scores)
        spread = high - low
        if offset:
            offset_text = self._format_ga_fitness(offset)
            if math.isclose(spread, 0.0, rel_tol=0.0, abs_tol=1.0e-12):
                detail = (
                    "All recorded fitness values are exactly identical. "
                    f"The zoomed axis displays full fitness − {offset_text}."
                )
            else:
                detail = (
                    f"AUTO-ZOOM: plotted y = full fitness − {offset_text}. "
                    "The readouts, GA ranking, and CSV files keep the full score."
                )
        else:
            detail = (
                "Full fitness scale shown. Orange = candidate; green = best so "
                "far. Lower is better."
            )

        safety_flags = list(self._ga_safety_history)
        if safety_flags and all(safety_flags):
            detail += (
                " ALL RECORDED CANDIDATES WERE SAFETY-PENALIZED; the graph can "
                "show score differences, but these are not valid completed PID tests. "
                "Review the candidate reason and ga_runs/summary.csv."
            )
            explanation_color = T.red
        elif any(safety_flags):
            detail += (
                " Some candidates were safety-penalized; compare their reason in "
                "ga_runs/summary.csv before applying gains."
            )
            explanation_color = T.amber
        else:
            explanation_color = T.muted

        if hasattr(self, "ga_plot_explanation"):
            self.ga_plot_explanation.setText(detail)
            self.ga_plot_explanation.setStyleSheet(
                f"color: {explanation_color}; font-size: 11px;"
            )

    def _reset_ga_plot(self) -> None:
        self._ga_evaluation_count = 0
        self._ga_evaluations.clear()
        self._ga_fitness_history.clear()
        self._ga_best_history.clear()
        self._ga_safety_history.clear()
        self._ga_plot_offset = 0.0
        if hasattr(self, "ga_plot"):
            self.ga_plot.y_axis_label = "FITNESS SCORE"
            self.ga_plot.clear()
        if hasattr(self, "ga_last_fitness_display"):
            self.ga_last_fitness_display.setText("—")
            self.ga_last_fitness_display.setToolTip("")
        if hasattr(self, "ga_best_fitness_plot_display"):
            self.ga_best_fitness_plot_display.setText("—")
            self.ga_best_fitness_plot_display.setToolTip("")
        if hasattr(self, "ga_plot_explanation"):
            self.ga_plot_explanation.setText(
                "One point is added only after a candidate finishes. Orange = "
                "final candidate fitness; green = best so far. Lower is better."
            )
            self.ga_plot_explanation.setStyleSheet(
                f"color: {T.muted}; font-size: 11px;"
            )

    def _record_ga_fitness(
        self,
        fitness: float,
        *,
        safety_violation: bool = False,
    ) -> None:
        score = float(fitness)
        if not math.isfinite(score):
            return

        self._ga_evaluation_count += 1
        self._ga_evaluations.append(float(self._ga_evaluation_count))
        self._ga_fitness_history.append(score)
        self._ga_safety_history.append(bool(safety_violation))

        best_score = score
        if self.ga_tuner is not None:
            best = self.ga_tuner.best_candidate()
            if best is not None and best.fitness is not None:
                candidate_best = float(best.fitness)
                if math.isfinite(candidate_best):
                    best_score = candidate_best
        self._ga_best_history.append(best_score)

        score_text = self._format_ga_fitness(score)
        best_text = self._format_ga_fitness(best_score)
        self.ga_last_fitness_display.setText(score_text)
        self.ga_last_fitness_display.setToolTip(f"Full fitness: {score:.12g}")
        self.ga_best_fitness_plot_display.setText(best_text)
        self.ga_best_fitness_plot_display.setToolTip(
            f"Full best-so-far fitness: {best_score:.12g}"
        )
        self._update_ga_fitness_plot()

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

    def _ga_evaluation_configuration(
        self,
    ) -> tuple[GAEvaluationConfig, GAFitnessWeights]:
        config = GAEvaluationConfig(
            warmup_s=self.ga_warmup_spin.value(),
            evaluation_s=self.ga_evaluation_spin.value(),
            steady_state_window_s=self.ga_steady_window_spin.value(),
            max_tc_excursion_a=self.ga_max_excursion_spin.value(),
            max_abs_beam_error_nA=self.ga_max_beam_error_spin.value(),
            minimum_valid_beam_nA=self.ga_min_valid_beam_spin.value(),
            max_saturation_s=self.ga_max_saturation_spin.value(),
            minimum_scored_samples=10,
        ).validated()
        weights = GAFitnessWeights(
            tracking=self.ga_w_track_spin.value(),
            steady_state=self.ga_w_ss_spin.value(),
            movement=self.ga_w_move_spin.value(),
            saturation=self.ga_w_sat_spin.value(),
            oscillation=self.ga_w_osc_spin.value(),
        ).validated()
        return config, weights

    def start_ga(self) -> None:
        if self.manual_ga_mode_check.isChecked():
            self._start_manual_ga()
        else:
            self._start_automatic_ga()

    def _start_manual_ga(self) -> None:
        if self._ga_auto_active:
            return
        if self._pid_running:
            self.stop_pid(reason="PID STOPPED — MANUAL GA STARTED", restore_manual=False)
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
        self.ga_phase_display.setText("MANUAL")
        self.ga_status_label.setText(
            "MANUAL GA READY — TEST THE CURRENT CANDIDATE AND SUBMIT ITS FITNESS"
        )

    def _start_automatic_ga(self) -> None:
        if self._ga_auto_active:
            self.ga_status_label.setText("AUTOMATIC GA IS ALREADY ACTIVE")
            return
        if not self.auto_ga_arm_check.isChecked():
            self.ga_status_label.setText(
                "GA NOT STARTED — CHECK ARM AUTO GA AFTER VERIFYING ALL LIMITS"
            )
            return
        if not self.arm_output_check.isChecked():
            self.ga_status_label.setText(
                "GA NOT STARTED — ARM OUTPUT MUST ALSO BE CHECKED ON THE PID PAGE"
            )
            return
        if self.output_callback is None:
            self.ga_status_label.setText(
                "GA NOT STARTED — NO PID HARDWARE OUTPUT CALLBACK IS CONNECTED"
            )
            return
        if self._pending_actuator_index != self._actuator_index:
            self.ga_status_label.setText(
                "GA NOT STARTED — CONFIRM THE PENDING TC SELECTION ON THE PID PAGE"
            )
            return
        if not 0 <= self._actuator_index < 12:
            self.ga_status_label.setText("GA NOT STARTED — SELECT TC1 THROUGH TC12")
            return
        if not self.context.power_states[self._actuator_index]:
            self.ga_status_label.setText(
                f"GA NOT STARTED — {self.context.channel_name(self._actuator_index)} POWER IS OFF"
            )
            return
        if not self.context.enable_states[self._actuator_index]:
            self.ga_status_label.setText(
                f"GA NOT STARTED — {self.context.channel_name(self._actuator_index)} IS NOT ENABLED"
            )
            return

        snapshot = self.context.beam_snapshot(max_age_s=self._beam_stale_limit())
        beam = float(snapshot.get("value_nA", float("nan")))
        if not bool(snapshot.get("valid")) or not math.isfinite(beam):
            self.ga_status_label.setText(
                "GA NOT STARTED — VALID, FRESH BEAM FEEDBACK IS REQUIRED"
            )
            return
        if abs(beam) < self.ga_min_valid_beam_spin.value():
            self.ga_status_label.setText(
                f"GA NOT STARTED — |BEAM| {abs(beam):.4g} nA IS BELOW THE "
                f"{self.ga_min_valid_beam_spin.value():.4g} nA VALID-BEAM THRESHOLD"
            )
            return
        baseline_target = self.context.target(self._actuator_index)
        tc_actual = self.context.actual(self._actuator_index)
        if not math.isfinite(tc_actual):
            self.ga_status_label.setText(
                "GA NOT STARTED — A VALID MEASURED-TC READBACK IS REQUIRED"
            )
            return
        if not self._capture_ga_recovery_reference(show_status=False):
            self.ga_status_label.setText(
                "GA NOT STARTED — A KNOWN-GOOD RECOVERY REFERENCE COULD NOT BE CAPTURED"
            )
            return
        reference = self._ga_recovery_reference
        assert reference is not None
        baseline_target = reference.target_map[self._actuator_index]
        beam = reference.beam_nA
        if not (
            self.tc_min_spin.value() <= baseline_target <= self.tc_max_spin.value()
        ):
            self.ga_status_label.setText(
                f"GA NOT STARTED — BASELINE {baseline_target:.2f} A IS OUTSIDE "
                f"THE PID TC LIMITS {self.tc_min_spin.value():.2f} TO "
                f"{self.tc_max_spin.value():.2f} A"
            )
            return

        worst_restore_s = (
            self.ga_max_excursion_spin.value()
            / max(1.0e-6, self.ga_restore_step_spin.value())
            * (self._ga_sequence_timer.interval() / 1000.0)
            * max(1, len(reference.targets_a))
            + self.ga_restore_hold_spin.value()
        )
        if worst_restore_s > self.ga_restore_timeout_spin.value():
            self.ga_status_label.setText(
                f"GA NOT STARTED — THE WORST-CASE BASELINE RESTORE NEEDS ABOUT "
                f"{worst_restore_s:.1f} s, WHICH EXCEEDS THE "
                f"{self.ga_restore_timeout_spin.value():.1f} s TIMEOUT. INCREASE "
                f"THE RESTORE STEP OR TIMEOUT"
            )
            return

        initial_error = abs(self.setpoint_spin.value() - beam)
        if initial_error <= self.deadband_spin.value():
            self.ga_status_label.setText(
                f"GA NOT STARTED — INITIAL ERROR {initial_error:.4g} nA IS INSIDE "
                f"THE {self.deadband_spin.value():.4g} nA PID DEADBAND. SET A SMALL, "
                f"SAFE TEST REFERENCE OUTSIDE THE DEADBAND SO THE CANDIDATES CAN BE COMPARED"
            )
            return
        if initial_error > self.ga_max_beam_error_spin.value():
            self.ga_status_label.setText(
                f"GA NOT STARTED — INITIAL BEAM ERROR {initial_error:.4g} nA EXCEEDS "
                f"THE {self.ga_max_beam_error_spin.value():.4g} nA ABORT LIMIT"
            )
            return

        if self._pid_running:
            self.stop_pid(reason="PID STOPPED — AUTOMATIC GA STARTED", restore_manual=False)

        try:
            bounds, tuning_config = self._ga_configuration()
            evaluation_config, weights = self._ga_evaluation_configuration()
            seed_gains = PIDGains(
                self.kp_spin.value(), self.ki_spin.value(), self.kd_spin.value()
            ).validated()
            for name, value, limits in (
                ("Kp", seed_gains.kp, bounds.kp),
                ("Ki", seed_gains.ki, bounds.ki),
                ("Kd", seed_gains.kd, bounds.kd),
            ):
                if not limits[0] <= value <= limits[1]:
                    raise ValueError(
                        f"CURRENT {name}={value:.6g} IS OUTSIDE THE SEARCH BOUNDS "
                        f"{limits[0]:.6g} TO {limits[1]:.6g}; EDIT THE "
                        f"{name} MIN/MAX BOUNDS IN THE GA TAB"
                    )
            self.ga_tuner = GAPIDTuner(bounds=bounds, config=tuning_config)
            candidate = self.ga_tuner.initialize(seed_gains)
            self.ga_evaluator = GACandidateEvaluator(evaluation_config, weights)
        except (ValueError, RuntimeError) as exc:
            self.ga_status_label.setText(f"GA NOT STARTED — {exc}")
            return

        self._ga_saved_gains = PIDGains(
            self.kp_spin.value(), self.ki_spin.value(), self.kd_spin.value()
        )
        self._ga_saved_target_limits = tuple(
            self.context.target_limits[self._actuator_index]
        )
        self._ga_baseline_target = baseline_target
        self._ga_baseline_beam = beam
        self._ga_pending_candidate = None
        self._ga_run_complete = False
        self._ga_abort_after_restore = False
        self._ga_abort_reason = ""
        self._ga_restore_stable_since = None
        self._ga_last_result = None
        self._ga_auto_active = True
        self._ga_sequence_state = "PREPARING"
        self._reset_ga_plot()
        self._create_ga_run_directory(evaluation_config, weights)
        self._set_ga_controls_locked(True)
        self.context.set_mode(ControlMode.GA_TUNING)
        self._present_candidate(candidate)
        self._start_automatic_candidate(candidate)

    def _create_ga_run_directory(
        self,
        config: GAEvaluationConfig,
        weights: GAFitnessWeights,
    ) -> None:
        self._ga_run_dir = None
        try:
            run_name = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            destination = Path(__file__).resolve().parents[4] / "Exports" / "GA" / run_name
            settings = "\n".join(
                [
                    f"actuator={self.context.channel_name(self._actuator_index)}",
                    f"setpoint_nA={self.setpoint_spin.value()}",
                    f"baseline_target_A={self._ga_baseline_target}",
                    f"baseline_readback_A={None if self._ga_recovery_reference is None else self._ga_recovery_reference.actual_map.get(self._actuator_index)}",
                    f"baseline_beam_nA={self._ga_baseline_beam}",
                    f"baseline_beam_tolerance_nA={self.ga_baseline_beam_tolerance_spin.value()}",
                    f"population={self.population_spin.value()}",
                    f"generations={self.generations_spin.value()}",
                    f"kp_bounds={self.kp_min_spin.value()},{self.kp_max_spin.value()}",
                    f"ki_bounds={self.ki_min_spin.value()},{self.ki_max_spin.value()}",
                    f"kd_bounds={self.kd_min_spin.value()},{self.kd_max_spin.value()}",
                    f"warmup_s={config.warmup_s}",
                    f"evaluation_s={config.evaluation_s}",
                    f"steady_state_window_s={config.steady_state_window_s}",
                    f"max_tc_excursion_A={config.max_tc_excursion_a}",
                    f"max_abs_beam_error_nA={config.max_abs_beam_error_nA}",
                    f"minimum_valid_beam_nA={config.minimum_valid_beam_nA}",
                    f"max_ga_tc_rate_A_per_s={self.ga_max_tc_rate_spin.value()}",
                    f"recovery_scope={self.ga_recovery_scope_combo.currentData()}",
                    f"recovery_targets_A={None if self._ga_recovery_reference is None else self._ga_recovery_reference.targets_a}",
                    f"recovery_readbacks_A={None if self._ga_recovery_reference is None else self._ga_recovery_reference.actuals_a}",
                    f"recovery_min_beam_fraction={self.ga_recovery_beam_fraction_spin.value() / 100.0}",
                    f"weights={weights}",
                    "",
                ]
            )
            file_writer.submit(write_text, destination / "run_settings.txt", settings)
            self._ga_run_dir = destination
        except Exception as exc:  # pragma: no cover - file-system boundary
            self.ga_status_label.setText(
                f"GA WARNING — DATA LOG DIRECTORY COULD NOT BE CREATED: {exc}"
            )

    def _start_automatic_candidate(self, candidate: PIDCandidate) -> None:
        if not self._ga_auto_active or self.ga_tuner is None:
            return
        snapshot = self.context.beam_snapshot(max_age_s=self._beam_stale_limit())
        beam = float(snapshot.get("value_nA", float("nan")))
        if not bool(snapshot.get("valid")) or not math.isfinite(beam):
            self._abort_automatic_ga("FRESH BEAM DATA LOST BEFORE CANDIDATE START", attempt_restore=True)
            return

        self._present_candidate(candidate)
        self._reset_ga_live_response(
            f"G{candidate.generation + 1} / C{candidate.index + 1}"
        )
        now = time.monotonic()
        sample_clock = float(snapshot.get("timestamp", 0.0))
        evaluation_start = (
            sample_clock
            if math.isfinite(sample_clock) and sample_clock > 0.0
            else now
        )
        self.ga_evaluator.start(
            candidate_number=candidate.index + 1,
            generation_number=candidate.generation + 1,
            gains=candidate.gains,
            setpoint_nA=self.setpoint_spin.value(),
            baseline_target_a=self._ga_baseline_target,
            baseline_actual_a=(
                self._ga_recovery_reference.actual_map[self._actuator_index]
                if self._ga_recovery_reference is not None
                else self.context.actual(self._actuator_index)
            ),
            timestamp_s=evaluation_start,
        )
        self._ga_sequence_state = "EVALUATING"
        self._ga_starting_pid = True
        try:
            self.start_pid()
        finally:
            self._ga_starting_pid = False
        if not self._pid_running:
            self._abort_automatic_ga("PID COULD NOT START FOR GA CANDIDATE", attempt_restore=True)
            return

        self._ga_sequence_timer.start()
        self._refresh_ga_runner_status(now)
        self.ga_status_label.setText(
            f"AUTO GA — GENERATION {candidate.generation + 1}, "
            f"CANDIDATE {candidate.index + 1} — WARM-UP/RUN IN PROGRESS"
        )

    def _complete_automatic_candidate(self, result: GAEvaluationResult) -> None:
        if not self._ga_auto_active or self.ga_tuner is None:
            return
        self._ga_last_result = result
        self.stop_pid(
            reason=f"PID STOPPED — GA CANDIDATE FITNESS {result.score:.6g}",
            restore_manual=False,
        )
        self._log_ga_result(result)
        try:
            next_candidate = self.ga_tuner.submit_fitness(result.score)
        except RuntimeError as exc:
            self._abort_automatic_ga(str(exc), attempt_restore=True)
            return
        self._record_ga_fitness(
            result.score, safety_violation=result.safety_violation
        )
        self._ga_pending_candidate = next_candidate
        self._ga_run_complete = self.ga_tuner.finished
        if hasattr(self, "ga_live_score_display"):
            self.ga_live_score_display.setText(
                self._format_ga_fitness(result.score)
            )
        if result.safety_violation:
            self.ga_terms_display.setText("SAFETY PENALTY")
            if hasattr(self, "ga_live_phase_display"):
                self.ga_live_phase_display.setText("PENALIZED")
            self._set_ga_live_event(
                f"Candidate safety penalty: {result.reason}. PID is stopped and "
                "the known-good trim-coil/readback/beam reference is now being restored.",
                T.red,
            )
            restore_status = (
                f"CANDIDATE PENALIZED — {result.reason} — FITNESS "
                f"{result.score:.6g} — RESTORING BASELINE"
            )
        else:
            if hasattr(self, "ga_live_phase_display"):
                self.ga_live_phase_display.setText("COMPLETE")
            self._set_ga_live_event(
                f"Candidate completed with fitness {result.score:.5g}. The known-good "
                "reference is being restored before the next candidate.",
                T.green,
            )
            self.ga_terms_display.setText(
                f"T {result.terms.tracking:.3g} | SS {result.terms.steady_state:.3g} | "
                f"M {result.terms.movement:.3g} | S {result.terms.saturation:.3g} | "
                f"O {result.terms.oscillation:.3g}"
            )
            restore_status = (
                f"CANDIDATE FITNESS {result.score:.6g} — RESTORING TC BASELINE"
            )
        self._refresh_ga_progress()
        self._begin_ga_restore(restore_status)

    def _log_ga_result(self, result: GAEvaluationResult) -> None:
        if self._ga_run_dir is None:
            return
        try:
            filename = (
                f"generation_{result.generation_number:03d}_"
                f"candidate_{result.candidate_number:03d}.csv"
            )
            file_writer.submit(write_evaluation_csv, deepcopy(result), self._ga_run_dir / filename)
            file_writer.submit(append_summary_csv, deepcopy(result), self._ga_run_dir / "summary.csv")
        except Exception as exc:  # pragma: no cover - file-system boundary
            self.ga_status_label.setText(f"GA DATA LOG WARNING — {exc}")

    def _begin_ga_restore(self, status: str) -> None:
        if not self._ga_auto_active:
            return
        if self._pid_running:
            self.stop_pid(
                reason="PID STOPPED — RESTORING GA REFERENCE",
                restore_manual=False,
            )
        reference = self._ga_recovery_reference
        if reference is None:
            self._finalize_automatic_ga(
                False,
                "RECOVERY BLOCKED — NO KNOWN-GOOD REFERENCE WAS CAPTURED",
            )
            return
        try:
            recovery_config = GARecoveryConfig(
                command_step_a=self.ga_restore_step_spin.value(),
                target_tolerance_a=0.005,
                actual_tolerance_a=self.ga_restore_tolerance_spin.value(),
                minimum_beam_nA=self.ga_min_valid_beam_spin.value(),
                minimum_beam_fraction=(
                    self.ga_recovery_beam_fraction_spin.value() / 100.0
                ),
                beam_reference_tolerance_nA=(
                    self.ga_baseline_beam_tolerance_spin.value()
                ),
                stable_hold_s=self.ga_restore_hold_spin.value(),
                timeout_s=self.ga_restore_timeout_spin.value(),
            ).validated()
            self.ga_recovery_manager.start(
                reference=reference,
                config=recovery_config,
                timestamp_s=time.monotonic(),
            )
        except ValueError as exc:
            self._finalize_automatic_ga(
                False,
                f"RECOVERY CONFIGURATION ERROR — {str(exc).upper()}",
            )
            return

        self._ga_sequence_state = "RESTORING"
        self._ga_restore_started = time.monotonic()
        self._ga_restore_stable_since = None
        self.context.set_mode(ControlMode.PID)
        self._set_ga_controls_locked(True)
        self.ga_phase_display.setText("RESTORING")
        if hasattr(self, "ga_live_phase_display"):
            self.ga_live_phase_display.setText("RECOVERY")
        self.ga_status_label.setText(status)
        self._ga_sequence_timer.start()

    def _ga_sequence_tick(self) -> None:
        if not self._ga_auto_active:
            self._ga_sequence_timer.stop()
            return

        now = time.monotonic()
        if self._ga_sequence_state == "EVALUATING":
            if not self._pid_running:
                self._abort_automatic_ga(
                    "PID STOPPED UNEXPECTEDLY DURING CANDIDATE EVALUATION",
                    attempt_restore=True,
                )
                return
            if not self.auto_ga_arm_check.isChecked():
                self._abort_automatic_ga(
                    "ARM AUTO GA WAS REMOVED DURING AUTOMATIC GA",
                    attempt_restore=True,
                )
                return
            if not self.arm_output_check.isChecked():
                self._abort_automatic_ga(
                    "ARM OUTPUT WAS REMOVED DURING AUTOMATIC GA",
                    attempt_restore=False,
                )
                return
            index = self._actuator_index
            if not self.context.power_states[index] or not self.context.enable_states[index]:
                self._abort_automatic_ga(
                    f"{self.context.channel_name(index)} POWER OR ENABLE WAS REMOVED",
                    attempt_restore=False,
                )
                return
            self._refresh_ga_runner_status(now)
            return

        if self._ga_sequence_state == "RESTORING":
            self._ga_restore_tick(now)

    def _ga_restore_tick(self, now: float) -> None:
        if self.output_callback is None or not self.arm_output_check.isChecked():
            self._finalize_automatic_ga(
                False,
                "REFERENCE RECOVERY BLOCKED — OUTPUT IS NOT ARMED",
            )
            return
        reference = self._ga_recovery_reference
        if reference is None:
            self._finalize_automatic_ga(
                False,
                "REFERENCE RECOVERY BLOCKED — NO REFERENCE IS AVAILABLE",
            )
            return
        for index, _target in reference.targets_a:
            if not self.context.power_states[index] or not self.context.enable_states[index]:
                self._finalize_automatic_ga(
                    False,
                    f"REFERENCE RECOVERY BLOCKED — "
                    f"{self.context.channel_name(index)} IS OFF OR DISABLED",
                )
                return
        if not self.context.can_write(ControlMode.PID):
            self.context.set_mode(ControlMode.PID)

        command = self.ga_recovery_manager.next_command(
            self.context.targets_snapshot()
        )
        if command is not None:
            try:
                accepted = self.output_callback(
                    command.channel_index,
                    command.delta_a,
                    self.pid.last_result,
                )
            except Exception as exc:  # pragma: no cover - hardware boundary
                self._finalize_automatic_ga(
                    False,
                    f"REFERENCE RECOVERY CALLBACK FAILED: {exc}",
                )
                return
            if accepted is False:
                self._finalize_automatic_ga(
                    False,
                    f"REFERENCE RECOVERY COMMAND WAS REJECTED FOR "
                    f"{self.context.channel_name(command.channel_index)}",
                )
                return

        beam_snapshot = self.context.beam_snapshot(
            max_age_s=self._beam_stale_limit()
        )
        restore_beam = float(beam_snapshot.get("value_nA", float("nan"))) if beam_snapshot.get("valid") else float("nan")
        update = self.ga_recovery_manager.observe(
            timestamp_s=now,
            current_targets_a=self.context.targets_snapshot(),
            actual_values_a=list(self.context.actual_values),
            beam_nA=restore_beam,
        )

        active_target = self.context.target(self._actuator_index)
        active_actual = self.context.actual(self._actuator_index)
        self._append_ga_live_response(
            timestamp_s=now,
            beam_nA=restore_beam,
            setpoint_nA=self.setpoint_spin.value(),
            tc_target_a=active_target,
            tc_actual_a=active_actual,
        )
        self.ga_time_display.setText(
            f"REC {update.elapsed_s:.1f}/{self.ga_restore_timeout_spin.value():.1f} s"
        )
        self.ga_status_label.setText(update.status)
        if hasattr(self, "ga_live_phase_display"):
            self.ga_live_phase_display.setText("RECOVERY")
        self._set_ga_live_event(
            update.status,
            T.green if update.complete else (T.red if update.timed_out else T.amber),
        )

        if update.complete:
            self._finish_ga_restore()
            return
        if update.timed_out:
            self._finalize_automatic_ga(
                False,
                update.status,
            )

    def _finish_ga_restore(self) -> None:
        if self._ga_abort_after_restore:
            self._finalize_automatic_ga(False, self._ga_abort_reason or "GA ABORTED")
            return
        if self._ga_run_complete:
            self._finalize_automatic_ga(True, "AUTOMATIC GA COMPLETE")
            return
        candidate = self._ga_pending_candidate
        if candidate is None:
            self._finalize_automatic_ga(False, "GA HAS NO NEXT CANDIDATE")
            return
        self._ga_pending_candidate = None
        self.context.set_mode(ControlMode.GA_TUNING)
        self._start_automatic_candidate(candidate)

    def _abort_automatic_ga(self, reason: str, *, attempt_restore: bool) -> None:
        if not self._ga_auto_active:
            return
        reason = str(reason)
        if self.ga_evaluator.active:
            result = self.ga_evaluator.abort(reason, timestamp_s=time.monotonic())
            self._ga_last_result = result
            self._log_ga_result(result)
        if self._pid_running:
            self.stop_pid(reason=f"PID STOPPED — {reason}", restore_manual=False)
        self._ga_abort_after_restore = True
        self._ga_abort_reason = reason
        if (
            attempt_restore
            and self.output_callback is not None
            and self.arm_output_check.isChecked()
            and self._ga_recovery_reference is not None
        ):
            self._begin_ga_restore(
                f"GA ABORTED — {reason} — RESTORING KNOWN-GOOD REFERENCE"
            )
        else:
            self._finalize_automatic_ga(False, reason)

    def _finalize_automatic_ga(self, success: bool, reason: str) -> None:
        self._ga_sequence_timer.stop()
        if self._pid_running:
            self.stop_pid(reason="PID STOPPED — GA FINALIZATION", restore_manual=False)

        saved_gains = self._ga_saved_gains
        saved_limits = self._ga_saved_target_limits
        self._ga_auto_active = False
        self._ga_sequence_state = "COMPLETE" if success else "ABORTED"
        if saved_gains is not None:
            self.kp_spin.setValue(saved_gains.kp)
            self.ki_spin.setValue(saved_gains.ki)
            self.kd_spin.setValue(saved_gains.kd)
        if saved_limits is not None:
            self.context.set_target_limits(
                self._actuator_index, saved_limits[0], saved_limits[1]
            )
        self.context.set_mode(ControlMode.MANUAL)
        self.arm_output_check.setChecked(False)
        self.auto_ga_arm_check.setChecked(False)
        self._set_ga_controls_locked(False)
        self._set_manual_score_controls()
        self._refresh_ga_progress()

        log_text = f" — LOGS: {self._ga_run_dir}" if self._ga_run_dir is not None else ""
        if hasattr(self, "ga_live_phase_display"):
            self.ga_live_phase_display.setText("COMPLETE" if success else "ABORTED")
        self._set_ga_live_event(
            reason,
            T.green if success else T.red,
        )
        self.ga_recovery_manager.reset()

        if success and self.ga_tuner is not None and self.ga_tuner.best_candidate() is not None:
            best = self.ga_tuner.best_candidate()
            assert best is not None
            self.ga_phase_display.setText("COMPLETE")
            self.ga_status_label.setText(
                f"AUTOMATIC GA COMPLETE — BEST FITNESS {float(best.fitness):.6g}. "
                f"ORIGINAL WORKING GAINS WERE RESTORED; REVIEW AND PRESS APPLY BEST GAINS "
                f"TO LOAD Kp={best.gains.kp:.6g}, Ki={best.gains.ki:.6g}, "
                f"Kd={best.gains.kd:.6g}{log_text}"
            )
        else:
            self.ga_phase_display.setText("ABORTED")
            self.ga_status_label.setText(f"AUTOMATIC GA ABORTED — {reason}{log_text}")

        self._ga_pending_candidate = None
        self._ga_run_complete = False
        self._ga_abort_after_restore = False
        self._ga_abort_reason = ""
        self._ga_saved_gains = None
        self._ga_saved_target_limits = None
        self._ga_baseline_beam = float("nan")

    def _set_ga_controls_locked(self, locked: bool) -> None:
        for widget in getattr(self, "_ga_config_widgets", []):
            widget.setEnabled(not locked)
        self.start_ga_button.setEnabled(not locked)
        self.apply_best_button.setEnabled(not locked)
        self.fitness_spin.setEnabled(not locked and self.manual_ga_mode_check.isChecked())
        self.submit_fitness_button.setEnabled(
            not locked and self.manual_ga_mode_check.isChecked()
        )

        # During an automatic experiment, candidate gains and every PID setting
        # are frozen. Programmatic candidate loading still works on disabled spin
        # boxes, but the operator cannot accidentally change the setpoint, limits,
        # actuator, or timing in the middle of a fitness test.
        pid_setting_widgets = (
            self.setpoint_spin,
            self.kp_spin,
            self.ki_spin,
            self.kd_spin,
            self.deadband_spin,
            self.trend_tolerance_spin,
            self.direction_check_spin,
            self.initial_direction_combo,
            self.loop_period_spin,
            self.derivative_tau_spin,
            self.tc_min_spin,
            self.tc_max_spin,
            self.beam_stale_spin,
            self.reset_i_deadband_check,
            self.reset_i_reverse_check,
            self.load_actual_button,
            self.capture_baseline_button,
            self.reset_button,
            self.start_pid_button,
            self.stop_pid_button,
            self.actuator_selector,
            self.apply_actuator_button,
        )
        for widget in pid_setting_widgets:
            widget.setEnabled(not locked)
        self.actuator_selector.setEnabled(not locked and not self._pid_running)
        self.initial_direction_combo.setEnabled(not locked and not self._pid_running)
        self._update_actuator_selection_controls()

        # Keep both arming controls and ABORT available as emergency stops.
        self.arm_output_check.setEnabled(True)
        self.auto_ga_arm_check.setEnabled(True)
        self.abort_ga_button.setEnabled(True)

    def _refresh_ga_runner_status(self, timestamp_s: float | None = None) -> None:
        if not hasattr(self, "ga_phase_display"):
            return
        if self._ga_sequence_state == "RESTORING":
            self.ga_phase_display.setText("RESTORING")
            if hasattr(self, "ga_live_phase_display"):
                self.ga_live_phase_display.setText("RECOVERY")
            return
        if not self._ga_auto_active or not self.ga_evaluator.active:
            return
        now = time.monotonic() if timestamp_s is None else float(timestamp_s)
        phase = self.ga_evaluator.phase.value
        elapsed = self.ga_evaluator.elapsed_s(now)
        total = (
            self.ga_evaluator.config.warmup_s
            + self.ga_evaluator.config.evaluation_s
        )
        self.ga_phase_display.setText(phase)
        if hasattr(self, "ga_live_phase_display"):
            self.ga_live_phase_display.setText(phase)
        if phase == "WARMUP":
            self._set_ga_live_event(
                f"Candidate warm-up: {elapsed:.1f}/{self.ga_evaluator.config.warmup_s:.1f} s. "
                "The response is visible, but samples are not scored yet.",
                T.cyan,
            )
        else:
            self._set_ga_live_event(
                f"Candidate scoring in progress: {self.ga_evaluator.scored_samples} samples. "
                "The displayed live fitness is provisional until the interval ends.",
                T.green,
            )
        self.ga_time_display.setText(f"{elapsed:.1f} / {total:.1f} s")
        self.ga_samples_display.setText(str(self.ga_evaluator.scored_samples))

    def abort_ga(self) -> None:
        if self._ga_auto_active:
            self._abort_automatic_ga("OPERATOR ABORT", attempt_restore=True)
            return
        self.ga_tuner = None
        self.ga_status_label.setText("GA ABORTED")
        self.ga_phase_display.setText("ABORTED")
        self._refresh_ga_progress()
        if self.context.can_write(ControlMode.GA_TUNING):
            self.context.set_mode(ControlMode.MANUAL)

    def submit_candidate_fitness(self, fitness: float) -> None:
        if self._ga_auto_active:
            self.ga_status_label.setText(
                "MANUAL FITNESS IS DISABLED DURING AUTOMATIC GA EVALUATION"
            )
            return
        if self.ga_tuner is None:
            self.ga_status_label.setText("START MANUAL GA BEFORE SUBMITTING FITNESS")
            return
        try:
            next_candidate = self.ga_tuner.submit_fitness(float(fitness))
        except RuntimeError as exc:
            self.ga_status_label.setText(str(exc).upper())
            return

        self._record_ga_fitness(float(fitness), safety_violation=False)
        if self.ga_tuner.finished:
            best = self.ga_tuner.best_candidate()
            if best is None:
                self.ga_status_label.setText("GA FINISHED — NO VALID CANDIDATE")
            else:
                self.ga_status_label.setText(
                    f"MANUAL GA COMPLETE — BEST FITNESS {float(best.fitness):.6g}"
                )
            self.context.set_mode(ControlMode.MANUAL)
            self._refresh_ga_progress()
            return

        if next_candidate is not None:
            self._present_candidate(next_candidate)
            self.ga_status_label.setText("NEXT MANUAL CANDIDATE READY — AWAITING FITNESS")

    def _present_candidate(self, candidate: PIDCandidate) -> None:
        self.kp_spin.setValue(candidate.gains.kp)
        self.ki_spin.setValue(candidate.gains.ki)
        self.kd_spin.setValue(candidate.gains.kd)
        self._refresh_pid_radar()
        self._refresh_ga_progress()
        self.candidate_requested.emit(candidate)

    def apply_best_gains(self) -> None:
        if self._ga_auto_active:
            self.ga_status_label.setText("BEST GAINS CANNOT BE APPLIED DURING AN ACTIVE RUN")
            return
        if self.ga_tuner is None or self.ga_tuner.best_candidate() is None:
            self.ga_status_label.setText("NO EVALUATED GA CANDIDATE IS AVAILABLE")
            return
        best = self.ga_tuner.best_candidate()
        assert best is not None
        self.kp_spin.setValue(best.gains.kp)
        self.ki_spin.setValue(best.gains.ki)
        self.kd_spin.setValue(best.gains.kd)
        self.ga_status_label.setText(
            f"BEST GAINS LOADED — Kp={best.gains.kp:.6g}, "
            f"Ki={best.gains.ki:.6g}, Kd={best.gains.kd:.6g}"
        )

    def _refresh_ga_progress(self) -> None:
        if self.ga_tuner is None:
            self.ga_generation_display.setText("—")
            self.ga_candidate_display.setText("—")
            self.ga_current_display.setText("—")
            self.ga_best_display.setText("—")
            if not self._ga_auto_active:
                self.ga_time_display.setText("—")
                self.ga_samples_display.setText("—")
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
                f"{float(best.fitness):.4g} | {best.gains.kp:.3g}, "
                f"{best.gains.ki:.3g}, {best.gains.kd:.3g}"
            )


__all__ = ["PIDGAControlTab", "PIDOutputCallback"]
