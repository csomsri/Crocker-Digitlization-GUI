"""Drift scheduling only: hardware readiness and writes remain in the controller."""
from dataclasses import dataclass
import math


@dataclass
class CruiseSupervisor:
    active: bool = False
    drift_since: float | None = None
    ready_after: float = 0.0
    sessions: int = 0
    last_stamp: float | None = None

    def start(self, now, cooldown):
        self.active = True
        self.sessions = 0
        self.drift_since = self.last_stamp = None
        self.ready_after = now + cooldown

    def stop(self):
        self.active = False
        self.drift_since = self.last_stamp = None

    def rearm(self, now, cooldown):
        self.drift_since = self.last_stamp = None
        self.ready_after = now + cooldown

    def should_tune(self, *, now, stamp, error, ready, pending, automatic,
                    band, persistence, maximum_sessions):
        if not self.active or not ready or pending or not automatic or now < self.ready_after:
            self.drift_since = None
            return False
        if not all(math.isfinite(v) for v in (now, stamp, error)):
            self.drift_since = None
            return False
        if self.last_stamp is not None and stamp <= self.last_stamp:
            return False
        self.last_stamp = stamp
        if abs(error) <= band:
            self.drift_since = None
            return False
        if self.drift_since is None:
            self.drift_since = now
        return now-self.drift_since >= persistence and (maximum_sessions == 0 or self.sessions < maximum_sessions)
