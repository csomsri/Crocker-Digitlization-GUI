"""Surrogate model construction and fitting."""

from __future__ import annotations

from typing import Any


def fit_single_task_gp(
    *,
    train_x: Any,
    train_y: Any,
    bounds: Any,
    dimension: int,
) -> Any:
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from botorch.models.transforms import Normalize, Standardize
    from gpytorch.mlls import ExactMarginalLogLikelihood

    model = SingleTaskGP(
        train_X=train_x,
        train_Y=train_y,
        input_transform=Normalize(d=dimension, bounds=bounds),
        outcome_transform=Standardize(m=1),
    )
    mll = ExactMarginalLogLikelihood(model.likelihood, model)
    fit_gpytorch_mll(mll)
    return model


def predict_posterior_mean_variance(
    *,
    model: Any,
    query_x: Any,
    torch: Any,
) -> tuple[list[float], list[float]]:
    model.eval()
    with torch.no_grad():
        posterior = model.posterior(query_x)
        mean = posterior.mean.detach().cpu().reshape(-1)
        variance = posterior.variance.detach().cpu().reshape(-1)
    return [float(value) for value in mean], [float(value) for value in variance]
