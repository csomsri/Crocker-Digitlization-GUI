"""Smoke test for the BoTorch PID gain proposal loop."""

from __future__ import annotations

import sys
from pathlib import Path


CROCKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CROCKER_ROOT))

from source.Python.Optimization.pid_gain_adapter import (  # noqa: E402
    BotorchPidOptimizer,
    PidTrialResult,
)


def main() -> int:
    optimizer = BotorchPidOptimizer(
        (0.0, 5.0), (0.0, 2.0), (0.0, 1.0),
        use_cuda=False,
        initial_safe_trials=4,
        mc_samples=32,
        num_restarts=2,
        raw_samples=32,
    )
    initial = optimizer.propose_batch(4)
    if len(initial) != 4 or len(set(initial)) != 4:
        raise RuntimeError("Sobol initialization did not return four distinct candidates")

    results = []
    for candidate in initial:
        score = (candidate.kp - 2.0) ** 2 + (candidate.ki - 0.5) ** 2 + candidate.kd**2
        results.append(PidTrialResult(candidate, score, score, 0.0, score, 0.0, True))
    optimizer.record_results(results)

    proposed = optimizer.propose_batch(1)
    if len(proposed) != 1:
        raise RuntimeError("BoTorch did not return one candidate")
    grid = optimizer.surrogate_grid(kd_value=0.0, grid_size=8)
    if not grid.get("ready"):
        raise RuntimeError(f"PID surrogate grid was not ready: {grid}")
    if optimizer.best_result is None:
        raise RuntimeError("Best safe PID result was not retained")
    print(f"BoTorch PID optimizer test passed: proposed={proposed[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
