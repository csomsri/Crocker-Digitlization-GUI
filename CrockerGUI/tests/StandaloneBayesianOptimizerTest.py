"""Smoke test for the standalone Bayesian optimizer."""

from __future__ import annotations

import sys
from pathlib import Path


CROCKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CROCKER_ROOT))

from source.Python.Optimization.bayesian_optimizer import (  # noqa: E402
    BotorchBayesianOptimizer,
    OptimizationObservation,
)


def main() -> int:
    optimizer = BotorchBayesianOptimizer(
        [
            ("x", (-2.0, 2.0)),
            ("y", (-1.0, 3.0)),
        ],
        use_cuda=False,
        initial_safe_trials=4,
        mc_samples=32,
        num_restarts=2,
        raw_samples=32,
    )
    initial = optimizer.propose_batch(4)
    if len(initial) != 4:
        raise RuntimeError("Sobol initialization did not return four candidates")
    if any(set(candidate.values) != {"x", "y"} for candidate in initial):
        raise RuntimeError("Candidate did not preserve the named parameter space")

    observations = []
    for candidate in initial:
        x = candidate.value("x")
        y = candidate.value("y")
        score = (x - 0.25) ** 2 + (y - 1.5) ** 2
        observations.append(
            OptimizationObservation(
                candidate=candidate,
                score=score,
                safe=True,
                metadata={"source": "smoke-test"},
            )
        )
    optimizer.record_observations(observations)

    proposed = optimizer.propose_batch(1)
    if len(proposed) != 1:
        raise RuntimeError("BoTorch did not return one standalone candidate")
    grid = optimizer.surrogate_grid(axis_x="x", axis_y="y", grid_size=8)
    if not grid.get("ready"):
        raise RuntimeError(f"Surrogate grid was not ready: {grid}")
    if len(grid["mean"]) != 8 or len(grid["mean"][0]) != 8:
        raise RuntimeError("Surrogate grid did not have the expected shape")
    if optimizer.best_observation is None:
        raise RuntimeError("Best safe observation was not retained")
    print(f"Standalone Bayesian optimizer test passed: proposed={proposed[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
