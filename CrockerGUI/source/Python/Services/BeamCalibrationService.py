from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Any


DEFAULT_RANGE_LABELS = (
    "100 pA",
    "300 pA",
    "1 nA",
    "3 nA",
    "10 nA",
    "30 nA",
    "100 nA",
    "300 nA",
    "1 uA",
    "100 uA",
)


@dataclass(frozen=True)
class BeamRange:
    label: str
    full_scale_ua: float
    points: tuple[tuple[float, float], ...]
    mode: str = "curve"


@dataclass(frozen=True)
class BeamState:
    timestamp: float
    raw_value: float
    current_ua: float
    display_ua: float
    range_index: int
    range_label: str
    full_scale_ua: float
    select_mode: str
    quality: str
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BeamCalibrationService:
    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)
        self._lock = Lock()
        self._ranges = self._default_ranges()
        self._select_mode = "manual"
        self._manual_index = 0
        self._digital_source = "bitmask_low4"
        self._beam_channel = 13
        self._smooth_tau_s = 0.0
        self._deadband_display = 0.0
        self._gauge_uses_range_fs = True
        self._gauge_fullscale_override_ua = 100.0
        self._smoothed_ua: float | None = None
        self._last_update = 0.0
        self._state = BeamState(
            timestamp=0.0,
            raw_value=0.0,
            current_ua=0.0,
            display_ua=0.0,
            range_index=0,
            range_label=self._ranges[0].label,
            full_scale_ua=self._ranges[0].full_scale_ua,
            select_mode=self._select_mode,
            quality="idle",
        )
        self.reload()

    def reload(self) -> None:
        if not self.config_path.exists():
            return
        with self.config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("beam calibration config must contain a JSON object")

        ranges = self._ranges_from_config(data)
        with self._lock:
            if ranges:
                self._ranges = ranges
            self._select_mode = str(data.get("select_mode", self._select_mode))
            self._manual_index = int(data.get("manual_index", self._manual_index))
            self._digital_source = str(data.get("digital_source", self._digital_source))
            self._beam_channel = self._channel_index(data.get("beam_channel", self._beam_channel))
            self._smooth_tau_s = max(0.0, float(data.get("smooth_tau_s", self._smooth_tau_s)))
            self._deadband_display = max(0.0, float(data.get("deadband_display", self._deadband_display)))
            self._gauge_uses_range_fs = bool(data.get("gauge_uses_range_fs", self._gauge_uses_range_fs))
            self._gauge_fullscale_override_ua = float(
                data.get("gauge_fullscale_override_uA", data.get("gauge_fullscale_override_ua", self._gauge_fullscale_override_ua))
            )

    def update(self, snapshot: dict[str, Any] | None) -> BeamState:
        with self._lock:
            if not snapshot:
                self._state = self._state_with_quality("idle", "No transport snapshot")
                return self._state

            channels = snapshot.get("channels", [])
            if not isinstance(channels, list) or self._beam_channel >= len(channels):
                self._state = self._state_with_quality("degraded", "Beam channel is not present")
                return self._state

            channel = channels[self._beam_channel]
            if not isinstance(channel, dict):
                self._state = self._state_with_quality("degraded", "Beam channel is malformed")
                return self._state

            timestamp = float(snapshot.get("timestamp") or time.time())
            raw_value = float(channel.get("raw", channel.get("actual", 0.0)))
            range_index = self._active_range_index(snapshot)
            beam_range = self._ranges[range_index]
            current_ua = self._convert(raw_value, beam_range)
            display_ua = self._smooth(current_ua, timestamp)
            full_scale_ua = beam_range.full_scale_ua if self._gauge_uses_range_fs else self._gauge_fullscale_override_ua
            self._state = BeamState(
                timestamp=timestamp,
                raw_value=raw_value,
                current_ua=current_ua,
                display_ua=display_ua,
                range_index=range_index,
                range_label=beam_range.label,
                full_scale_ua=full_scale_ua,
                select_mode=self._select_mode,
                quality="ok",
            )
            return self._state

    def set_manual_range(self, index: int) -> BeamState:
        with self._lock:
            self._select_mode = "manual"
            self._manual_index = self._clamp_range_index(index)
            self._state = BeamState(
                **{**self._state.to_dict(), "range_index": self._manual_index, "range_label": self._ranges[self._manual_index].label, "select_mode": "manual"}
            )
            return self._state

    def state(self) -> BeamState:
        with self._lock:
            return self._state

    def state_dict(self) -> dict[str, Any]:
        return self.state().to_dict()

    def ranges_dict(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"index": index, "label": beam_range.label, "full_scale_ua": beam_range.full_scale_ua}
                for index, beam_range in enumerate(self._ranges)
            ]

    def _state_with_quality(self, quality: str, message: str) -> BeamState:
        return BeamState(**{**self._state.to_dict(), "quality": quality, "message": message})

    def _active_range_index(self, snapshot: dict[str, Any]) -> int:
        if self._select_mode == "digital":
            bitmask = int(snapshot.get("bitmask", self._bitmask_from_channels(snapshot.get("channels", []))))
            if self._digital_source == "bitmask_low4":
                return self._clamp_range_index(bitmask & 0xF)
        return self._clamp_range_index(self._manual_index)

    def _convert(self, raw_value: float, beam_range: BeamRange) -> float:
        if beam_range.mode == "linear" and len(beam_range.points) >= 2:
            low, high = beam_range.points[0], beam_range.points[-1]
            span = high[0] - low[0]
            if span:
                return low[1] + ((raw_value - low[0]) / span) * (high[1] - low[1])
        return self._interpolate(raw_value, beam_range.points)

    def _smooth(self, current_ua: float, timestamp: float) -> float:
        previous = self._smoothed_ua
        if previous is None:
            self._smoothed_ua = current_ua
            self._last_update = timestamp
            return current_ua
        if abs(current_ua - previous) < self._deadband_display:
            return previous
        dt = max(0.0, timestamp - self._last_update)
        self._last_update = timestamp
        if self._smooth_tau_s <= 0.0 or dt <= 0.0:
            self._smoothed_ua = current_ua
            return current_ua
        alpha = 1.0 - math.exp(-dt / self._smooth_tau_s)
        self._smoothed_ua = previous + alpha * (current_ua - previous)
        return self._smoothed_ua

    def _ranges_from_config(self, data: dict[str, Any]) -> list[BeamRange]:
        ranges = data.get("ranges", [])
        if isinstance(ranges, dict):
            ranges = [{"label": label, **entry} for label, entry in ranges.items() if isinstance(entry, dict)]
        if not isinstance(ranges, list):
            return []
        parsed: list[BeamRange] = []
        for index, entry in enumerate(ranges):
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("label", DEFAULT_RANGE_LABELS[min(index, len(DEFAULT_RANGE_LABELS) - 1)]))
            full_scale_ua = float(entry.get("full_scale_uA", entry.get("full_scale_ua", self._label_to_ua(label))))
            points = self._points_from_entry(entry)
            if len(points) >= 2:
                parsed.append(BeamRange(label=label, full_scale_ua=full_scale_ua, points=points, mode=str(entry.get("mode", "curve"))))
        return parsed

    def _points_from_entry(self, entry: dict[str, Any]) -> tuple[tuple[float, float], ...]:
        points = entry.get("points", entry.get("curve", []))
        parsed: list[tuple[float, float]] = []
        if isinstance(points, list):
            for point in points:
                if isinstance(point, dict):
                    raw = point.get("raw", point.get("x"))
                    current = point.get("uA", point.get("ua", point.get("current_ua", point.get("eng", point.get("y")))))
                    if raw is not None and current is not None:
                        parsed.append((float(raw), float(current)))
                elif isinstance(point, list | tuple) and len(point) >= 2:
                    parsed.append((float(point[0]), float(point[1])))
        parsed = sorted({raw: current for raw, current in parsed if math.isfinite(raw) and math.isfinite(current)}.items())
        return tuple(parsed)

    def _default_ranges(self) -> list[BeamRange]:
        return [
            BeamRange(label=label, full_scale_ua=self._label_to_ua(label), points=((0.0, 0.0), (1.0, self._label_to_ua(label))))
            for label in DEFAULT_RANGE_LABELS
        ]

    def _interpolate(self, raw_value: float, points: tuple[tuple[float, float], ...]) -> float:
        if not points:
            return raw_value
        if raw_value <= points[0][0]:
            return points[0][1]
        if raw_value >= points[-1][0]:
            return points[-1][1]
        for low, high in zip(points, points[1:]):
            if low[0] <= raw_value <= high[0]:
                span = high[0] - low[0]
                if not span:
                    return low[1]
                return low[1] + ((raw_value - low[0]) / span) * (high[1] - low[1])
        return points[-1][1]

    def _clamp_range_index(self, index: int) -> int:
        return max(0, min(len(self._ranges) - 1, int(index)))

    def _channel_index(self, value: Any) -> int:
        if isinstance(value, int):
            return max(0, value)
        text = str(value).lower()
        if text.startswith("ch") and text[2:].isdigit():
            return max(0, int(text[2:]) - 1)
        if text in {"beam", "beam_current", "centering_beam"}:
            return 13
        if text == "main_magnet":
            return 12
        return self._beam_channel

    def _label_to_ua(self, label: str) -> float:
        text = label.strip().lower().replace("µ", "u")
        parts = text.split()
        if len(parts) < 2:
            return 1.0
        value = float(parts[0])
        unit = parts[1]
        if unit == "pa":
            return value * 1.0e-6
        if unit == "na":
            return value * 1.0e-3
        if unit == "ua":
            return value
        return value

    def _bitmask_from_channels(self, channels: Any) -> int:
        if not isinstance(channels, list):
            return 0
        bitmask = 0
        for index, channel in enumerate(channels):
            if not isinstance(channel, dict):
                continue
            if bool(channel.get("on", False)):
                bitmask |= 1 << index
            if bool(channel.get("enabled", False)):
                bitmask |= 1 << (len(channels) + index)
        return bitmask
