"""PID gain adapter for the standalone Bayesian optimization package.

The reusable optimizer lives in ``source.Python.Optimization``. This module
keeps the PID-facing types stable while mapping PID gain trials onto a generic
bounded parameter space.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from source.Python.Optimization.bayesian_optimizer import BotorchBayesianOptimizer
from source.Python.Optimization.observations import OptimizationObservation
from source.Python.Optimization.parameter_space import OptimizationCandidate


@dataclass(frozen=True)
class PidGainCandidate:
    kp: float
    ki: float
    kd: float


@dataclass(frozen=True)
class PidTrialResult:
    """One completed closed-loop PID experiment.

    ``score`` is a cost (smaller is better). Unsafe experiments are retained in
    history for audit purposes, but are never used to train the performance
    model.
    """

    candidate: PidGainCandidate
    score: float
    settling_time: float
    overshoot: float
    steady_state_error: float
    control_effort: float
    safe: bool


class BotorchPidOptimizer:
    """PID-shaped compatibility wrapper around ``BotorchBayesianOptimizer``."""

    def __init__(
        self,
        kp_bounds: tuple[float, float],
        ki_bounds: tuple[float, float],
        kd_bounds: tuple[float, float],
        use_cuda: bool = True,
        *,
        initial_safe_trials: int = 6,
        seed: int = 1729,
        mc_samples: int = 256,
        num_restarts: int = 10,
        raw_samples: int = 256,
    ) -> None:
        self.optimizer = BotorchBayesianOptimizer(
            [
                ("kp", kp_bounds),
                ("ki", ki_bounds),
                ("kd", kd_bounds),
            ],
            use_cuda=use_cuda,
            initial_safe_trials=initial_safe_trials,
            seed=seed,
            mc_samples=mc_samples,
            num_restarts=num_restarts,
            raw_samples=raw_samples,
        )
        self.results: list[PidTrialResult] = []

    @property
    def safe_results(self) -> list[PidTrialResult]:
        return [result for result in self.results if result.safe]

    @property
    def best_result(self) -> PidTrialResult | None:
        safe = self.safe_results
        return min(safe, key=lambda result: result.score) if safe else None

    def propose_batch(self, batch_size: int) -> list[PidGainCandidate]:
        return [
            self._to_pid_candidate(candidate)
            for candidate in self.optimizer.propose_batch(batch_size)
        ]

    def record_results(self, results: Iterable[PidTrialResult]) -> None:
        validated = list(results)
        observations: list[OptimizationObservation] = []
        for result in validated:
            values = (
                result.candidate.kp,
                result.candidate.ki,
                result.candidate.kd,
                result.score,
                result.settling_time,
                result.overshoot,
                result.steady_state_error,
                result.control_effort,
            )
            if not all(math.isfinite(value) for value in values):
                raise ValueError("PID trial values must be finite")
            observations.append(
                OptimizationObservation(
                    candidate=self._from_pid_candidate(result.candidate),
                    score=result.score,
                    safe=result.safe,
                    metadata={
                        "settling_time": result.settling_time,
                        "overshoot": result.overshoot,
                        "steady_state_error": result.steady_state_error,
                        "control_effort": result.control_effort,
                    },
                )
            )
        self.optimizer.record_observations(observations)
        self.results.extend(validated)

    def surrogate_grid(
        self,
        *,
        kd_value: float | None = None,
        grid_size: int = 28,
    ) -> dict:
        fixed_values = {}
        if kd_value is not None:
            fixed_values["kd"] = float(kd_value)
        return self.optimizer.surrogate_grid(
            axis_x="kp",
            axis_y="ki",
            fixed_values=fixed_values,
            grid_size=grid_size,
        )

    @staticmethod
    def _from_pid_candidate(candidate: PidGainCandidate) -> OptimizationCandidate:
        return OptimizationCandidate(
            {
                "kp": float(candidate.kp),
                "ki": float(candidate.ki),
                "kd": float(candidate.kd),
            }
        )

    @staticmethod
    def _to_pid_candidate(candidate: OptimizationCandidate) -> PidGainCandidate:
        return PidGainCandidate(
            kp=candidate.value("kp"),
            ki=candidate.value("ki"),
            kd=candidate.value("kd"),
        )
