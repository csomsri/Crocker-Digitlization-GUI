"""Observation/evaluation history for Bayesian optimization.

The real experiment is still external to this package. This module records the
caller's evaluated candidates and keeps unsafe results out of model training.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from source.Python.Optimization.parameter_space import (
    OptimizationCandidate,
    ParameterSpace,
)


@dataclass(frozen=True)
class OptimizationObservation:
    """One completed experiment.

    ``score`` is a cost (smaller is better). Unsafe observations are retained in
    history for audit purposes, but are not used to train the performance model.
    Metadata is owned by the caller and can contain workflow-specific metrics.
    """

    candidate: OptimizationCandidate
    score: float
    safe: bool = True
    metadata: dict[str, float | str | bool] | None = None


class ObservationHistory:
    def __init__(self, parameter_space: ParameterSpace) -> None:
        self.parameter_space = parameter_space
        self.observations: list[OptimizationObservation] = []

    @property
    def safe_observations(self) -> list[OptimizationObservation]:
        return [observation for observation in self.observations if observation.safe]

    @property
    def best_observation(self) -> OptimizationObservation | None:
        safe = self.safe_observations
        return min(safe, key=lambda observation: observation.score) if safe else None

    def record(self, observations: Iterable[OptimizationObservation]) -> None:
        validated = list(observations)
        for observation in validated:
            self._validate_observation(observation)
        self.observations.extend(validated)

    def _validate_observation(self, observation: OptimizationObservation) -> None:
        if not math.isfinite(observation.score):
            raise ValueError("Observation score must be finite")
        self.parameter_space.validate_candidate(observation.candidate)
        if observation.metadata is None:
            return
        for key, value in observation.metadata.items():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"Observation metadata {key!r} must be finite")

