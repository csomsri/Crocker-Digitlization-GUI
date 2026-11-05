"""Deterministic coupled-coil plant and executable BO demo. Never accesses devices."""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .reference_store import ReferenceStore
from .trim_coil_bo import BeamSnapshot, TrimCoilConfig, TrimCoilSession
from ..Optimization.trim_coil_optimizer import TrimCoilBayesianOptimizer


class CoupledCoilSimulator:
    mode = 'simulation'

    def __init__(self, reference, bounds, *, seed=1729, noise_nA=0.02, drift_nA_s=0):
        self.reference, self.bounds = reference, dict(bounds)
        self.targets = dict(reference.targets_a)
        self.actuals = dict(self.targets)
        self.owner = None
        self.random = random.Random(seed)
        self.noise_nA, self.drift_nA_s = noise_nA, drift_nA_s
        self.fault = None
        self.last_time = None
        self.command_history = []
        self.last_telemetry = None

    def acquire(self, owner):
        if self.owner is not None:
            return False
        self.owner = owner
        return True

    def release(self, owner):
        if self.owner is not owner:
            raise ValueError('Control ownership lost')
        self.owner = None

    def cancel(self, owner):
        if self.owner is not owner:
            raise ValueError('Control ownership lost')

    def validate_transition(self, targets):
        if set(targets) != set(self.reference.targets_a):
            raise ValueError('Whole reference vector required')
        if self.fault == 'interlock':
            raise ValueError('Interlock blocks writes')
        for name, value in targets.items():
            low, high = self.bounds.get(name, (self.reference.targets_a[name], self.reference.targets_a[name]))
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError('Simulator target outside configured local bounds')

    def apply(self, targets, owner):
        if self.owner is not owner:
            raise ValueError('Exclusive control required')
        self.validate_transition(targets)
        if self.fault == 'partial_write':
            name = next(iter(targets))
            self.targets[name] = targets[name]
            self.fault = None
            raise ValueError('Injected partial write')
        self.targets = dict(targets)
        self.command_history.append(dict(targets))
        return True

    def expected_beam(self, values, now=0):
        names = list(self.bounds)
        x = [(values[k] - self.reference.targets_a[k]) / ((self.bounds[k][1] - self.bounds[k][0]) / 2)
             for k in names]
        # Coupling makes independent one-coil tuning insufficient.
        gain = sum(0.8 * v - 1.5 * v * v for v in x)
        gain += sum(0.5 * a * b for a, b in zip(x, x[1:]))
        return self.reference.beam_nA + gain + self.drift_nA_s * now

    def snapshot(self, now):
        dt = 0 if self.last_time is None else max(0, now - self.last_time)
        self.last_time = now
        if self.fault != 'settling':
            for name in self.actuals:
                self.actuals[name] += (self.targets[name] - self.actuals[name]) * (1 - math.exp(-dt / 0.1))
        beam = self.expected_beam(self.actuals, now) + self.random.gauss(0, self.noise_nA)
        snapshot = BeamSnapshot(now - 10 if self.fault == 'stale' else now,
            dict(self.actuals), 0 if self.fault == 'beam_loss' else beam,
            dict(self.reference.machine_configuration), self.reference.diagnostic,
            valid=self.fault != 'invalid_diagnostic', outputs_ready=self.fault != 'interlock')
        # Capture targets at sampling time; the coordinator may command another
        # point later in the same poll, after this snapshot was acquired.
        self.last_telemetry = {'event': 'telemetry', 'time_s': snapshot.timestamp_s,
            'targets_a': dict(self.targets), 'readbacks_a': dict(snapshot.readbacks_a),
            'beam_nA': snapshot.beam_nA, 'valid': snapshot.valid and snapshot.outputs_ready}
        return snapshot


def simulation_reference():
    """Synthetic fixture, never derived from uncalibrated runsheet numbers."""
    return ReferenceStore.validate({
        'schema_version': 1, 'record_type': 'measured_reference',
        'reference_id': 'synthetic-demo', 'captured_at': '2026-01-01T00:00:00+00:00',
        'operator': 'simulator', 'source_dataset': 'synthetic coupled quadratic',
        'machine_configuration': {'mode': 'simulation', 'species': 'synthetic'},
        'coils': [{'channel': k, 'unit': 'A', 'target': 0., 'readback': 0.} for k in ('TC1', 'TC2')],
        'beam': {'diagnostic': 'synthetic-output', 'unit': 'nA', 'mean': 10.,
                 'stddev': .02, 'sample_count': 20, 'window_s': 2.}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trials', type=int, default=10)
    parser.add_argument('--seed', type=int, default=1729)
    parser.add_argument('--stream', action='store_true', help='Emit JSON progress lines; accept abort on stdin')
    parser.add_argument('--output', type=Path, help='New JSON audit file; existing files are never overwritten')
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        parser.error('Output file already exists')
    import torch
    torch.set_num_threads(1)  # Small GP fits; avoid oversubscribing CPU cores.
    reference = simulation_reference()
    parameters = [('TC1', (-.5, .5)), ('TC2', (-.5, .5))]
    optimizer = TrimCoilBayesianOptimizer(parameters, use_cuda=False, initial_safe_trials=4,
        seed=args.seed, mc_samples=32, num_restarts=2, raw_samples=32)
    backend = CoupledCoilSimulator(reference, dict(parameters), seed=args.seed)
    # Capture the state already producing beam; never load an operating run sheet.
    snapshot = backend.snapshot(0.)
    reference = replace(reference, reference_id='session-start',
                        targets_a=dict(backend.targets), readbacks_a=dict(snapshot.readbacks_a),
                        captured_at=datetime.now(timezone.utc).isoformat())
    config = TrimCoilConfig(trial_budget=args.trials, time_budget_s=1000,
                           stable_hold_s=.2, measurement_window_s=.4)
    session = TrimCoilSession(backend=backend, reference=reference, parameters=parameters,
                             optimizer=optimizer, config=config)
    if args.stream:
        def read_commands():
            for line in sys.stdin:
                if line.strip() == 'abort':
                    session.request_abort()
                    break
        threading.Thread(target=read_commands, daemon=True).start()
    now = 0.
    session.start(now)
    delivered = 0
    while session.state not in session.TERMINAL:
        now = round(now + .1, 8)
        session.poll(now)
        if backend.last_telemetry is not None:
            telemetry = backend.last_telemetry
            if telemetry['time_s'] == now:
                session.audit.append(dict(telemetry))
        if args.stream:
            for event in session.audit[delivered:]:
                print(json.dumps({'progress': event}), flush=True)
            delivered = len(session.audit)
    summary = {'mode': 'simulation', 'state': session.state, 'reason': session.reason,
               'seed': args.seed, 'candidate_trials': session.trials,
               'measurement_windows': len(session.windows), 'simulated_elapsed_s': now,
               'baseline_nA': getattr(session, 'baseline_mean', None),
               'incumbent_targets_a': session.incumbent, 'incumbent_mean_nA': session.incumbent_mean,
               'reference_restored': backend.targets == reference.targets_a}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as handle:
            json.dump({'created_at': datetime.now(timezone.utc).isoformat(),
                       'summary': summary, 'events': session.audit}, handle, indent=2, allow_nan=False)
    print(json.dumps({'summary': summary}) if args.stream else json.dumps(summary, indent=2), flush=True)
    return 0 if session.state == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
