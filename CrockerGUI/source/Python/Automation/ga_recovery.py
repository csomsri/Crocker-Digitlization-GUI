"""Pure recovery planner: commands are proposals, never hardware writes."""
from dataclasses import dataclass, asdict
from types import SimpleNamespace
import math


@dataclass(frozen=True)
class GARecoveryConfig:
    command_step_a: float = .02
    target_tolerance_a: float = .005
    actual_tolerance_a: float = .5
    minimum_beam_nA: float = .05
    minimum_beam_fraction: float = .5
    beam_reference_tolerance_nA: float = .2
    stable_hold_s: float = 2
    timeout_s: float = 20

    def validated(self):
        if not all(math.isfinite(v) and v >= 0 for v in asdict(self).values()):
            raise ValueError('Recovery settings must be finite and nonnegative')
        if self.command_step_a <= 0 or self.timeout_s <= self.stable_hold_s or self.minimum_beam_fraction > 1:
            raise ValueError('Invalid recovery step, timeout or beam fraction')
        return self


@dataclass(frozen=True)
class GARecoveryReference:
    targets_a: tuple
    actuals_a: tuple
    beam_nA: float
    timestamp_s: float

    @property
    def target_map(self):
        return dict(self.targets_a)

    @property
    def actual_map(self):
        return dict(self.actuals_a)


class GARecoveryManager:
    def __init__(self):
        self.reset()

    def reset(self):
        self.reference = None
        self.stable_since = None

    @staticmethod
    def capture(*, targets_a, actual_values_a, beam_nA, channel_indices, timestamp_s):
        indices = tuple(dict.fromkeys(channel_indices))
        if not indices or any(i < 0 or i >= len(targets_a) or i >= len(actual_values_a) for i in indices):
            raise ValueError('Invalid recovery channels')
        values = [beam_nA, timestamp_s] + [targets_a[i] for i in indices] + [actual_values_a[i] for i in indices]
        if not all(math.isfinite(v) for v in values):
            raise ValueError('Recovery reference must be finite')
        return GARecoveryReference(tuple((i,targets_a[i]) for i in indices),
                                   tuple((i,actual_values_a[i]) for i in indices), beam_nA, timestamp_s)

    def start(self, *, reference, config, timestamp_s):
        self.reference, self.config, self.start_time = reference, config.validated(), timestamp_s
        self.stable_since = None

    def next_command(self, current_targets_a):
        for index, target in self.reference.targets_a:
            current = current_targets_a[index]
            if not math.isfinite(current):
                raise ValueError('Invalid target during recovery')
            delta = target-current
            if abs(delta) > self.config.target_tolerance_a:
                step = self.config.command_step_a
                return SimpleNamespace(channel_index=index, delta_a=max(-step,min(step,delta)))
        return None

    def observe(self, *, timestamp_s, current_targets_a, actual_values_a, beam_nA):
        c, r = self.config, self.reference
        stable = math.isfinite(beam_nA) and abs(beam_nA) >= max(c.minimum_beam_nA, abs(r.beam_nA)*c.minimum_beam_fraction)
        stable = stable and abs(beam_nA-r.beam_nA) <= c.beam_reference_tolerance_nA
        stable = stable and all(math.isfinite(current_targets_a[i]) and abs(current_targets_a[i]-v) <= c.target_tolerance_a for i,v in r.targets_a)
        stable = stable and all(math.isfinite(actual_values_a[i]) and abs(actual_values_a[i]-v) <= c.actual_tolerance_a for i,v in r.actuals_a)
        if not stable:
            self.stable_since = None
        elif self.stable_since is None:
            self.stable_since = timestamp_s
        elapsed = timestamp_s-self.start_time
        timed_out = elapsed >= c.timeout_s
        complete = not timed_out and self.stable_since is not None and timestamp_s-self.stable_since >= c.stable_hold_s
        return SimpleNamespace(elapsed_s=elapsed, complete=complete, timed_out=timed_out,
                               status='Reference recovered' if complete else 'Recovery timed out' if timed_out else 'Restoring reference; waiting for stable feedback')
