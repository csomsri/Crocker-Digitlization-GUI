"""Public orchestration for standalone bounded Bayesian optimization.

The implementation is split by responsibility:

- ``parameter_space.py`` defines parameters and candidates.
- ``observations.py`` records evaluated candidates.
- ``training.py`` converts safe observations into training tensors.
- ``surrogate_model.py`` builds and fits the GP surrogate model.
- ``acquisition.py`` chooses the next model-guided candidates.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from source.Python.Optimization.acquisition import propose_expected_improvement_batch
from source.Python.Optimization.observations import (
    ObservationHistory,
    OptimizationObservation,
)
from source.Python.Optimization.parameter_space import (
    OptimizationCandidate,
    OptimizationParameter,
    ParameterSpace,
)
from source.Python.Optimization.surrogate_model import (
    fit_single_task_gp,
    predict_posterior_mean_variance,
)
from source.Python.Optimization.training import build_training_tensors


class BotorchBayesianOptimizer:
    """Propose bounded candidates with Sobol seeding followed by GP qLogEI.

    The optimizer is intentionally standalone: callers define the parameter
    names and bounds, run the real experiment elsewhere, calculate a scalar
    cost, then record the result.
    """

    def __init__(
        self,
        parameters: Sequence[OptimizationParameter | tuple[str, tuple[float, float]]],
        use_cuda: bool = True,
        *,
        initial_safe_trials: int = 6,
        seed: int = 1729,
        mc_samples: int = 256,
        num_restarts: int = 10,
        raw_samples: int = 256,
    ) -> None:
        if initial_safe_trials < 1:
            raise ValueError("initial_safe_trials must be positive")
        if mc_samples < 1 or num_restarts < 1 or raw_samples < 1:
            raise ValueError("BoTorch sampling and restart counts must be positive")

        # Store the parameter space and history of observations.
        self.parameter_space = ParameterSpace(parameters)
        self.history = ObservationHistory(self.parameter_space)
        self.use_cuda = use_cuda
        self.initial_safe_trials = initial_safe_trials
        self.seed = seed
        self.mc_samples = mc_samples
        self.num_restarts = num_restarts
        self.raw_samples = raw_samples
        self._torch: Any | None = None
        self._sobol: Any | None = None
        self._torch_ready = False
        self._botorch_ready = False
        self._device = "cpu"

    @property
    def parameters(self) -> tuple[OptimizationParameter, ...]:
        return self.parameter_space.parameters

    @property
    def parameter_names(self) -> tuple[str, ...]:
        return self.parameter_space.names

    @property
    def observations(self) -> list[OptimizationObservation]:
        return self.history.observations

    @property
    def safe_observations(self) -> list[OptimizationObservation]:
        return self.history.safe_observations

    @property
    def best_observation(self) -> OptimizationObservation | None:
        return self.history.best_observation

    def propose_batch(self, batch_size: int) -> list[OptimizationCandidate]:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._require_torch()
        safe_observations = self.safe_observations
        if len(safe_observations) < self.initial_safe_trials:
            return self._propose_sobol_batch(batch_size)
        return self._propose_model_guided_batch(batch_size, safe_observations)

    def record_observations(self, observations: Iterable[OptimizationObservation]) -> None:
        self.history.record(observations)

    def surrogate_grid(
        self,
        *,
        axis_x: str,
        axis_y: str,
        fixed_values: dict[str, float] | None = None,
        grid_size: int = 32,
    ) -> dict[str, Any]:
        safe_observations = self.safe_observations
        if len(safe_observations) < self.initial_safe_trials:
            return {
                "ready": False,
                "message": (
                    f"Need {self.initial_safe_trials} safe observations; "
                    f"have {len(safe_observations)}."
                ),
                "safe_observation_count": len(safe_observations),
                "initial_safe_trials": self.initial_safe_trials,
            }
        if grid_size < 2:
            raise ValueError("grid_size must be at least 2")
        if axis_x == axis_y:
            raise ValueError("axis_x and axis_y must be different")
        if axis_x not in self.parameter_names or axis_y not in self.parameter_names:
            raise ValueError("Surrogate axes must be optimization parameters")

        self._require_botorch()
        fixed = self._fixed_grid_values(fixed_values or {}, {axis_x, axis_y})
        bounds = self._bounds_tensor()
        train_x, train_y = build_training_tensors(
            observations=safe_observations,
            parameter_space=self.parameter_space,
            torch=self._torch,
            tensor_options=self._tensor_options(),
        )
        model = fit_single_task_gp(
            train_x=train_x,
            train_y=train_y,
            bounds=bounds,
            dimension=self.parameter_space.dimension,
        )
        x_values = self._axis_values(axis_x, grid_size)
        y_values = self._axis_values(axis_y, grid_size)
        rows = []
        for y_value in y_values:
            for x_value in x_values:
                row = []
                for parameter in self.parameter_space.parameters:
                    if parameter.name == axis_x:
                        row.append(x_value)
                    elif parameter.name == axis_y:
                        row.append(y_value)
                    else:
                        row.append(fixed[parameter.name])
                rows.append(row)
        query_x = self._torch.tensor(rows, **self._tensor_options())
        objective_mean, objective_variance = predict_posterior_mean_variance(
            model=model,
            query_x=query_x,
            torch=self._torch,
        )
        cost_mean = [-value for value in objective_mean]
        cost_stddev = [max(value, 0.0) ** 0.5 for value in objective_variance]
        return {
            "ready": True,
            "axis_x": axis_x,
            "axis_y": axis_y,
            "fixed_values": fixed,
            "x_values": x_values,
            "y_values": y_values,
            "mean": self._reshape_grid(cost_mean, grid_size),
            "stddev": self._reshape_grid(cost_stddev, grid_size),
            "safe_observation_count": len(safe_observations),
            "initial_safe_trials": self.initial_safe_trials,
        }

    def _propose_sobol_batch(self, batch_size: int) -> list[OptimizationCandidate]:
        unit_candidates = self._sobol.draw(batch_size).to(**self._tensor_options())
        bounds = self._bounds_tensor()
        candidates = bounds[0] + (bounds[1] - bounds[0]) * unit_candidates
        return self.parameter_space.candidates_from_tensor_rows(candidates.detach().cpu())

    def _propose_model_guided_batch(
        self,
        batch_size: int,
        safe_observations: Sequence[OptimizationObservation],
    ) -> list[OptimizationCandidate]:
        self._require_botorch()
        bounds = self._bounds_tensor()
        train_x, train_y = build_training_tensors(
            observations=safe_observations,
            parameter_space=self.parameter_space,
            torch=self._torch,
            tensor_options=self._tensor_options(),
        )
        model = fit_single_task_gp(
            train_x=train_x,
            train_y=train_y,
            bounds=bounds,
            dimension=self.parameter_space.dimension,
        )
        candidates = propose_expected_improvement_batch(
            model=model,
            train_y=train_y,
            bounds=bounds,
            batch_size=batch_size,
            torch=self._torch,
            seed=self.seed,
            mc_samples=self.mc_samples,
            num_restarts=self.num_restarts,
            raw_samples=self.raw_samples,
        )
        return self.parameter_space.candidates_from_tensor_rows(candidates)

    def _require_torch(self) -> None:
        if self._torch_ready:
            return
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError(
                "Torch is required for BotorchBayesianOptimizer Sobol proposals."
            ) from exc

        self._torch = torch
        self._device = torch.device(
            "cuda" if self.use_cuda and torch.cuda.is_available() else "cpu"
        )
        self._sobol = torch.quasirandom.SobolEngine(
            dimension=self.parameter_space.dimension,
            scramble=True,
            seed=self.seed,
        )
        self._torch_ready = True

    def _require_botorch(self) -> None:
        if self._botorch_ready:
            return
        self._require_torch()
        try:
            import botorch  # noqa: F401
            import gpytorch  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "Torch, BoTorch, and GPyTorch are required for BotorchBayesianOptimizer."
            ) from exc
        self._botorch_ready = True

    def _tensor_options(self) -> dict[str, Any]:
        return {"dtype": self._torch.double, "device": self._device}

    def _bounds_tensor(self) -> Any:
        return self._torch.tensor(
            [
                [parameter.bounds[0] for parameter in self.parameter_space.parameters],
                [parameter.bounds[1] for parameter in self.parameter_space.parameters],
            ],
            **self._tensor_options(),
        )

    def _axis_values(self, parameter_name: str, grid_size: int) -> list[float]:
        bounds_by_name = {
            parameter.name: parameter.bounds
            for parameter in self.parameter_space.parameters
        }
        lower, upper = bounds_by_name[parameter_name]
        return [
            lower + (upper - lower) * index / (grid_size - 1)
            for index in range(grid_size)
        ]

    def _fixed_grid_values(
        self,
        requested: dict[str, float],
        axis_names: set[str],
    ) -> dict[str, float]:
        best = self.best_observation
        fixed: dict[str, float] = {}
        validation_candidate: dict[str, float] = {}
        for parameter in self.parameter_space.parameters:
            lower, upper = parameter.bounds
            if parameter.name in axis_names:
                validation_candidate[parameter.name] = (lower + upper) * 0.5
                continue
            value = requested.get(parameter.name)
            if value is None and best is not None:
                value = best.candidate.values.get(parameter.name)
            if value is None:
                value = (lower + upper) * 0.5
            fixed[parameter.name] = float(value)
            validation_candidate[parameter.name] = float(value)
        self.parameter_space.validate_candidate(OptimizationCandidate(validation_candidate))
        return fixed

    @staticmethod
    def _reshape_grid(values: list[float], grid_size: int) -> list[list[float]]:
        return [
            values[row * grid_size:(row + 1) * grid_size]
            for row in range(grid_size)
        ]
