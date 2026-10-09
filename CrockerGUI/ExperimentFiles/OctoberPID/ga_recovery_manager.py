# -*- coding: utf-8 -*-
"""Pure target-reset requests for automatic GA PID tuning.

The captured TC targets are restored through the GUI's ordinary output
callback and the existing LabVIEW ramp. Each request contains the full target
difference for one channel. There is no GA recovery step, rate, dwell, timeout,
beam threshold, or measured-current acceptance criterion here.

Software-target equality uses the same two-decimal precision as
ControllerContext.set_target. It does not acknowledge that LabVIEW has
applied a command or that the physical current or beam has settled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class GARecoveryReference:
    """Captured target profile with beam and readback diagnostics."""

    targets_a: tuple[tuple[int, float], ...]
    actuals_a: tuple[tuple[int, float], ...]
    beam_nA: float
    captured_at_s: float

    def validated(self) -> "GARecoveryReference":
        if not math.isfinite(float(self.beam_nA)):
            raise ValueError("Recovery-reference beam current must be finite")
        if not math.isfinite(float(self.captured_at_s)):
            raise ValueError("Recovery-reference timestamp must be finite")
        targets: dict[int, float] = {}
        actuals: dict[int, float] = {}
        for index, target in self.targets_a:
            idx = int(index)
            value = float(target)
            if idx < 0:
                raise ValueError("Recovery-reference channel indices must be nonnegative")
            if not math.isfinite(value):
                raise ValueError("Recovery-reference targets must be finite")
            targets[idx] = value
        for index, actual in self.actuals_a:
            idx = int(index)
            value = float(actual)
            if idx < 0:
                raise ValueError("Recovery-reference channel indices must be nonnegative")
            if not math.isfinite(value):
                raise ValueError("Recovery-reference readbacks must be finite")
            actuals[idx] = value
        if not targets:
            raise ValueError("Recovery reference must contain at least one trim coil")
        if set(targets) != set(actuals):
            raise ValueError("Recovery target and readback references must use the same channels")
        return GARecoveryReference(
            targets_a=tuple(sorted(targets.items())),
            actuals_a=tuple(sorted(actuals.items())),
            beam_nA=float(self.beam_nA),
            captured_at_s=float(self.captured_at_s),
        )

    @property
    def target_map(self) -> dict[int, float]:
        return dict(self.targets_a)

    @property
    def actual_map(self) -> dict[int, float]:
        return dict(self.actuals_a)


@dataclass(frozen=True)
class GARecoveryCommand:
    """A full target difference to pass to the ordinary output callback."""

    channel_index: int
    delta_a: float
    reference_target_a: float
    current_target_a: float


class GARecoveryManager:
    """Request the captured software targets without evaluating physical recovery."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.reference: GARecoveryReference | None = None
        self.active = False

    @staticmethod
    def _value(container: Sequence[float] | Mapping[int, float], index: int) -> float:
        try:
            return float(container[index])
        except (IndexError, KeyError, TypeError, ValueError, OverflowError):
            return float("nan")

    @staticmethod
    def capture(
        *,
        targets_a: Sequence[float] | Mapping[int, float],
        actual_values_a: Sequence[float] | Mapping[int, float],
        beam_nA: float,
        channel_indices: Sequence[int],
        timestamp_s: float,
    ) -> GARecoveryReference:
        target_references: list[tuple[int, float]] = []
        actual_references: list[tuple[int, float]] = []
        for raw_index in channel_indices:
            index = int(raw_index)
            target = GARecoveryManager._value(targets_a, index)
            actual = GARecoveryManager._value(actual_values_a, index)
            if not math.isfinite(target):
                raise ValueError(f"No finite target is available for recovery channel {index}")
            if not math.isfinite(actual):
                raise ValueError(f"No finite readback is available for recovery channel {index}")
            target_references.append((index, target))
            actual_references.append((index, actual))
        return GARecoveryReference(
            targets_a=tuple(target_references),
            actuals_a=tuple(actual_references),
            beam_nA=float(beam_nA),
            captured_at_s=float(timestamp_s),
        ).validated()

    def start(self, *, reference: GARecoveryReference) -> None:
        self.reference = reference.validated()
        self.active = True

    def next_command(
        self,
        current_targets_a: Sequence[float] | Mapping[int, float],
    ) -> GARecoveryCommand | None:
        """Return one full target correction, or None when all targets match.

        Selected channels are checked in increasing index order. All selected
        current targets must be finite before any request is returned. The
        caller applies a request and supplies its updated software targets on
        the next call; this manager never writes targets itself.
        """
        if not self.active or self.reference is None:
            return None

        command: GARecoveryCommand | None = None
        for index, reference_target in self.reference.targets_a:
            current = self._value(current_targets_a, index)
            if not math.isfinite(current):
                raise ValueError(f"No finite target is available for recovery channel {index}")
            if round(current, 2) == round(reference_target, 2):
                continue
            delta = reference_target - current
            if not math.isfinite(delta):
                raise ValueError(f"Recovery target difference is non-finite for channel {index}")
            if command is None:
                command = GARecoveryCommand(
                    channel_index=index,
                    delta_a=delta,
                    reference_target_a=reference_target,
                    current_target_a=current,
                )

        if command is None:
            self.active = False
        return command


__all__ = [
    "GARecoveryCommand",
    "GARecoveryManager",
    "GARecoveryReference",
]
