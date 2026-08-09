from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class PidGainCandidate:
    kp: float
    ki: float
    kd: float


@dataclass(frozen=True)
class PidTrialResult:
    """One completed closed-loop experiment.

    ``score`` is a cost (smaller is better). Unsafe experiments are retained in
    the history for audit purposes, but are never used to train the performance
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
    """Propose PID gains with a Sobol-initialized BoTorch optimization loop.

    This class deliberately does not run the plant. The caller must apply each
    candidate through the normal control allocation, limits, interlocks, and
    operator-approval path, measure the response, and call :meth:`record_results`.
    BoTorch maximizes ``-score`` because PID response scores are costs.
    """

    _DIMENSION = 3

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
        self.kp_bounds = self._validate_bounds("Kp", kp_bounds)
        self.ki_bounds = self._validate_bounds("Ki", ki_bounds)
        self.kd_bounds = self._validate_bounds("Kd", kd_bounds)
        if initial_safe_trials < 1:
            raise ValueError("initial_safe_trials must be positive")
        if mc_samples < 1 or num_restarts < 1 or raw_samples < 1:
            raise ValueError("BoTorch sampling and restart counts must be positive")

        self.use_cuda = use_cuda
        self.initial_safe_trials = initial_safe_trials
        self.seed = seed
        self.mc_samples = mc_samples
        self.num_restarts = num_restarts
        self.raw_samples = raw_samples
        self.results: list[PidTrialResult] = []
        self._torch: Any | None = None
        self._sobol: Any | None = None
        self._botorch_ready = False
        self._device = "cpu"

    @property
    def safe_results(self) -> list[PidTrialResult]:
        return [result for result in self.results if result.safe]

    @property
    def best_result(self) -> PidTrialResult | None:
        safe = self.safe_results
        return min(safe, key=lambda result: result.score) if safe else None

    def propose_batch(self, batch_size: int) -> list[PidGainCandidate]:
        """Return ``batch_size`` gains for the caller to evaluate.

        Space-filling Sobol points are returned until enough safe observations
        exist to fit a GP. Subsequent batches maximize qLogExpectedImprovement.
        """
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._require_botorch()

        safe_results = self.safe_results
        if len(safe_results) < self.initial_safe_trials:
            unit_candidates = self._sobol.draw(batch_size).to(**self._tensor_options())
            return self._from_unit_cube(unit_candidates)

        torch = self._torch
        from botorch.acquisition.logei import qLogExpectedImprovement
        from botorch.fit import fit_gpytorch_mll
        from botorch.models import SingleTaskGP
        from botorch.models.transforms import Normalize, Standardize
        from botorch.optim import optimize_acqf
        from botorch.sampling.normal import SobolQMCNormalSampler
        from gpytorch.mlls import ExactMarginalLogLikelihood

        train_x = torch.tensor(
            [[r.candidate.kp, r.candidate.ki, r.candidate.kd] for r in safe_results],
            **self._tensor_options(),
        )
        # BoTorch maximizes objectives; the trial score is a cost.
        train_y = torch.tensor(
            [[-r.score] for r in safe_results], **self._tensor_options()
        )
        bounds = self._bounds_tensor()
        model = SingleTaskGP(
            train_X=train_x,
            train_Y=train_y,
            input_transform=Normalize(d=self._DIMENSION, bounds=bounds),
            outcome_transform=Standardize(m=1),
        )
        mll = ExactMarginalLogLikelihood(model.likelihood, model)
        fit_gpytorch_mll(mll)
        sampler = SobolQMCNormalSampler(
            sample_shape=torch.Size([self.mc_samples]), seed=self.seed
        )
        acquisition = qLogExpectedImprovement(
            model=model,
            best_f=train_y.max(),
            sampler=sampler,
        )
        candidates, _ = optimize_acqf(
            acq_function=acquisition,
            bounds=bounds,
            q=batch_size,
            num_restarts=self.num_restarts,
            raw_samples=self.raw_samples,
            options={"batch_limit": 5, "maxiter": 200},
            sequential=batch_size > 1,
        )
        return self._to_candidates(candidates.detach().cpu())

    def record_results(self, results: Iterable[PidTrialResult]) -> None:
        validated = list(results)
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
            self._validate_candidate(result.candidate)
        self.results.extend(validated)

    def _require_botorch(self) -> None:
        if self._botorch_ready:
            return
        try:
            import torch
            import botorch  # noqa: F401
            import gpytorch  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "Torch, BoTorch, and GPyTorch are required for BotorchPidOptimizer."
            ) from exc

        self._torch = torch
        self._device = torch.device(
            "cuda" if self.use_cuda and torch.cuda.is_available() else "cpu"
        )
        self._sobol = torch.quasirandom.SobolEngine(
            dimension=self._DIMENSION, scramble=True, seed=self.seed
        )
        self._botorch_ready = True

    def _tensor_options(self) -> dict[str, Any]:
        return {"dtype": self._torch.double, "device": self._device}

    def _bounds_tensor(self) -> Any:
        return self._torch.tensor(
            [
                [self.kp_bounds[0], self.ki_bounds[0], self.kd_bounds[0]],
                [self.kp_bounds[1], self.ki_bounds[1], self.kd_bounds[1]],
            ],
            **self._tensor_options(),
        )

    def _from_unit_cube(self, unit_candidates: Any) -> list[PidGainCandidate]:
        bounds = self._bounds_tensor()
        candidates = bounds[0] + (bounds[1] - bounds[0]) * unit_candidates
        return self._to_candidates(candidates.detach().cpu())

    @staticmethod
    def _to_candidates(values: Any) -> list[PidGainCandidate]:
        return [PidGainCandidate(*(float(value) for value in row)) for row in values]

    def _validate_candidate(self, candidate: PidGainCandidate) -> None:
        for name, value, bounds in (
            ("Kp", candidate.kp, self.kp_bounds),
            ("Ki", candidate.ki, self.ki_bounds),
            ("Kd", candidate.kd, self.kd_bounds),
        ):
            if not bounds[0] <= value <= bounds[1]:
                raise ValueError(f"{name}={value} lies outside bounds {bounds}")

    @staticmethod
    def _validate_bounds(name: str, bounds: tuple[float, float]) -> tuple[float, float]:
        if len(bounds) != 2:
            raise ValueError(f"{name} bounds must contain exactly two values")
        lower, upper = (float(bounds[0]), float(bounds[1]))
        if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
            raise ValueError(f"{name} bounds must be finite and strictly increasing")
        return lower, upper
