"""Poll-driven simulation coordinator for direct trim-coil BO.

No ControlService adapter is provided: joint-coil hardware execution requires a
separate integration review. All time supplied here is monotonic session time.
"""
from __future__ import annotations

import math
import statistics
import threading
from collections import deque
from dataclasses import asdict, dataclass

from .reference_store import MeasuredReference, finite
from ..Optimization.parameter_space import OptimizationCandidate, ParameterSpace
from ..Optimization.observations import OptimizationObservation


@dataclass(frozen=True)
class TrimCoilConfig:
    trial_budget: int = 10
    time_budget_s: float = 300
    baseline_windows: int = 3
    confirmation_pairs: int = 3
    drift_every: int = 3
    minimum_gain_nA: float = 0.1
    confidence_multiplier: float = 3.0
    drift_tolerance_nA: float = 1.0
    target_tolerance_a: float = 0.01
    stable_hold_s: float = 1
    measurement_window_s: float = 2
    stage_timeout_s: float = 15
    max_telemetry_age_s: float = 0.5
    minimum_beam_nA: float = 0.1
    maximum_window_stddev_nA: float = 1
    minimum_samples: int = 3

    def validate(self):
        for key, value in asdict(self).items():
            finite(value, key)
            if value <= 0:
                raise ValueError(f'{key} must be positive')
        for key in ('trial_budget', 'baseline_windows', 'confirmation_pairs', 'drift_every', 'minimum_samples'):
            if type(getattr(self, key)) is not int:
                raise ValueError(f'{key} must be an integer')
        if min(self.baseline_windows, self.confirmation_pairs, self.minimum_samples) < 2:
            raise ValueError('Repeated windows and samples are required')
        if self.stage_timeout_s <= self.stable_hold_s + self.measurement_window_s:
            raise ValueError('Stage timeout must exceed settling hold plus acquisition window')
        return self


@dataclass(frozen=True)
class BeamSnapshot:
    timestamp_s: float
    readbacks_a: dict[str, float]
    beam_nA: float
    configuration: dict
    diagnostic: str
    valid: bool = True
    outputs_ready: bool = True


class TrimCoilSession:
    """Own one simulator, returning to the fixed reference after every window.

    Backend contract: mode, acquire(owner), release(owner), cancel(owner),
    validate_transition(targets), apply(targets, owner), snapshot(now).
    apply validates the complete transition and reports partial/rejected writes
    by raising. The coordinator never enables outputs or bypasses the backend.
    """
    TERMINAL = {'completed', 'stopped', 'blocked'}

    def __init__(self, *, backend, reference: MeasuredReference, parameters,
                 optimizer, config: TrimCoilConfig):
        if getattr(backend, 'mode', None) != 'simulation':
            raise ValueError('Direct multi-coil BO is currently simulation-only')
        self.config = config.validate()
        self.backend, self.reference, self.optimizer = backend, reference, optimizer
        self.space = ParameterSpace(parameters)
        if tuple(optimizer.parameter_names) != self.space.names:
            raise ValueError('Optimizer and session channel mapping differ')
        if tuple(p.bounds for p in optimizer.parameters) != tuple(p.bounds for p in self.space.parameters):
            raise ValueError('Optimizer and session bounds differ')
        if not set(self.space.names) <= set(reference.targets_a):
            raise ValueError('Reference is missing selected coils')
        self.reference_point = {k: reference.targets_a[k] for k in self.space.names}
        self._validate_candidate(self.reference_point)
        if optimizer.observations:
            raise ValueError('Start with a fresh optimizer; historical data needs compatibility review')
        self.incumbent = dict(self.reference_point)
        self.incumbent_mean = None
        self.state, self.reason = 'idle', ''
        self.audit, self.windows = [], []
        self.queue = deque()
        self.trials = 0
        self.owned = False
        self.last_now = None
        self.last_stamp = None
        self.baselines = []
        self.confirmation = None
        self.abort_requested = threading.Event()
        self.final_verification_queued = False

    def _validate_candidate(self, values):
        if set(values) != set(self.space.names):
            raise ValueError('Candidate must contain exactly the selected coil names')
        self.space.validate_candidate(OptimizationCandidate(values))

    def _full_targets(self, point):
        return {**self.reference.targets_a, **point}

    def _event(self, event, **values):
        self.audit.append({'event': event, 'time_s': self.last_now, 'state': self.state, **values})

    def start(self, now):
        if self.state != 'idle':
            raise ValueError('Session cannot restart; create a new session')
        finite(now, 'session time')
        if not self.backend.acquire(self):
            raise ValueError('Exclusive control ownership unavailable')
        self.owned = True
        self.started = self.last_now = now
        self.queue.extend(('baseline', dict(self.reference_point)) for _ in range(self.config.baseline_windows))
        self._event('start', configuration=self.reference.machine_configuration,
                    reference_targets_a=dict(self.reference.targets_a),
                    reference_readbacks_a=dict(self.reference.readbacks_a),
                    initial_distinct_settings=getattr(self.optimizer, 'initial_safe_trials', 1),
                    reference_id=self.reference.reference_id, config=asdict(self.config),
                    parameters=[{'name': p.name, 'bounds': p.bounds} for p in self.space.parameters],
                    optimizer_seed=getattr(self.optimizer, 'seed', None))
        self._next(now)

    def abort(self):
        if self.state not in self.TERMINAL and self.state != 'idle':
            self._stop('operator abort', self.last_now)

    def request_abort(self):
        """Thread-safe cancellation request, checked again after model fitting."""
        self.abort_requested.set()

    def _release(self):
        if self.owned:
            self.backend.release(self)
            self.owned = False

    def _apply(self, point):
        self._validate_candidate(point)
        targets = self._full_targets(point)
        self.backend.validate_transition(targets)
        if self.backend.apply(targets, self) is not True:
            raise ValueError('Rejected or partially applied command')

    def _next(self, now):
        try:
            if self.abort_requested.is_set():
                self._stop('operator abort', now)
                return
            if self.queue:
                kind, point = self.queue.popleft()
            elif self.trials < self.config.trial_budget:
                kind = 'candidate'
                point = dict(self.optimizer.propose_batch(1)[0].values)
                if self.abort_requested.is_set():
                    self._stop('operator abort', now)
                    return
            elif not self.final_verification_queued:
                self.final_verification_queued = True
                self.queue.extend([('final_incumbent', dict(self.incumbent)),
                                   ('drift', dict(self.reference_point))])
                self._next(now)
                return
            else:
                self.state, self.reason = 'completed', 'trial budget reached; reference verified'
                self._event('finish', incumbent=dict(self.incumbent), incumbent_mean_nA=self.incumbent_mean)
                self._release()
                return
            self._validate_candidate(point)
            self.current_kind, self.current_point = kind, point
            self._apply(point)
            self.state, self.stage_start = 'settling', now
            self.stable_since, self.samples = None, []
            self._event('apply', kind=kind, targets_a=self._full_targets(point))
        except Exception as exc:
            self._stop(str(exc), now)

    def _stop(self, reason, now):
        self.reason = reason
        self.queue.clear()
        self._event('stop', reason=reason, kind=getattr(self, 'current_kind', None),
                    targets_a=getattr(self, 'current_point', None),
                    interrupted_samples=list(getattr(self, 'samples', [])))
        try:
            self.backend.cancel(self)
            self._apply(self.reference_point)
            self.state, self.stage_start, self.stable_since = 'recovering', now, None
        except Exception as exc:
            self.state = 'blocked'
            self.reason += f'; recovery blocked: {exc}'
            self._event('recovery_blocked', reason=self.reason)
            self._release()

    def poll(self, now):
        if self.state == 'idle' or self.state in self.TERMINAL:
            return
        finite(now, 'session time')
        if now < self.last_now:
            raise ValueError('Session time must be monotonic')
        self.last_now = now
        try:
            if self.abort_requested.is_set() and self.state != 'recovering':
                self._stop('operator abort', now)
                return
            if now - self.started >= self.config.time_budget_s and self.state != 'recovering':
                self._stop('time budget reached', now)
                return
            snapshot = self.backend.snapshot(now)
            self._validate_snapshot(snapshot, now)
            if now - self.stage_start > self.config.stage_timeout_s:
                raise ValueError(f'{self.state} timeout')
            # Held packets must neither accumulate samples nor establish a stable hold.
            if self.last_stamp is not None and snapshot.timestamp_s <= self.last_stamp:
                return
            self.last_stamp = snapshot.timestamp_s
            target = self.reference_point if self.state in ('returning', 'recovering') else self.current_point
            settled = all(abs(snapshot.readbacks_a[k] - v) <= self.config.target_tolerance_a
                          for k, v in self._full_targets(target).items())
            if not settled:
                self.stable_since = None
                if self.state == 'measuring':
                    raise ValueError('Readbacks left tolerance during acquisition')
                return
            if self.stable_since is None:
                self.stable_since = snapshot.timestamp_s
            if self.state in ('returning', 'recovering'):
                if self.baselines and abs(snapshot.beam_nA - self.baseline_mean) > self.config.drift_tolerance_nA:
                    raise ValueError('Reference beam did not recover within drift tolerance')
                if snapshot.timestamp_s - self.stable_since >= self.config.stable_hold_s:
                    if self.state == 'recovering':
                        self.state = 'stopped'
                        self._event('recovery_verified', reason=self.reason)
                        self._release()
                    else:
                        self._after_return(now)
                return
            if self.state == 'settling':
                if snapshot.timestamp_s - self.stable_since < self.config.stable_hold_s:
                    return
                self.state, self.window_start = 'measuring', snapshot.timestamp_s
                self.stage_start = now
                return  # acquisition uses a separate window after stable hold
            self.samples.append((snapshot.timestamp_s, snapshot.beam_nA, dict(snapshot.readbacks_a)))
            if snapshot.timestamp_s - self.window_start >= self.config.measurement_window_s:
                self._finish_window(now)
        except Exception as exc:
            if self.state == 'recovering':
                self.state = 'blocked'
                self.reason += f'; recovery blocked: {exc}'
                self._event('recovery_blocked', reason=self.reason)
                self._release()
            else:
                self._stop(str(exc), now)

    def _validate_snapshot(self, snapshot, now):
        stamp = finite(snapshot.timestamp_s, 'telemetry timestamp')
        if not 0 <= now - stamp <= self.config.max_telemetry_age_s:
            raise ValueError('Stale telemetry')
        if not snapshot.valid or not snapshot.outputs_ready:
            raise ValueError('Invalid diagnostic, interlock, or disabled output')
        if snapshot.configuration != self.reference.machine_configuration or snapshot.diagnostic != self.reference.diagnostic:
            raise ValueError('Machine configuration or diagnostic changed')
        if finite(snapshot.beam_nA, 'beam') < self.config.minimum_beam_nA:
            raise ValueError('Beam loss')
        for name in self.reference.targets_a:
            finite(snapshot.readbacks_a.get(name), f'{name} readback')

    def _finish_window(self, now):
        values = [sample[1] for sample in self.samples]
        if len(values) < self.config.minimum_samples:
            raise ValueError('Insufficient fresh acquisition samples')
        mean, stddev = statistics.mean(values), statistics.stdev(values)
        if stddev > self.config.maximum_window_stddev_nA:
            raise ValueError('Unstable beam window')
        window = {'kind': self.current_kind, 'point': dict(self.current_point),
                  'mean_nA': mean, 'stddev_nA': stddev, 'sample_count': len(values),
                  'time_s': now, 'raw_samples': list(self.samples)}
        self.windows.append(window)
        # Do not assume independent telemetry to manufacture a variance of the mean.
        self.optimizer.record_observations([OptimizationObservation(
            OptimizationCandidate(dict(self.current_point)), -mean,
            metadata={'timestamp_s': now, 'stddev_nA': stddev, 'sample_count': len(values), 'kind': self.current_kind})])
        self._event('measurement', **window)
        self._apply(self.reference_point)
        self.state, self.stage_start, self.stable_since = 'returning', now, None

    def _after_return(self, now):
        window = self.windows[-1]
        kind, mean = window['kind'], window['mean_nA']
        if kind == 'baseline':
            self.baselines.append(mean)
            self.baseline_mean = statistics.mean(self.baselines)
            self.incumbent_mean = self.baseline_mean
            if max(self.baselines) - min(self.baselines) > self.config.drift_tolerance_nA:
                self._stop('Unstable initial reference', now)
                return
        elif kind == 'candidate':
            self.trials += 1
            if mean > self.incumbent_mean + self.config.minimum_gain_nA:
                self.confirmation = {'point': dict(window['point']), 'candidate': [], 'incumbent': []}
                for _ in range(self.config.confirmation_pairs):
                    self.queue.extend([('confirm_incumbent', dict(self.incumbent)),
                                       ('confirm_candidate', dict(window['point']))])
            if self.trials % self.config.drift_every == 0:
                self.queue.append(('drift', dict(self.reference_point)))
        elif kind.startswith('confirm_'):
            key = kind.removeprefix('confirm_')
            self.confirmation[key].append(mean)
            c, b = self.confirmation['candidate'], self.confirmation['incumbent']
            if len(c) == len(b) == self.config.confirmation_pairs:
                differences = [a - v for a, v in zip(c, b)]
                gain = statistics.mean(differences)
                se = statistics.stdev(differences) / math.sqrt(len(differences))
                lower = gain - self.config.confidence_multiplier * se
                accepted = lower > self.config.minimum_gain_nA
                if accepted:
                    self.incumbent = dict(self.confirmation['point'])
                    self.incumbent_mean = statistics.mean(c)
                else:
                    self.incumbent_mean = statistics.mean(b)
                self._event('confirmation', gain_nA=gain, standard_error_nA=se,
                            lower_bound_nA=lower, promoted=accepted, incumbent=dict(self.incumbent))
                self.confirmation = None
        elif kind == 'drift' and abs(mean - self.baseline_mean) > self.config.drift_tolerance_nA:
            self._stop('Reference drift exceeded tolerance', now)
            return
        elif kind == 'final_incumbent':
            # Verification is reported separately; a single window does not promote.
            self._event('final_verification', measured_mean_nA=mean, incumbent=dict(self.incumbent))
        self._next(now)
