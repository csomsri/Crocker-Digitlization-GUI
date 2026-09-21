"""Fail-closed loading of reviewed PID hardware allocation profiles."""

from __future__ import annotations

import json
import math
import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path


def _limits_digest(source):
    return hashlib.sha256(json.dumps(source.get('measurement_channels', {}), sort_keys=True,
                                    allow_nan=False).encode('utf-8')).hexdigest()


def approve_operator_limits(source, *, approved_by, statement):
    """Record explicit operator approval of limits, not physical calibration."""
    source['approval_status'] = 'approved'
    source['approval_basis'] = 'operator_limits'
    source['operator_approval'] = dict(approved_by=approved_by, statement=statement,
        approved_at=datetime.now(timezone.utc).isoformat(), limits_sha256=_limits_digest(source))
    return source


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
    external_ramp: bool = False


class HardwareProfile:
    def __init__(self, path: str | Path, channel_names: list[str] | tuple[str, ...]) -> None:
        self.path = Path(path)
        self.channel_names = tuple(channel_names)
        self.name = ""
        self.allocations: dict[str, HardwareAllocation] = {}
        self._load()

    def _load(self) -> None:
        source = json.loads(self.path.read_text(encoding="utf-8"))
        self._validate(source)

    @classmethod
    def from_data(cls, source: dict, channel_names, *, require_approved=True):
        profile = cls.__new__(cls)
        profile.channel_names = tuple(channel_names)
        profile.name = ""
        profile.allocations = {}
        profile._validate(source, require_approved=require_approved)
        return profile

    def _validate(self, source: dict, *, require_approved=True) -> None:
        if require_approved and source.get("approval_status") != "approved":
            raise ValueError("Hardware profile is draft or unapproved. Open Edit Hardware Profile, verify the coil limits, and complete Calibration & review with reviewer approval before hardware PID/BO.")
        operator_limits = source.get('approval_basis') == 'operator_limits'
        if require_approved and operator_limits:
            record = source.get('operator_approval', {})
            if not all(str(record.get(k, '')).strip() for k in ('approved_by', 'statement', 'approved_at')):
                raise ValueError('Operator approval record is incomplete')
            datetime.fromisoformat(record['approved_at'])
            if record.get('limits_sha256') != _limits_digest(source):
                raise ValueError('Operating limits changed since approval. Review and approve the updated limits.')
        required_provenance = (
            "measurement_date", "machine_configuration", "units", "operator",
            "reviewer", "source_dataset", "uncertainty", "valid_until",
        )
        provenance = source.get("provenance", {})
        missing = [key for key in required_provenance if not str(provenance.get(key, "")).strip()
                   or str(provenance.get(key, "")).strip().lower() in
                   {"unknown", "pending", "yyyy-mm-dd", "operator name", "independent reviewer name",
                    "immutable calibration record or dataset id", "document coefficient uncertainty"}]
        if require_approved and not operator_limits and missing:
            raise ValueError(f"profile provenance is missing: {', '.join(missing)}")
        if require_approved and not operator_limits:
            measured = date.fromisoformat(str(provenance["measurement_date"]))
            valid_until = date.fromisoformat(str(provenance["valid_until"]))
            if measured > date.today():
                raise ValueError("measurement date cannot be in the future")
            if valid_until < date.today() or valid_until < measured:
                raise ValueError("profile has expired and must be revalidated")
        self.name = str(source.get("profile_name", "Hardware profile"))
        entries = source.get("measurement_channels", {})
        for measurement_name, entry in entries.items():
            if measurement_name not in self.channel_names or not isinstance(entry, dict):
                raise ValueError(f"unknown measurement channel: {measurement_name}")
            external_ramp = entry.get('ramp_control') == 'labview'
            if operator_limits:
                if (measurement_name not in self.channel_names[:12] or not external_ramp
                        or entry.get('allocation') != {measurement_name: 1.0}):
                    raise ValueError('Operator limits approval supports single trim-coil identity allocation with LabVIEW ramping only')
            vectors = {}
            for key in ("allocation", "command_bias", "minimum_command", "maximum_command", "maximum_slew_per_second"):
                mapping = {} if external_ramp and key == 'maximum_slew_per_second' else entry.get(key, {})
                if not isinstance(mapping, dict):
                    raise ValueError(f"{measurement_name}.{key} must be an object keyed by channel")
                unknown = set(mapping) - set(self.channel_names)
                if unknown:
                    raise ValueError(f"{measurement_name}.{key} has unknown channels: {sorted(unknown)}")
                default = 0.0 if key in {"allocation", "command_bias"} or (external_ramp and key == 'maximum_slew_per_second') else None
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
                if vectors["minimum_command"][index] >= vectors["maximum_command"][index]:
                    raise ValueError(f"{measurement_name} has unordered command limits")
                if not external_ramp and vectors["maximum_slew_per_second"][index] <= 0.0:
                    raise ValueError(f"{measurement_name} has a non-positive slew limit")
            abort = entry.get("abort_limits", {})
            abort_values = [float(abort.get(key, 0.0)) for key in (
                "max_absolute_error", "max_overshoot", "max_control_output", "max_saturation_seconds",
            )]
            if not all(math.isfinite(value) and value > 0.0 for value in abort_values):
                raise ValueError(f"{measurement_name} requires four positive finite abort limits")
            self.allocations[measurement_name] = HardwareAllocation(
                **vectors,
                max_absolute_error=abort_values[0],
                max_overshoot=abort_values[1],
                max_control_output=abort_values[2],
                max_saturation_seconds=abort_values[3],
                external_ramp=external_ramp,
            )
        if not self.allocations:
            raise ValueError("profile contains no measurement-channel allocations")

    def allocation_for(self, measurement_name: str) -> HardwareAllocation:
        try:
            return self.allocations[measurement_name]
        except KeyError as exc:
            raise ValueError(f"profile has no allocation for {measurement_name}") from exc


def apply_hardware_profile(config: dict, path: str | Path, channel_names) -> dict:
    """Apply reviewed hardware limits without widening trial/UI limits."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Hardware beam PID requires a reviewed profile at {path}")
    index = config["measurement_channel"]
    if not 0 <= index < min(12, len(channel_names)):
        raise ValueError("Hardware beam PID requires a TC1-TC12 actuator")
    source = json.loads(path.read_text(encoding='utf-8'))
    if channel_names[index] not in source.get('measurement_channels', {}):
        raise ValueError(f"No hardware profile for {channel_names[index]}. Open Edit Hardware Profile and configure/review this coil's limits. Existing profiles: {', '.join(source.get('measurement_channels', {})) or 'none'}.")
    profile = HardwareProfile.from_data(source, channel_names)
    limits = profile.allocation_for(channel_names[index])
    expected = [float(i == index) for i in range(len(channel_names))]
    if limits.allocation != expected:
        raise ValueError("Hardware beam PID requires profile allocation 1.0 to the selected TC only")
    result = dict(config, allocation=list(limits.allocation),
                  command_bias=list(limits.command_bias), allocation_calibrated=True)
    for key, combine in (("minimum_command", max), ("maximum_command", min),
                         ("maximum_slew_per_second", min)):
        result[key] = [combine(a, b) for a, b in zip(config[key], getattr(limits, key))]
    if result["minimum_command"][index] >= result["maximum_command"][index]:
        raise ValueError("Hardware profile and trial current limits do not overlap")
    if limits.external_ramp:
        result['maximum_slew_per_second'] = [0.0] * len(channel_names)
    elif result["maximum_slew_per_second"][index] <= 0:
        raise ValueError("Hardware trial requires a positive slew limit")
    for key in ("max_absolute_error", "max_overshoot", "max_control_output", "max_saturation_seconds"):
        result[key] = min(config.get(key, float("inf")), getattr(limits, key))
    return result
