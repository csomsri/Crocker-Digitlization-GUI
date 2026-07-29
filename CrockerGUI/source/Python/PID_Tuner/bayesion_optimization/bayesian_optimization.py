from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PidGainCandidate:
    kp: float
    ki: float
    kd: float


@dataclass(frozen=True)
class PidTrialResult:
    candidate: PidGainCandidate
    score: float
    settling_time: float
    overshoot: float
    steady_state_error: float
    control_effort: float
    safe: bool


class BotorchPidOptimizer:
    """Batch Bayesian Optimization scaffold for PID gain tuning.

    This class is the intended home for the real Torch/BoTorch optimizer. It
    should propose batches of PID gain candidates, then consume scored trial
    results from the GUI-controlled hardware trial runner.
    """

    def __init__(
        self,
        kp_bounds: tuple[float, float],
        ki_bounds: tuple[float, float],
        kd_bounds: tuple[float, float],
        use_cuda: bool = True,
    ) -> None:
        self.kp_bounds = kp_bounds
        self.ki_bounds = ki_bounds
        self.kd_bounds = kd_bounds
        self.use_cuda = use_cuda
        self.results: list[PidTrialResult] = []
        self._torch: Any | None = None
        self._botorch_ready = False
        self._device = "cpu"

    def propose_batch(self, batch_size: int) -> list[PidGainCandidate]:
        """Return a batch of PID gains.

        Once BoTorch is wired in, this should fit/update a GP model and use a
        batch acquisition function such as qLogExpectedImprovement. For now it
        raises clearly instead of pretending to be a working BO optimizer.
        """
        self._require_botorch()
        raise NotImplementedError("BoTorch PID gain proposal is not implemented yet.")

    def record_results(self, results: list[PidTrialResult]) -> None:
        self.results.extend(results)

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
        if self.use_cuda and torch.cuda.is_available():
            self._device = "cuda"
        self._botorch_ready = True
