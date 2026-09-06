"""Acquisition functions and candidate selection."""

from __future__ import annotations

from typing import Any


def propose_expected_improvement_batch(
    *,
    model: Any,
    train_y: Any,
    bounds: Any,
    batch_size: int,
    torch: Any,
    seed: int,
    mc_samples: int,
    num_restarts: int,
    raw_samples: int,
) -> Any:
    from botorch.acquisition.logei import qLogExpectedImprovement
    from botorch.optim import optimize_acqf
    from botorch.sampling.normal import SobolQMCNormalSampler

    sampler = SobolQMCNormalSampler(
        sample_shape=torch.Size([mc_samples]),
        seed=seed,
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
        num_restarts=num_restarts,
        raw_samples=raw_samples,
        options={"batch_limit": 5, "maxiter": 200},
        sequential=batch_size > 1,
    )
    return candidates.detach().cpu()
