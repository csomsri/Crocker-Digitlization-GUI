"""Fail-closed loading of reviewed PID hardware allocation profiles."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class HardwareAllocation:
    allocation: list[float]
    command_bias: list[float]
    minimum_command: list[float]
    maximum_command: list[float]
    maximum_slew_per_second: list[float]
    max_absolute_error: float
    max_overshoot: float
    max_control_output: float
    max_saturation_seconds: float


class HardwareProfile:
    def __init__(self, path: str | Path, channel_names: list[str] | tuple[str, ...]) -> None:
        self.path = Path(path)
        self.channel_names = tuple(channel_names)
        self.name = ""
        self.allocations: dict[str, HardwareAllocation] = {}
        self._load()

    def _load(self) -> None:
        source = json.loads(self.path.read_text(encoding="utf-8"))
        if source.get("approval_status") != "approved":
            raise ValueError("profile approval_status must be 'approved'")
        required_provenance = (
            "measurement_date", "machine_configuration", "units", "operator",
            "reviewer", "source_dataset", "uncertainty", "valid_until",
        )
        provenance = source.get("provenance", {})
        missing = [key for key in required_provenance if not str(provenance.get(key, "")).strip()]
        if missing:
            raise ValueError(f"profile provenance is missing: {', '.join(missing)}")
        if date.fromisoformat(str(provenance["valid_until"])) < date.today():
            raise ValueError("profile has expired and must be revalidated")
        self.name = str(source.get("profile_name", self.path.stem))
        entries = source.get("measurement_channels", {})
        for measurement_name, entry in entries.items():
            if measurement_name not in self.channel_names or not isinstance(entry, dict):
                raise ValueError(f"unknown measurement channel: {measurement_name}")
            vectors = {}
            for key in ("allocation", "command_bias", "minimum_command", "maximum_command", "maximum_slew_per_second"):
                mapping = entry.get(key, {})
                if not isinstance(mapping, dict):
                    raise ValueError(f"{measurement_name}.{key} must be an object keyed by channel")
                unknown = set(mapping) - set(self.channel_names)
                if unknown:
                    raise ValueError(f"{measurement_name}.{key} has unknown channels: {sorted(unknown)}")
                default = 0.0 if key in {"allocation", "command_bias"} else None
                values = []
                for channel in self.channel_names:
                    raw = mapping.get(channel, default)
                    if raw is None:
                        raise ValueError(f"{measurement_name}.{key} is missing {channel}")
                    values.append(float(raw))
                if not all(math.isfinite(value) for value in values):
                    raise ValueError(f"{measurement_name}.{key} contains a non-finite value")
                vectors[key] = values
            allocated = [i for i, value in enumerate(vectors["allocation"]) if value != 0.0]
            if not allocated:
                raise ValueError(f"{measurement_name} has no allocated actuator")
            for index in allocated:
                channel = self.channel_names[index]
                if channel not in entry["command_bias"]:
                    raise ValueError(f"{measurement_name}.command_bias is missing allocated channel {channel}")
                if vectors["minimum_command"][index] >= vectors["maximum_command"][index]:
                    raise ValueError(f"{measurement_name} has unordered command limits")
                if vectors["maximum_slew_per_second"][index] <= 0.0:
                    raise ValueError(f"{measurement_name} has a non-positive slew limit")
            abort = entry.get("abort_limits", {})
            abort_values = [float(abort.get(key, 0.0)) for key in (
                "max_absolute_error", "max_overshoot", "max_control_output", "max_saturation_seconds",
            )]
            if not all(math.isfinite(value) and value > 0.0 for value in abort_values):
                raise ValueError(f"{measurement_name} requires four positive finite abort limits")
            self.allocations[measurement_name] = HardwareAllocation(
                **vectors,
                max_absolute_error=abort_values[0], max_overshoot=abort_values[1],
                max_control_output=abort_values[2], max_saturation_seconds=abort_values[3],
            )
        if not self.allocations:
            raise ValueError("profile contains no measurement-channel allocations")

    def allocation_for(self, measurement_name: str) -> HardwareAllocation:
        try:
            return self.allocations[measurement_name]
        except KeyError as exc:
            raise ValueError(f"profile has no allocation for {measurement_name}") from exc
