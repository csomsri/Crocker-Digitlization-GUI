"""Existing PID workspace backed by the standalone Python NLAPID engine."""
from __future__ import annotations

import math
import time
from pathlib import Path

from PySide6.QtWidgets import QLabel

from python.app.Automation.PidControlPage import PidControlPage
from source.Python.Control.PythonNLATrial import PythonNLATrial
from python.app.widgets.ScreenSafeComboBox import ScreenSafeComboBox as QComboBox
from source.Python.Control.NLAPID import (
    NLAPID, PIDGains, PIDLimits, AdaptiveDirectionSettings,
)


class PythonPIDPage(PidControlPage):
    """Reuse the PID page controls/transport; replace only the control engine."""

    def __init__(self, go_back, backend_mode, **kwargs):
        self.pid = NLAPID()
        self._last_sample_time = None
        self._last_fresh_time = time.perf_counter()
        super().__init__(go_back, backend_mode, **kwargs)
        self.python_trial = PythonNLATrial(self.backend)
        self.log_path = Path(__file__).resolve().parents[3] / "logs" / "python_nlapid_commands.csv"
        for label in self.findChildren(QLabel):
            if label.text() == "PID Control":
                label.setText("PythonPID")
            elif label.text() == "PID CHANNEL CONTROL":
                label.setText("PYTHON NLA PID CHANNEL CONTROL")
        self._reset_pid_state()

    def _cpp_nla_selected(self):
        return False

    def _build_control_panel(self):
        panel = super()._build_control_panel()
        self.cpp_nla_panel.hide()
        layout = panel.layout()
        self.deadband_input = self._make_spinbox(0.0, 100.0, 0.01, " A")
        self.deadband_input.setValue(0.05)
        self.direction_input = QComboBox()
        self.direction_input.addItem("Increase target first", 1)
        self.direction_input.addItem("Decrease target first", -1)
        self.direction_input.currentIndexChanged.connect(lambda _: self._reset_pid_state())
        self.direction_interval_input = self._make_spinbox(0.05, 60.0, 0.05, " s")
        self.direction_interval_input.setValue(1.0)
        self.trend_tolerance_input = self._make_spinbox(0.0, 100.0, 0.01, " A")
        self.trend_tolerance_input.setValue(0.05)
        for column, (name, widget) in enumerate((
            ("Deadband", self.deadband_input),
            ("Initial direction", self.direction_input),
            ("Direction window", self.direction_interval_input),
            ("Trend tolerance", self.trend_tolerance_input),
        )):
            layout.addWidget(QLabel(name), 7, column)
            layout.addWidget(widget, 8, column)
        self.nla_status = QLabel("NLA ready")
        self.nla_status.setWordWrap(True)
        layout.addWidget(self.nla_status, 9, 0, 1, 4)
        return panel

    def _controller_config(self) -> dict:
        return {
            "controller_kind": "python_nla",
            "nla_deadband": self.deadband_input.value(),
            "nla_trend_tolerance": self.trend_tolerance_input.value(),
            "nla_direction_check_interval": self.direction_interval_input.value(),
            "nla_initial_direction": int(self.direction_input.currentData()),
            "nla_integral_memory_s": 20.0,
            "nla_output_max": self.max_step_input.value(),
        }

    def _restore_controller_config(self, approved: dict) -> None:
        self.deadband_input.setValue(approved["nla_deadband"])
        self.trend_tolerance_input.setValue(approved["nla_trend_tolerance"])
        self.direction_interval_input.setValue(approved["nla_direction_check_interval"])
        self.direction_input.setCurrentIndex(self.direction_input.findData(approved["nla_initial_direction"]))
        self.max_step_input.setValue(approved["nla_output_max"])

    def _lock_controller_inputs(self, locked: bool) -> None:
        super()._lock_controller_inputs(locked)
        for widget in (self.deadband_input, self.trend_tolerance_input,
                       self.direction_interval_input, self.direction_input):
            widget.setEnabled(not locked)

    def _start_trial(self, config: dict) -> None:
        self.python_trial.backend = self.backend
        self.python_trial.start(config)

    def _trial_status(self) -> dict:
        return self.python_trial.status()

    def _stop_trial(self, disable: bool = True) -> None:
        self.python_trial.stop(disable)

    def _reset_pid_state(self):
        super()._reset_pid_state()
        self._last_sample_time = None
        self._last_fresh_time = time.perf_counter()
        self.pid.reset(direction=int(self.direction_input.currentData()))

    def _stop_pid(self, reason):
        self.run_metrics.finish(reason)
        # Holding means no new write, especially after a rejected command.
        self.pid_enabled = False
        self.enable_button.blockSignals(True)
        self.enable_button.setChecked(False)
        self.enable_button.setText("Enable PID")
        self.enable_button.blockSignals(False)
        self._reset_pid_state()
        self.last_safety_message = reason
        self._refresh_status()

    def _set_pid_enabled(self, enabled):
        if enabled and self.backend_available and self.backend is not None:
            try:
                target = float(self.backend.PendingCommand()[self.selected_index]["target"])
                if not math.isfinite(target):
                    raise ValueError("Nonfinite current target")
                self.command_values[self.selected_index] = target
            except Exception as exc:
                self._stop_pid(f"Cannot read current target: {exc}")
                return
        super()._set_pid_enabled(enabled)

    def _tick_pid_controller(self):
        if not self.pid_enabled:
            return
        now = time.perf_counter()
        if self.backend_available and self.backend is not None:
            try:
                snapshot = self.backend.LatestSnapshot()
                sample_time = float(snapshot["timestamp"])
                measurement = float(snapshot["channels"][self.selected_index]["actual"])
                if not math.isfinite(sample_time) or time.time() - sample_time > 2.0:
                    self._stop_pid("Stale telemetry")
                    return
            except Exception as exc:
                self._stop_pid(f"Invalid telemetry: {exc}")
                return
        elif not self.dry_run_check.isChecked():
            self._stop_pid("Live backend unavailable")
            return
        else:
            sample_time = now
            measurement = self.actual_values[self.selected_index]
        if self._last_sample_time is not None and sample_time <= self._last_sample_time:
            if sample_time < self._last_sample_time or now - self._last_fresh_time > 2.0:
                self._stop_pid("Telemetry stopped or moved backwards")
            return
        if self._last_sample_time is None:
            self._last_sample_time = sample_time
            self._last_fresh_time = now
            self.pid.reset(setpoint=self.setpoint_input.value(), measurement=measurement,
                           direction=int(self.direction_input.currentData()))
            return
        dt = sample_time - self._last_sample_time
        self._last_sample_time = sample_time
        self._last_fresh_time = now
        try:
            self.pid.set_gains(PIDGains(self.kp_input.value(), self.ki_input.value(), self.kd_input.value()))
            self.pid.set_limits(PIDLimits(output_min=0.0, output_max=self.max_step_input.value()))
            self.pid.set_settings(AdaptiveDirectionSettings(
                deadband=self.deadband_input.value(),
                trend_tolerance=self.trend_tolerance_input.value(),
                direction_check_interval=self.direction_interval_input.value(),
                initial_direction=int(self.direction_input.currentData()),
            ))
            result = self.pid.update(self.setpoint_input.value(), measurement, dt)
        except ValueError as exc:
            self._stop_pid(str(exc))
            return
        previous = self.command_values[self.selected_index]
        lower, upper = sorted((self.min_output_input.value(), self.max_output_input.value()))
        proposed = self._limited_output(previous + result.output)
        # Never send outside absolute limits when a new bound excludes the old target.
        if not lower <= proposed <= upper:
            self._stop_pid("Current target outside command limits; adjust before restarting")
            return
        self.command_values[self.selected_index] = proposed
        if not self._apply_channel_command(self.selected_index):
            self.command_values[self.selected_index] = previous
            self._stop_pid("NLA command rejected")
            return
        self.nla_status.setText(
            f"Direction {result.direction:+d} | {result.error_trend} | "
            f"P {result.proportional:.4g}  I {result.integral:.4g}  D {result.derivative:.4g} A/update | "
            f"Delta {result.output:+.4g} A"
        )

    def stop_backend(self):
        self.timer.stop()
        self.python_trial.stop(False)
        self._stop_pid("Page closed")
        super().stop_backend()
