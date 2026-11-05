"""Sequential noisy beam maximization, isolated from the PID optimizer defaults."""
from __future__ import annotations

import math

from .bayesian_optimizer import BotorchBayesianOptimizer
from .training import build_training_tensors


class TrimCoilBayesianOptimizer(BotorchBayesianOptimizer):
    def propose_batch(self, batch_size=1):
        if batch_size != 1:
            raise ValueError('Trim-coil experiments must be sequential (q=1)')
        self._require_torch()
        distinct = {tuple(self.parameter_space.candidate_vector(o.candidate)) for o in self.safe_observations}
        if len(distinct) < self.initial_safe_trials:
            for _ in range(100):
                proposal = self._propose_sobol_batch(1)
                if tuple(self.parameter_space.candidate_vector(proposal[0])) not in distinct:
                    return proposal
            raise RuntimeError('Could not generate a distinct initial setting')
        return self._propose_model_guided_batch(1, self.safe_observations)

    def _propose_model_guided_batch(self, batch_size, safe_observations):
        self._require_botorch()
        from botorch.acquisition.logei import qLogNoisyExpectedImprovement
        from botorch.fit import fit_gpytorch_mll
        from botorch.models import SingleTaskGP
        from botorch.models.transforms import Normalize, Standardize
        from botorch.optim import optimize_acqf
        from botorch.sampling.normal import SobolQMCNormalSampler
        from gpytorch.mlls import ExactMarginalLogLikelihood

        x, y = build_training_tensors(observations=safe_observations,
            parameter_space=self.parameter_space, torch=self._torch, tensor_options=self._tensor_options())
        variances = [(o.metadata or {}).get('mean_variance_nA2') for o in safe_observations]
        # Never fabricate noise for partially characterized observations.
        if any(v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0) for v in variances):
            raise ValueError('Beam mean variances must be finite and nonnegative')
        kwargs = {}
        if all(v is not None for v in variances):
            kwargs['train_Yvar'] = self._torch.tensor([[max(v, 1e-8)] for v in variances], **self._tensor_options())
        bounds = self._bounds_tensor()
        model = SingleTaskGP(train_X=x, train_Y=y, input_transform=Normalize(d=x.shape[-1], bounds=bounds),
                             outcome_transform=Standardize(m=1), **kwargs)
        fit_gpytorch_mll(ExactMarginalLogLikelihood(model.likelihood, model))
        acquisition = qLogNoisyExpectedImprovement(model=model, X_baseline=x,
            sampler=SobolQMCNormalSampler(sample_shape=self._torch.Size([self.mc_samples]), seed=self.seed))
        # optimize_acqf uses random initialization; fork preserves caller RNG state.
        with self._torch.random.fork_rng(devices=[] if self._device.type == 'cpu' else [self._device.index]):
            self._torch.manual_seed(self.seed + len(safe_observations))
            candidates, _ = optimize_acqf(acquisition, bounds=bounds, q=1,
                num_restarts=self.num_restarts, raw_samples=self.raw_samples)
        return self.parameter_space.candidates_from_tensor_rows(candidates.detach().cpu())
