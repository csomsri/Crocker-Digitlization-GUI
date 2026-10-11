"""Simulation-only diagnostic: bound C++ PID, first-order plant, real BO.

Runs accelerated deterministic trials without Qt, ZMQ, or hardware. This
isolates optimizer/controller behavior; it does not reproduce GUI timing.
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import CycloViz
from source.Python.Optimization.pid_gain_adapter import BotorchPidOptimizer, PidGainCandidate, PidTrialResult
from source.Python.Optimization.hybrid_pid_optimizer import HybridPIDOptimizer, HybridConfig
from source.Python.Optimization.trial_metrics import evaluate_trial, trial_cost
from source.Python.Simulator.FirstOrderBeamPlant import FirstOrderBeamPlant
from source.Python.Simulator.ZMQSimulator import build_bitmask


def struct(name, **values):
    obj = getattr(CycloViz, name)()
    for key, value in values.items():
        setattr(obj, key, value)
    return obj


def trial(candidate, initial=193.0):
    plant = FirstOrderBeamPlant()
    plant.channels[9] = initial
    plant.beam_na = initial * plant.gain_na_per_a
    command = initial
    pid = CycloViz.NLAPID(
        struct('NLAPIDGains', kp=candidate.kp, ki=candidate.ki, kd=candidate.kd),
        struct('NLAPIDLimits', output_max=300.0,
               integral_max=300.0, derivative_filter_tau=0.2),
        struct('NLAPIDSettings', deadband=0.01, initial_direction=1,
               direction_each_update=True, integral_memory_s=20.0, max_control_dt=0.1))
    enabled = [False] * 14
    enabled[9] = True
    mask = build_bitmask([True] * 14, enabled)
    rows = [(0.0, plant.beam_na, 1.0-plant.beam_na, 0.0, command, 0)]
    for step in range(1, 301):
        output = pid.update(1.0, plant.beam_na, 0.1, False)
        command = max(0.0, min(300.0, command + output['output']))
        targets = list(plant.channels)
        targets[9] = command
        plant.apply_reply([x * plant.raw_scale for x in targets] + [mask], 0.1)
        rows.append((step * 0.1, plant.beam_na, 1.0-plant.beam_na,
                     output['output']/0.1, command, int(output['saturated'] or command in (0, 300))))
    metrics = evaluate_trial(rows, 1.0, baseline_target=initial)
    return PidTrialResult(candidate, trial_cost(metrics), metrics.settling_time,
                          metrics.overshoot, metrics.steady_state_error,
                          metrics.control_effort, True, metrics=metrics), plant.channels[9]


def main():
    seed = PidGainCandidate(100, 5, 1)
    repeats = {}
    for start in (193.0, 245.0, 250.0):
        result, _ = trial(seed, start)
        repeats[str(start)] = dict(cost=result.score, beam_mae=result.metrics.mean_absolute_error,
                                  settled=result.metrics.settled)
    report = dict(scope='C++ engine and first-order plant; no GUI timing or hardware', repeats=repeats, searches={})
    bounds = ((0.0, 200.0), (0.0, 20.0), (0.0, 50.0))
    for mode in ('BO reset', 'BO carry', 'Hybrid reset'):
        hybrid = mode.startswith('Hybrid')
        optimizer = (HybridPIDOptimizer(bounds, seed, HybridConfig(budget=24)) if hybrid
                     else BotorchPidOptimizer(*bounds, use_cuda=False))
        optimizer.optimizer.mc_samples = 16
        optimizer.optimizer.num_restarts = 2
        optimizer.optimizer.raw_samples = 32
        initial = 193.0
        history = []
        for index in range(24 if hybrid else 18):
            candidate = optimizer.propose_batch(1)[0]
            source = optimizer.pending_source if hybrid else ('Sobol' if index < 6 else 'BO')
            result, final = trial(candidate, initial)
            optimizer.record_results([result])
            history.append(dict(trial=index+1, source=source, start_A=initial,
                                kp=candidate.kp, ki=candidate.ki, kd=candidate.kd,
                                cost=result.score, beam_mae=result.metrics.mean_absolute_error,
                                settled=result.metrics.settled, oscillating=result.metrics.sustained_oscillation))
            initial = final if mode == 'BO carry' else 193.0
        best = min(history, key=lambda row: row['cost'])
        validated, _ = trial(PidGainCandidate(best['kp'], best['ki'], best['kd']))
        report['searches'][mode] = dict(history=history, best=best,
            reset_validation_cost=validated.score, sources=dict(Counter(row['source'] for row in history)),
            state=str(optimizer.state) if hybrid else 'BO',
            events=optimizer.events if hybrid else [])
        print(mode, 'best=', best['cost'], 'reset validation=', validated.score, flush=True)
    path = ROOT / 'Exports' / 'bo-convergence-diagnostic.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(path, flush=True)


if __name__ == '__main__':
    main()
