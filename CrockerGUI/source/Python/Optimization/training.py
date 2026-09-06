"""Training-data assembly for Bayesian optimization surrogate models."""

from __future__ import annotations

from typing import Any, Sequence

from source.Python.Optimization.observations import OptimizationObservation
from source.Python.Optimization.parameter_space import ParameterSpace


def build_training_tensors(
    *,
    observations: Sequence[OptimizationObservation],
    parameter_space: ParameterSpace,
    torch: Any,
    tensor_options: dict[str, Any],
) -> tuple[Any, Any]:
    train_x = torch.tensor(
        [
            parameter_space.candidate_vector(observation.candidate)
            for observation in observations
        ],
        **tensor_options,
    )
    # BoTorch maximizes objectives; observation score is a cost.
    train_y = torch.tensor(
        [[-observation.score] for observation in observations],
        **tensor_options,
    )
    return train_x, train_y

