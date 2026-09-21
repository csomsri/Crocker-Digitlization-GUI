# -*- coding: utf-8 -*-
"""Shared state and signals for the modular cyclotron controller tabs."""

from __future__ import annotations

import math
import time
from enum import Enum
from typing import Callable, Iterable, MutableSequence, Sequence

from PyQt6.QtCore import QObject, pyqtSignal


class ControlMode(str, Enum):
    MANUAL = "MANUAL"
    PID = "PID"
    GA_TUNING = "GA TUNING"
    SEQUENCE = "SEQUENCE"
    MULTI_SEQUENCE = "MULTI-TC SEQUENCE"


class ControllerContext(QObject):
    """Single shared model used by Manual, PID/GA, and sequence tabs.

    Tabs communicate through this object instead of importing or editing one
    another.  The existing ``target_values`` object is retained by reference so
    the rest of the CNL control-system code continues to see live target edits.
    """

    selected_channel_changed = pyqtSignal(int)
    target_changed = pyqtSignal(int, float)
    targets_changed = pyqtSignal(object)
    actual_values_changed = pyqtSignal(object)
    beam_measurement_changed = pyqtSignal(object)
    power_states_changed = pyqtSignal(object)
    enable_states_changed = pyqtSignal(object)
    plot_flags_changed = pyqtSignal(object)
    mode_changed = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    command_sent = pyqtSignal()

    def __init__(
        self,
        channel_names: Sequence[str],
        target_values: MutableSequence[float],
        plot_config: dict | None = None,
        send_callback: Callable[[], None] | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.channel_names = list(channel_names)
        self.target_values = target_values
        self.plot_config = plot_config if plot_config is not None else {}
        self._send_callback = send_callback

        self.selected_index = 0
        self.active_mode = ControlMode.MANUAL

        count = len(self.channel_names)
        self.actual_values = [0.0] * count

        # Beam feedback is physically separate from the selected magnetic
        # actuator.  The value is stored in calibrated nA with a monotonic
        # receive timestamp so the PID page can reject stale data.
        self._beam_current_nA = float("nan")
        self._beam_timestamp = 0.0
        self._beam_valid = False
        self._beam_status = "NO DATA"

        # Preserve the old controller's initial bit behavior: both button lists
        # start False unless a caller explicitly supplies remembered states.
        self.power_states = self._coerce_bool_list(
            self.plot_config.get("power_states"), count, default=False
        )
        self.enable_states = self._coerce_bool_list(
            self.plot_config.get("enable_states"), count, default=False
        )
        self.plot_flags = self._coerce_bool_list(
            self.plot_config.get("channels"), count, default=False
        )

        self.target_limits: list[tuple[float, float]] = [(0.0, 9999.99)] * count

    @staticmethod
    def _coerce_bool_list(values, count: int, default: bool) -> list[bool]:
        if isinstance(values, (list, tuple)):
            out = [bool(v) for v in values[:count]]
            if len(out) < count:
                out.extend([default] * (count - len(out)))
            return out
        return [default] * count

    def set_send_callback(self, callback: Callable[[], None] | None) -> None:
        self._send_callback = callback

    def channel_name(self, index: int | None = None) -> str:
        idx = self.selected_index if index is None else int(index)
        if 0 <= idx < len(self.channel_names):
            return self.channel_names[idx]
        return "—"

    def target(self, index: int | None = None) -> float:
        idx = self.selected_index if index is None else int(index)
        try:
            return float(self.target_values[idx])
        except (IndexError, TypeError, ValueError):
            return 0.0

    def actual(self, index: int | None = None) -> float:
        idx = self.selected_index if index is None else int(index)
        try:
            value = float(self.actual_values[idx])
            return value if math.isfinite(value) else float("nan")
        except (IndexError, TypeError, ValueError):
            return float("nan")

    def set_target_limits(self, index: int, minimum: float, maximum: float) -> None:
        if not 0 <= index < len(self.target_limits):
            raise IndexError(index)
        lo, hi = sorted((float(minimum), float(maximum)))
        self.target_limits[index] = (lo, hi)

    def clamp_target(self, index: int, value: float) -> float:
        lo, hi = self.target_limits[index]
        return max(lo, min(hi, float(value)))

    def set_selected_index(self, index: int) -> None:
        index = int(index)
        if not 0 <= index < len(self.channel_names):
            raise IndexError(index)
        if index == self.selected_index:
            return
        self.selected_index = index
        self.selected_channel_changed.emit(index)

    def set_target(
        self,
        index: int,
        value: float,
        *,
        send: bool = True,
        source_mode: ControlMode | str | None = None,
    ) -> float:
        index = int(index)
        if not 0 <= index < len(self.channel_names):
            raise IndexError(index)
        value = round(self.clamp_target(index, float(value)), 2)
        self.target_values[index] = value
        self.target_changed.emit(index, value)
        self.targets_changed.emit(self.targets_snapshot())
        if source_mode is not None:
            self.set_mode(source_mode)
        if send:
            self.request_send()
        return value

    def adjust_target(
        self,
        index: int,
        delta: float,
        *,
        send: bool = True,
        source_mode: ControlMode | str = ControlMode.MANUAL,
    ) -> float:
        return self.set_target(
            index,
            self.target(index) + float(delta),
            send=send,
            source_mode=source_mode,
        )

    def set_targets(
        self,
        updates: dict[int, float] | Sequence[float],
        *,
        send: bool = True,
        source_mode: ControlMode | str | None = None,
    ) -> None:
        if isinstance(updates, dict):
            items = updates.items()
        else:
            items = enumerate(updates)
        changed = False
        for index, value in items:
            index = int(index)
            if not 0 <= index < len(self.channel_names):
                continue
            try:
                numeric = round(self.clamp_target(index, float(value)), 2)
            except (TypeError, ValueError):
                continue
            self.target_values[index] = numeric
            self.target_changed.emit(index, numeric)
            changed = True
        if changed:
            self.targets_changed.emit(self.targets_snapshot())
            if source_mode is not None:
                self.set_mode(source_mode)
            if send:
                self.request_send()

    def targets_snapshot(self) -> list[float]:
        out: list[float] = []
        for i in range(len(self.channel_names)):
            out.append(self.target(i))
        return out

    def update_actual_values(self, values: Iterable[float]) -> None:
        incoming = list(values)
        for i in range(min(len(incoming), len(self.actual_values))):
            try:
                value = float(incoming[i])
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                self.actual_values[i] = value
        self.actual_values_changed.emit(list(self.actual_values))

    def update_beam_measurement(
        self,
        value_nA: float,
        *,
        timestamp: float | None = None,
        valid: bool = True,
        status: str = "LIVE",
    ) -> None:
        """Store one calibrated beam-current sample in nA.

        ``timestamp`` uses ``time.monotonic()`` by default.  The controller
        compares the stored age against its stale-data limit before each PID
        evaluation.
        """
        try:
            value = float(value_nA)
        except (TypeError, ValueError):
            self.invalidate_beam_measurement("INVALID BEAM VALUE")
            return

        is_valid = bool(valid) and math.isfinite(value)
        self._beam_current_nA = value if is_valid else float("nan")
        self._beam_timestamp = (
            time.monotonic() if timestamp is None else float(timestamp)
        )
        self._beam_valid = is_valid
        self._beam_status = str(status) if status else ("LIVE" if is_valid else "INVALID")
        self.beam_measurement_changed.emit(self.beam_snapshot())

    def invalidate_beam_measurement(self, status: str = "NO DATA") -> None:
        self._beam_valid = False
        self._beam_status = str(status)
        self.beam_measurement_changed.emit(self.beam_snapshot())

    def beam_age_s(self) -> float:
        if self._beam_timestamp <= 0.0:
            return float("inf")
        return max(0.0, time.monotonic() - self._beam_timestamp)

    def beam_current(self, *, max_age_s: float | None = None) -> float:
        if not self._beam_valid or not math.isfinite(self._beam_current_nA):
            return float("nan")
        if max_age_s is not None and self.beam_age_s() > max(0.0, float(max_age_s)):
            return float("nan")
        return float(self._beam_current_nA)

    def beam_snapshot(self, *, max_age_s: float | None = None) -> dict:
        fresh = self._beam_valid
        if max_age_s is not None:
            fresh = fresh and self.beam_age_s() <= max(0.0, float(max_age_s))
        value = self._beam_current_nA if fresh else float("nan")
        status = self._beam_status if fresh else (
            "STALE" if self._beam_valid else self._beam_status
        )
        return {
            "value_nA": float(value),
            "timestamp": float(self._beam_timestamp),
            "age_s": float(self.beam_age_s()),
            "valid": bool(fresh and math.isfinite(value)),
            "status": str(status),
        }

    def set_power_state(self, index: int, state: bool, *, send: bool = True) -> None:
        self.power_states[index] = bool(state)
        self.plot_config["power_states"] = list(self.power_states)
        self.power_states_changed.emit(list(self.power_states))
        if send:
            self.request_send()

    def set_all_power_states(self, state: bool, *, send: bool = True) -> None:
        self.power_states[:] = [bool(state)] * len(self.power_states)
        self.plot_config["power_states"] = list(self.power_states)
        self.power_states_changed.emit(list(self.power_states))
        if send:
            self.request_send()

    def set_enable_state(self, index: int, state: bool, *, send: bool = True) -> None:
        self.enable_states[index] = bool(state)
        self.plot_config["enable_states"] = list(self.enable_states)
        self.enable_states_changed.emit(list(self.enable_states))
        if send:
            self.request_send()

    def set_all_enable_states(self, state: bool, *, send: bool = True) -> None:
        self.enable_states[:] = [bool(state)] * len(self.enable_states)
        self.plot_config["enable_states"] = list(self.enable_states)
        self.enable_states_changed.emit(list(self.enable_states))
        if send:
            self.request_send()

    def set_plot_flag(self, index: int, state: bool, *, send: bool = True) -> None:
        self.plot_flags[index] = bool(state)
        self.plot_config["channels"] = list(self.plot_flags)
        self.plot_flags_changed.emit(list(self.plot_flags))
        if send:
            self.request_send()

    def set_all_plot_flags(self, state: bool, *, send: bool = True) -> None:
        self.plot_flags[:] = [bool(state)] * len(self.plot_flags)
        self.plot_config["channels"] = list(self.plot_flags)
        self.plot_flags_changed.emit(list(self.plot_flags))
        if send:
            self.request_send()

    def set_mode(self, mode: ControlMode | str) -> None:
        try:
            normalized = mode if isinstance(mode, ControlMode) else ControlMode(str(mode))
        except ValueError:
            normalized = ControlMode.MANUAL
        if normalized == self.active_mode:
            return
        self.active_mode = normalized
        self.mode_changed.emit(normalized.value)

    def can_write(self, mode: ControlMode | str) -> bool:
        try:
            normalized = mode if isinstance(mode, ControlMode) else ControlMode(str(mode))
        except ValueError:
            return False
        return self.active_mode == normalized

    def request_send(self) -> None:
        if self._send_callback is None:
            self.status_changed.emit("No control-output callback is connected")
            return
        try:
            self._send_callback()
            self.command_sent.emit()
        except Exception as exc:  # pragma: no cover - GUI-side safety boundary
            self.status_changed.emit(f"Control send failed: {exc}")


__all__ = ["ControlMode", "ControllerContext"]
