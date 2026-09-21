# -*- coding: utf-8 -*-
"""Modular Tesla-style cyclotron controller window.

Compatibility:
    The public class name and constructor remain compatible with the previous
    ``MagneticFieldControllerWindow`` used by the CNL control system.

Architecture:
    * This file owns the common header, upper navigation, channel table,
      live-data adapter, scaling, and control-queue output.
    * Manual, Sequence, and Multi-TC Sequence remain inside the Magnetic Field
      page because they share the compact channel-control workspace.
    * PID / GA Auto-Tune is a full-width upper tab because it needs more space.
      Its GUI remains in ``pid_ga_control_tab.py`` and imports the independent
      ``pid_controller.py`` and ``ga_pid_tuner.py`` engines.
"""

from __future__ import annotations

import math
import os
import queue as _queue
import sys
import time
from typing import Callable, List

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from scaling import TRIM_KEYS, get_scaler
from beam_cal import beam_cal

from controller_context import ControlMode, ControllerContext
from controller_theme import (
    CONTROLLER_QSS,
    Card,
    ClickLabel,
    PlotToggle,
    StatusDot,
    T,
    TeslaTabBar,
    bulk_button_css,
    flat_button_css,
    load_cnl_logo_pixmap,
    secondary_button_css,
    state_button_css,
    target_label_css,
)
from manual_control_tab import ManualControlTab
from multi_tc_sequence_tab import MultiTCSequenceTab
from pid_ga_control_tab import PIDGAControlTab, PIDOutputCallback
from sequence_control_tab import SequenceControlTab


CHANNEL_NAMES = [
    "TC1",
    "TC2",
    "TC3",
    "TC4",
    "TC5",
    "TC6",
    "TC7",
    "TC8",
    "TC9",
    "TC10",
    "TC11",
    "TC12",
    "MAIN MAGNET",
    "CENTERING BEAM",
]
NUM_CHANNELS = len(CHANNEL_NAMES)


class MagneticFieldControllerWindow(QWidget):
    """Tesla-style controller shell with modular operating-mode tabs."""

    def __init__(
        self,
        control_queue,
        target_values,
        plot_config,
        current_values_ref=None,
        data_queue=None,
    ):
        super().__init__()

        if len(target_values) < NUM_CHANNELS:
            raise ValueError(
                f"target_values must contain at least {NUM_CHANNELS} entries; "
                f"received {len(target_values)}"
            )

        self.control_queue = control_queue
        self.target_values = target_values
        self.plot_config = plot_config if plot_config is not None else {}
        self.current_values_ref = current_values_ref
        self.data_queue = data_queue
        self.scaler = get_scaler()

        self.actual_values = [0.0] * NUM_CHANNELS
        self._last_sample = None
        self.last_data_time = 0.0
        self.HOLD_SECONDS = 5.0
        self.controls_locked = False

        self.setWindowTitle("Cyclotron Controller")
        self.resize(1680, 900)
        self.setMinimumSize(1280, 720)
        self.setStyleSheet(CONTROLLER_QSS)

        here = os.path.dirname(os.path.abspath(__file__))
        self._cnl_logo_pixmap = load_cnl_logo_pixmap(here)
        if not self._cnl_logo_pixmap.isNull():
            self.setWindowIcon(QIcon(self._cnl_logo_pixmap))

        # One model is shared by every operating-mode tab.  The callback is set
        # after construction so send_update can use the fully initialized UI.
        self.context = ControllerContext(
            channel_names=CHANNEL_NAMES,
            target_values=self.target_values,
            plot_config=self.plot_config,
            send_callback=None,
            parent=self,
        )

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(18, 14, 18, 14)
        root_layout.setSpacing(8)
        root_layout.addWidget(self._build_header())
        root_layout.addWidget(self._build_subsystem_tabs(), 1)

        self.context.set_send_callback(self.send_update)
        self._connect_context()
        self._sync_all_channel_controls()
        self.update_display()

        self._rx_timer = QTimer(self)
        self._rx_timer.timeout.connect(self._poll_actual_data)
        self._rx_timer.start(50)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()

    # ---------------------------------------------------------------- Header
    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(16)

        brand = QLabel()
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setFixedSize(66, 56)
        brand.setStyleSheet("background: transparent; border: none;")
        if not self._cnl_logo_pixmap.isNull():
            brand.setPixmap(
                self._cnl_logo_pixmap.scaled(
                    62,
                    54,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            brand.setText("CNL")
            brand.setStyleSheet(
                f"background: transparent; border: 1px solid {T.muted}; "
                "border-radius: 8px; color: white; font-size: 15px;"
            )
        layout.addWidget(brand)

        layout.addWidget(self._vertical_divider())

        title = QLabel("CYCLOTRON CONTROLLER")
        title.setStyleSheet("font-size: 19px; font-weight: 500; letter-spacing: 2px;")
        layout.addWidget(title)

        self.controller_subtitle = QLabel("MAGNETIC FIELD CONTROLLER")
        self.controller_subtitle.setStyleSheet(
            f"color: {T.muted}; font-size: 12px; letter-spacing: 1px;"
        )
        layout.addWidget(self.controller_subtitle)
        layout.addStretch()

        live = QWidget()
        live_layout = QHBoxLayout(live)
        live_layout.setContentsMargins(0, 0, 0, 0)
        live_layout.setSpacing(8)
        self.live_dot = StatusDot(T.green)
        live_layout.addWidget(self.live_dot)
        self.live_label = QLabel("LIVE")
        self.live_label.setStyleSheet(f"color: {T.green}; font-size: 14px;")
        live_layout.addWidget(self.live_label)
        layout.addWidget(live)

        layout.addWidget(self._vertical_divider())
        self.mode_label = QLabel("MODE: MANUAL")
        self.mode_label.setStyleSheet(f"color: {T.cyan}; font-size: 13px;")
        layout.addWidget(self.mode_label)

        layout.addWidget(self._vertical_divider())
        self.clock_label = QLabel("--:--")
        self.clock_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.clock_label)

        layout.addWidget(self._vertical_divider())
        menu = QPushButton("☰")
        menu.setFixedSize(36, 36)
        menu.setCursor(Qt.CursorShape.PointingHandCursor)
        menu.setStyleSheet(flat_button_css())
        layout.addWidget(menu)
        return header

    @staticmethod
    def _vertical_divider() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setStyleSheet(f"color: {T.border};")
        line.setFixedHeight(32)
        return line

    # ---------------------------------------------------------- Subsystems
    def _build_subsystem_tabs(self) -> QTabWidget:
        """Build the full-width upper controller navigation.

        PID / GA is deliberately placed here instead of inside the compact
        Magnetic Field mode panel.  The PID workspace therefore receives the
        complete window area and can grow without crowding Manual or Sequence.
        """
        tabs = QTabWidget()
        tabs.setTabBar(TeslaTabBar())
        tabs.setDocumentMode(True)
        tabs.setStyleSheet("QTabWidget::pane { border: none; background: transparent; }")

        tabs.addTab(self._build_magnetic_page(), "MAGNETIC FIELD")

        # Full-page PID/GA workspace.  The implementation is still isolated in
        # pid_ga_control_tab.py and calls pid_controller.py + ga_pid_tuner.py.
        self.pid_tab = PIDGAControlTab(
            self.context, output_callback=self._apply_pid_delta_output
        )
        tabs.addTab(self.pid_tab, "PID / GA AUTO-TUNE")

        tabs.addTab(
            self._build_controller_placeholder(
                "SOURCE / EXTRACTION CONTROLLER",
                "A future SourceExtractionControllerPage can be imported here without changing the magnetic tabs.",
            ),
            "SOURCE / EXTRACTION",
        )
        tabs.addTab(
            self._build_controller_placeholder(
                "VACUUM / BEAM CONTROLLER",
                "A future VacuumBeamControllerPage can be imported here.",
            ),
            "VACUUM / BEAM",
        )
        tabs.addTab(
            self._build_controller_placeholder(
                "RF POWER CONTROLLER",
                "A future RFControllerPage can be imported here.",
            ),
            "RF POWER",
        )
        tabs.currentChanged.connect(self._on_subsystem_changed)
        self.subsystem_tabs = tabs
        return tabs

    def _build_controller_placeholder(self, title_text: str, message: str) -> QWidget:
        card = Card()
        layout = QVBoxLayout(card)
        title = QLabel(title_text)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 28px; font-weight: 500;")
        text = QLabel(message)
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setStyleSheet(f"color: {T.muted}; font-size: 17px;")
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(text)
        layout.addStretch()
        return card

    def _on_subsystem_changed(self, index: int) -> None:
        names = [
            "MAGNETIC FIELD CONTROLLER",
            "PID / GA AUTO-TUNE CONTROLLER",
            "SOURCE / EXTRACTION CONTROLLER",
            "VACUUM / BEAM CONTROLLER",
            "RF POWER CONTROLLER",
        ]
        if 0 <= index < len(names):
            self.controller_subtitle.setText(names[index])
        if index == 1 and hasattr(self, "pid_tab"):
            self.pid_tab.refresh()

    # ------------------------------------------------------ Magnetic page
    def _build_magnetic_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(self._build_channel_panel(), 53)
        layout.addWidget(self._build_mode_panel(), 47)
        return page

    def _build_channel_panel(self) -> QWidget:
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(0)

        header = QGridLayout()
        header.setContentsMargins(0, 0, 0, 6)
        header.setHorizontalSpacing(12)
        widths = [80, 200, 160, 140, 140]
        for column, width in enumerate(widths):
            header.setColumnMinimumWidth(column, width)

        for column, text in enumerate(("PLOT", "TARGET (A)", "CHANNEL")):
            label = QLabel(text)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(
                f"color: {T.muted}; font-size: 13px; letter-spacing: 0.5px;"
            )
            header.addWidget(label, 0, column)

        self.power_all_btn = self._build_bulk_header(
            header,
            column=3,
            title="POWER",
            initial_text="ALL ON",
            tooltip="Turn all magnetic-field power channels ON or OFF",
            handler=self._toggle_power_all,
        )
        self.enable_all_btn = self._build_bulk_header(
            header,
            column=4,
            title="ENABLE",
            initial_text="ALL ENABLE",
            tooltip="Enable or un-enable every magnetic-field channel",
            handler=self._toggle_enable_all,
        )
        header.setRowMinimumHeight(0, 58)
        layout.addLayout(header)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"color: {T.border_soft};")
        layout.addWidget(separator)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(0)
        for column, width in enumerate(widths):
            grid.setColumnMinimumWidth(column, width)

        self.plot_buttons: List[PlotToggle] = []
        self.labels: List[ClickLabel] = []
        self.channel_labels: List[ClickLabel] = []
        self.power_buttons: List[QPushButton] = []
        self.enable_buttons: List[QPushButton] = []
        # Backward-compatible attribute names used by older code.
        self.on_buttons = self.power_buttons
        self.en_buttons = self.enable_buttons

        for index, channel in enumerate(CHANNEL_NAMES):
            plot_button = PlotToggle(index)
            plot_button.setToolTip(f"Include {channel} in monitoring plots")
            plot_button.selected.connect(self._on_plot_flag_changed)
            self.plot_buttons.append(plot_button)
            grid.addWidget(plot_button, index, 0, alignment=Qt.AlignmentFlag.AlignCenter)

            target = ClickLabel(index, "0.00")
            target.clicked.connect(self._select_channel)
            target.setAlignment(Qt.AlignmentFlag.AlignCenter)
            target.setMinimumHeight(42)
            self.labels.append(target)
            grid.addWidget(target, index, 1)

            name = ClickLabel(index, channel)
            name.clicked.connect(self._select_channel)
            name.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            name.setStyleSheet(f"color: #C7D0D6; font-size: 14px;")
            self.channel_labels.append(name)
            grid.addWidget(name, index, 2)

            power = QPushButton("ON")
            power.setCheckable(True)
            power.setMinimumHeight(40)
            power.setCursor(Qt.CursorShape.PointingHandCursor)
            power.clicked.connect(
                lambda checked, idx=index: self.context.set_power_state(idx, checked, send=True)
            )
            self.power_buttons.append(power)
            grid.addWidget(power, index, 3)

            enable = QPushButton("EN")
            enable.setCheckable(True)
            enable.setMinimumHeight(40)
            enable.setCursor(Qt.CursorShape.PointingHandCursor)
            enable.clicked.connect(
                lambda checked, idx=index: self.context.set_enable_state(idx, checked, send=True)
            )
            self.enable_buttons.append(enable)
            grid.addWidget(enable, index, 4)

            if index < NUM_CHANNELS - 1:
                rule = QFrame()
                rule.setFrameShape(QFrame.Shape.HLine)
                rule.setStyleSheet(f"color: {T.border_soft};")
                grid.addWidget(rule, index, 0, 1, 5, alignment=Qt.AlignmentFlag.AlignBottom)
            grid.setRowMinimumHeight(index, 48)

        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 8, 0, 0)
        self.plot_all_btn = QPushButton("PLOT ALL")
        self.plot_all_btn.setCheckable(True)
        self.plot_all_btn.setStyleSheet(secondary_button_css())
        self.plot_all_btn.clicked.connect(self._toggle_plot_all)
        footer.addWidget(self.plot_all_btn)
        footer.addStretch()

        self.lock_btn = QPushButton("🔒  UNLOCK")
        self.lock_btn.setCheckable(True)
        self.lock_btn.setStyleSheet(secondary_button_css())
        self.lock_btn.clicked.connect(self._toggle_lock)
        footer.addWidget(self.lock_btn)
        layout.addLayout(footer)
        return card

    def _build_bulk_header(
        self,
        header: QGridLayout,
        *,
        column: int,
        title: str,
        initial_text: str,
        tooltip: str,
        handler,
    ) -> QPushButton:
        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(4)
        label = QLabel(title)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(
            f"color: {T.muted}; font-size: 13px; letter-spacing: 0.5px;"
        )
        button = QPushButton(initial_text)
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(28)
        button.clicked.connect(handler)
        wrapper_layout.addWidget(label)
        wrapper_layout.addWidget(button)
        header.addWidget(wrapper, 0, column)
        return button

    def _build_mode_panel(self) -> QWidget:
        """Compact magnetic-field operating modes.

        PID / GA is intentionally not created here; it lives in the full-width
        upper tab built by :meth:`_build_subsystem_tabs`.
        """
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tabs = QTabWidget()
        tabs.setTabBar(TeslaTabBar())
        tabs.setDocumentMode(True)
        tabs.setStyleSheet("QTabWidget::pane { border: none; background: transparent; }")

        self.manual_tab = ManualControlTab(self.context)
        self.sequence_tab = SequenceControlTab(self.context)
        self.multi_sequence_tab = MultiTCSequenceTab(self.context)

        tabs.addTab(self.manual_tab, "MANUAL")
        tabs.addTab(self.sequence_tab, "SEQUENCE")
        tabs.addTab(self.multi_sequence_tab, "MULTI-TC SEQUENCE")
        layout.addWidget(tabs)
        self.mode_tabs = tabs
        return card

    # ------------------------------------------------------------- Context
    @property
    def selected_index(self) -> int:
        return self.context.selected_index

    @selected_index.setter
    def selected_index(self, value: int) -> None:
        self.context.set_selected_index(int(value))

    def _connect_context(self) -> None:
        self.context.selected_channel_changed.connect(lambda _idx: self.update_display())
        self.context.target_changed.connect(lambda _idx, _value: self.update_display())
        self.context.power_states_changed.connect(lambda _states: self._sync_power_controls())
        self.context.enable_states_changed.connect(lambda _states: self._sync_enable_controls())
        self.context.plot_flags_changed.connect(lambda _states: self._sync_plot_controls())
        self.context.mode_changed.connect(self._on_mode_changed)
        self.context.status_changed.connect(self._show_status_message)

    def _select_channel(self, index: int) -> None:
        self.context.set_selected_index(index)
        self.update_display()

    def _on_plot_flag_changed(self, index: int, checked: bool) -> None:
        self.context.set_plot_flag(index, checked, send=True)

    def _on_mode_changed(self, mode: str) -> None:
        self.mode_label.setText(f"MODE: {mode}")
        if mode == ControlMode.MANUAL.value:
            self.mode_label.setStyleSheet(f"color: {T.cyan}; font-size: 13px;")
        elif mode in (ControlMode.PID.value, ControlMode.GA_TUNING.value):
            self.mode_label.setStyleSheet(f"color: {T.orange}; font-size: 13px;")
        else:
            self.mode_label.setStyleSheet(f"color: {T.amber}; font-size: 13px;")

    def _show_status_message(self, text: str) -> None:
        print(f"[Controller] {text}")

    # ---------------------------------------------------------- Row states
    def _apply_power_button_visual(self, button: QPushButton, bit_state: bool) -> None:
        # Preserve the original controller's action-label convention:
        # bit False -> button offers ON; bit True -> button offers OFF.
        button.setText("OFF" if bit_state else "ON")
        button.setToolTip(
            "Power bit is ON — click to turn OFF"
            if bit_state
            else "Power bit is OFF — click to turn ON"
        )
        button.setStyleSheet(
            state_button_css(T.green if bit_state else T.red, bit_state)
        )

    def _apply_enable_button_visual(self, button: QPushButton, bit_state: bool) -> None:
        # Same action-label convention as the previous EN/UN controller.
        button.setText("UN" if bit_state else "EN")
        button.setToolTip(
            "Channel is enabled — click to un-enable"
            if bit_state
            else "Channel is not enabled — click to enable"
        )
        button.setStyleSheet(
            state_button_css(T.cyan if bit_state else T.dim, bit_state)
        )

    def _sync_power_controls(self) -> None:
        for button, state in zip(self.power_buttons, self.context.power_states):
            button.blockSignals(True)
            button.setChecked(bool(state))
            button.blockSignals(False)
            self._apply_power_button_visual(button, bool(state))

        all_on = bool(self.context.power_states) and all(self.context.power_states)
        self.power_all_btn.setText("ALL OFF" if all_on else "ALL ON")
        self.power_all_btn.setStyleSheet(
            bulk_button_css(T.red if all_on else T.green)
        )

    def _sync_enable_controls(self) -> None:
        for button, state in zip(self.enable_buttons, self.context.enable_states):
            button.blockSignals(True)
            button.setChecked(bool(state))
            button.blockSignals(False)
            self._apply_enable_button_visual(button, bool(state))

        all_enabled = bool(self.context.enable_states) and all(self.context.enable_states)
        self.enable_all_btn.setText("ALL DISABLE" if all_enabled else "ALL ENABLE")
        self.enable_all_btn.setStyleSheet(
            bulk_button_css(T.orange if all_enabled else T.cyan)
        )

    def _sync_plot_controls(self) -> None:
        for button, state in zip(self.plot_buttons, self.context.plot_flags):
            button.blockSignals(True)
            button.setChecked(bool(state))
            button.blockSignals(False)
        all_plotted = bool(self.context.plot_flags) and all(self.context.plot_flags)
        self.plot_all_btn.blockSignals(True)
        self.plot_all_btn.setChecked(all_plotted)
        self.plot_all_btn.setText("CLEAR ALL" if all_plotted else "PLOT ALL")
        self.plot_all_btn.blockSignals(False)

    def _sync_all_channel_controls(self) -> None:
        self._sync_power_controls()
        self._sync_enable_controls()
        self._sync_plot_controls()

    def _toggle_power_all(self) -> None:
        turn_on = not all(self.context.power_states)
        self.context.set_all_power_states(turn_on, send=True)

    def _toggle_enable_all(self) -> None:
        enable_all = not all(self.context.enable_states)
        self.context.set_all_enable_states(enable_all, send=True)

    def _toggle_plot_all(self, checked: bool) -> None:
        self.context.set_all_plot_flags(bool(checked), send=True)

    def _toggle_lock(self, checked: bool) -> None:
        self.controls_locked = bool(checked)
        self.lock_btn.setText("🔒  LOCKED" if checked else "🔒  UNLOCK")
        enabled = not checked
        for button in self.power_buttons + self.enable_buttons:
            button.setEnabled(enabled)
        self.power_all_btn.setEnabled(enabled)
        self.enable_all_btn.setEnabled(enabled)

    # ----------------------------------------------------------- Live data
    def _poll_actual_data(self) -> None:
        """Update magnetic actuals and calibrated beam-current feedback.

        The full CNL packet delivered to this controller already contains both
        the magnetic channel array and the raw beam-meter voltage.  Magnetic
        values continue through ``scaler.raw_to_eng``.  Beam voltage is
        converted to nA with the same ``beam_cal`` path used by the Vacuum/Beam
        monitoring window, including the packet's beam-range index.
        """
        # Preferred magnetic-only route used by some stand-alone launchers.
        # It has no beam packet, so any previously received beam sample simply
        # ages and is rejected by the PID stale-data check.
        if self.current_values_ref is not None:
            values: list[float] = []
            for index in range(NUM_CHANNELS):
                try:
                    values.append(float(self.current_values_ref[index]))
                except (IndexError, TypeError, ValueError):
                    values.append(self.actual_values[index])
            self.actual_values[:] = values
            self.context.update_actual_values(values)
            self._set_live_state(True)
            return

        if self.data_queue is None:
            self._set_live_state(False)
            self.context.invalidate_beam_measurement("NO CONTROLLER DATA QUEUE")
            return

        now = time.time()
        last = None
        received_new_packet = False
        while True:
            try:
                last = self.data_queue.get_nowait()
                received_new_packet = True
            except Exception:
                break

        if last is not None:
            self._last_sample = last
            self.last_data_time = now
        elif self._last_sample is not None and (now - self.last_data_time) <= self.HOLD_SECONDS:
            last = self._last_sample
        else:
            self._set_live_state(False)
            self.context.invalidate_beam_measurement("CONTROLLER DATA STALE")
            return

        if not isinstance(last, dict):
            self._set_live_state(False)
            if received_new_packet:
                self.context.invalidate_beam_measurement("INVALID CONTROLLER PACKET")
            return

        # Update beam timestamp only for a genuinely new packet.  Reusing the
        # held magnetic packet must not make stale beam data appear fresh.
        if received_new_packet:
            self._update_beam_feedback(last)

        raw = list(last.get("channels", []))
        if not raw:
            self._set_live_state(False)
            return

        count = min(len(TRIM_KEYS), len(raw), NUM_CHANNELS)
        try:
            for index in range(count):
                self.actual_values[index] = float(
                    self.scaler.raw_to_eng(TRIM_KEYS[index], raw[index])
                )
        except Exception as exc:
            print("[Controller] scaling error:", exc)
            self._set_live_state(False)
            return

        self.context.update_actual_values(self.actual_values)
        self._set_live_state(True)

    def _update_beam_feedback(self, packet: dict) -> None:
        """Convert the packet beam voltage to calibrated nA for PID feedback."""
        raw_value = packet.get("beam_current")
        if isinstance(raw_value, (list, tuple)):
            raw_value = raw_value[0] if raw_value else None
        if raw_value is None:
            raw_value = packet.get("beam_v_raw", packet.get("beam"))
        if raw_value is None:
            self.context.invalidate_beam_measurement("BEAM FIELD MISSING")
            return

        try:
            explicit_index = packet.get("beam_range_idx", packet.get("range_idx"))
            if explicit_index is None:
                range_index = int(beam_cal.select_index_for_pkt(packet))
            else:
                range_index = int(explicit_index)
            ranges = list(beam_cal.cfg.ranges)
            if not ranges:
                raise RuntimeError("beam calibration has no ranges")
            range_index = max(0, min(range_index, len(ranges) - 1))
            beam_nA = float(beam_cal.volts_to_nA(float(raw_value), range_index))
            if not math.isfinite(beam_nA):
                raise ValueError("non-finite calibrated beam current")
        except Exception as exc:
            self.context.invalidate_beam_measurement(f"BEAM CALIBRATION ERROR: {exc}")
            return

        self.context.update_beam_measurement(
            beam_nA,
            status=f"LIVE — RANGE {range_index + 1}",
        )

    def _set_live_state(self, live: bool) -> None:
        color = T.green if live else T.red
        self.live_dot.set_color(color)
        self.live_label.setText("LIVE" if live else "NO DATA")
        self.live_label.setStyleSheet(f"color: {color}; font-size: 14px;")

    # ------------------------------------------------------------- Display
    def update_display(self) -> None:
        for index, label in enumerate(self.labels):
            label.setText(f"{self.context.target(index):.2f}")
            label.setStyleSheet(target_label_css(index == self.context.selected_index))
        self.manual_tab.refresh()
        self.pid_tab.refresh()

    def _update_clock(self) -> None:
        self.clock_label.setText(time.strftime("%H:%M"))

    # ------------------------------------------------------- Output adapter
    def send_update(self) -> None:
        """Preserve the existing ENG->RAW scaling and control-queue payload."""
        self.plot_config["channels"] = list(self.context.plot_flags)

        engineering_values = self.context.targets_snapshot()
        raw_values = list(engineering_values)
        count = min(len(TRIM_KEYS), len(raw_values))
        for index in range(count):
            raw_values[index] = self.scaler.eng_to_raw(
                TRIM_KEYS[index], engineering_values[index]
            )

        if self.control_queue is None:
            return
        try:
            self.control_queue.put(
                (
                    raw_values[: len(TRIM_KEYS)],
                    list(self.context.power_states),
                    list(self.context.enable_states),
                )
            )
        except Exception as exc:
            print("⚠️ control_queue.put failed:", exc)

    def _apply_pid_delta_output(self, channel_index: int, delta_target: float, result) -> bool:
        """Apply the paper controller's signed per-sample TC target increment.

        This callback is reached only when the operator has selected
        ``ARM HARDWARE OUTPUT``.  Preview mode never calls it.  The existing
        engineering-target -> scaling -> control_queue path is preserved.
        """
        try:
            index = int(channel_index)
            delta = float(delta_target)
        except (TypeError, ValueError):
            return False

        if not math.isfinite(delta) or not 0 <= index < 12:
            return False
        if not self.context.can_write(ControlMode.PID):
            return False

        # Require the commanded trim coil to be both powered and enabled before
        # accepting an armed PID command.  This does not affect preview mode.
        if not self.context.power_states[index]:
            self.context.status_changed.emit(
                f"PID output rejected: {self.context.channel_name(index)} power is OFF"
            )
            return False
        if not self.context.enable_states[index]:
            self.context.status_changed.emit(
                f"PID output rejected: {self.context.channel_name(index)} is not enabled"
            )
            return False

        if abs(delta) <= 1e-12:
            return True

        current_target = self.context.target(index)
        requested_target = current_target + delta
        limited_target = self.context.clamp_target(index, requested_target)
        self.context.set_target(
            index,
            limited_target,
            send=True,
            source_mode=ControlMode.PID,
        )
        if not math.isclose(
            requested_target, limited_target, rel_tol=0.0, abs_tol=1e-9
        ):
            self.context.status_changed.emit(
                f"PID target clamped at {limited_target:.2f} A for "
                f"{self.context.channel_name(index)}"
            )
        return True

    def set_pid_output_callback(self, callback: PIDOutputCallback | None) -> None:
        """Connect the PID output to an integration/test adapter.

        The PID tab remains preview-only until this method is called and the
        operator checks ARM HARDWARE OUTPUT in the PID tab.
        """
        self.pid_tab.output_callback = callback

    def submit_pid_ga_fitness(self, fitness: float) -> None:
        """Hook for a future automated PID candidate test runner."""
        self.pid_tab.submit_candidate_fitness(float(fitness))


# ---------------------------------------------------------------- Demo only
if __name__ == "__main__":
    # This launcher exercises the modular GUI while keeping the production
    # constructor unchanged.  It still requires the project's scaling.py.
    import math as _math

    demo_targets = [341.0, 348.0, 0.0, 75.0, 63.0, 150.0, 209.0,
                    147.0, 296.0, 543.0, 0.0, 0.0, 2600.0, 7.0]
    demo_actuals = list(demo_targets)
    demo_control_queue = _queue.Queue()
    demo_plot_config = {"channels": [False] * NUM_CHANNELS}

    app = QApplication(sys.argv)
    window = MagneticFieldControllerWindow(
        demo_control_queue,
        demo_targets,
        demo_plot_config,
        current_values_ref=demo_actuals,
    )

    phase = 0.0

    def update_demo_actuals():
        nonlocal_phase = update_demo_actuals.phase
        for i, target in enumerate(demo_targets):
            demo_actuals[i] += 0.08 * (target - demo_actuals[i])
            demo_actuals[i] += 0.015 * _math.sin(nonlocal_phase + i * 0.6)
        update_demo_actuals.phase += 0.08

    update_demo_actuals.phase = phase
    demo_timer = QTimer()
    demo_timer.timeout.connect(update_demo_actuals)
    demo_timer.start(50)

    window.show()
    sys.exit(app.exec())
