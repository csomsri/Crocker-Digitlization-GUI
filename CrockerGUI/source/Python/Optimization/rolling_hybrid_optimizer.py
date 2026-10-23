"""GA with local BO learning from recent measured trials.

Selection fitness may belong to a learned phenotype (Baldwinian), but the
measurement archive always records the gains that actually ran on the plant.
"""
from dataclasses import asdict, dataclass
import math
from random import Random

from source.Python.Control.NLAPID import PIDGains
from .hybrid_pid_optimizer import HybridConfig, HybridPIDOptimizer, HybridState
from .pid_gain_adapter import PidGainCandidate
from .bayesian_optimizer import BotorchBayesianOptimizer
from .training import build_training_tensors
from .surrogate_model import fit_single_task_gp, predict_posterior_mean_variance
from .acquisition import propose_expected_improvement_batch


class WindowedBayesianOptimizer(BotorchBayesianOptimizer):
    """Bound training and visualization data without discarding the audit log."""
    @property
    def safe_observations(self):
        return super().safe_observations[-self.window_size:]

    @property
    def best_observation(self):
        return min(self.safe_observations, key=lambda o: o.score, default=None)


@dataclass(frozen=True)
class RollingHybridConfig(HybridConfig):
    learning_mode: str = 'lamarckian'
    window_size: int = 32
    local_radius: float = .15
    refinement_probability: float = .5
    lamarckian_probability: float = .5
    refinement_trials: int = 1
    uncertainty_multiplier: float = 1.0
    mc_samples: int = 256
    num_restarts: int = 10
    raw_samples: int = 256

    def validate(self):
        super().validate()
        if self.learning_mode not in {'lamarckian', 'baldwinian', 'mixed'}:
            raise ValueError('Unknown BO learning mode')
        for name in ('window_size', 'refinement_trials', 'mc_samples', 'num_restarts', 'raw_samples'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f'{name} must be a positive integer')
        if self.window_size < self.minimum_distinct:
            raise ValueError('BO window must cover the minimum distinct-point count')
        for name in ('refinement_probability', 'lamarckian_probability'):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f'{name} must be between zero and one')
        if not math.isfinite(self.local_radius) or not 0 < self.local_radius <= 1:
            raise ValueError('Local BO radius must be in (0, 1] of each gain span')
        if not math.isfinite(self.uncertainty_multiplier) or self.uncertainty_multiplier < 0:
            raise ValueError('Prediction uncertainty multiplier must be nonnegative')
        return self


class RollingHybridPIDOptimizer(HybridPIDOptimizer):
    def __init__(self, bounds, seed_gains, config=RollingHybridConfig(), *, proposer=None):
        super().__init__(bounds, seed_gains, config)
        self.optimizer = WindowedBayesianOptimizer(
            list(zip(('kp', 'ki', 'kd'), bounds)), use_cuda=False,
            initial_safe_trials=config.minimum_distinct, seed=config.seed,
            mc_samples=config.mc_samples, num_restarts=config.num_restarts,
            raw_samples=config.raw_samples)
        self.optimizer.window_size = config.window_size
        self._learning_rng = Random(config.seed + 3)
        self._local_proposer = proposer or self._local_model_proposal
        self._parent = self._learned = None
        self._learning_mode = None
        self._refinements_left = 0

    @property
    def recent_results(self):
        return self.safe_results[-self.config.window_size:]

    @property
    def best_result(self):
        if self.reference_drift_detected:
            return None
        # An old selection score is never deployment evidence. Use the latest
        # measured response per vector in the active window, then validate it.
        latest = {r.candidate: r for r in self.recent_results
                  if r.metrics and r.candidate not in self.rejected_validation_candidates}
        return min(latest.values(), key=lambda r: r.score, default=None)

    def candidate_mean(self, candidate):
        # The inherited recorder only needs the recent incumbent's score.
        return next(r.score for r in reversed(self.recent_results) if r.candidate == candidate)

    def readiness(self):
        points = {tuple((getattr(r.candidate, n)-lo)/(hi-lo)
                        for n, (lo, hi) in zip(('kp', 'ki', 'kd'), self.bounds))
                  for r in self.recent_results}
        spans = [max(p[i] for p in points)-min(p[i] for p in points)
                 for i in range(3)] if points else [0]*3
        return (len(points) >= self.config.minimum_distinct and min(spans) >= self.config.coverage,
                len(points), min(spans))

    def _space_filling_candidate(self):
        observed = [tuple((getattr(r.candidate, n)-lo)/(hi-lo)
                    for n, (lo, hi) in zip(('kp', 'ki', 'kd'), self.bounds))
                    for r in self.recent_results]
        points = [tuple(self._exploration_rng.random() for _ in range(3)) for _ in range(64)]
        point = max(points, key=lambda p: min(
            (sum((a-b)**2 for a, b in zip(p, q)) for q in observed), default=math.inf))
        return PidGainCandidate(*(lo+x*(hi-lo) for x, (lo, hi) in zip(point, self.bounds)))

    def _local_bounds(self, center):
        return [(max(lo, getattr(center, n)-self.config.local_radius*(hi-lo)),
                 min(hi, getattr(center, n)+self.config.local_radius*(hi-lo)))
                for n, (lo, hi) in zip(('kp', 'ki', 'kd'), self.bounds)]

    def _local_model_proposal(self, center):
        o = self.optimizer
        o._require_botorch()
        x, y = build_training_tensors(observations=o.safe_observations,
            parameter_space=o.parameter_space, torch=o._torch, tensor_options=o._tensor_options())
        model = fit_single_task_gp(train_x=x, train_y=y, bounds=o._bounds_tensor(), dimension=3)
        local = o._torch.tensor(self._local_bounds(center), **o._tensor_options()).T.contiguous()
        points = propose_expected_improvement_batch(model=model, train_y=y, bounds=local,
            batch_size=1, torch=o._torch, seed=o.seed+len(self.results),
            mc_samples=o.mc_samples, num_restarts=o.num_restarts, raw_samples=o.raw_samples)
        mu, var = predict_posterior_mean_variance(model=model, query_x=points, torch=o._torch)
        candidate = self._to_pid_candidate(o.parameter_space.candidates_from_tensor_rows(points)[0])
        return candidate, -mu[0], math.sqrt(max(0, var[0]))

    def _finish_learning(self):
        parent, learned = self._parent, self._learned
        if self._learning_mode == 'lamarckian':
            g = learned.candidate
            self.ga.population[self.ga.index] = PIDGains(g.kp, g.ki, g.kd)
        # GA history contains selection fitness; BO history contains physical
        # measurements. In Baldwinian mode these deliberately describe different gains.
        self.records[-1]['selection'] = dict(
            mode=self._learning_mode, genotype=asdict(self.ga.population[self.ga.index]),
            parent_gains=asdict(parent.candidate), phenotype=asdict(learned.candidate),
            fitness=learned.score, generation=self.ga.generation, index=self.ga.index)
        self.ga.submit_fitness(learned.score)
        self._parent = self._learned = None
        self._refinements_left = 0

    def propose_batch(self, batch_size):
        if batch_size != 1 or self.pending is not None:
            raise ValueError('Hybrid trials must be sequential with one result per proposal')
        if len(self.results) >= self.config.budget or self.state == HybridState.STOPPED:
            raise RuntimeError('Hybrid budget exhausted or session stopped')
        self.prediction = None
        if self._parent is not None:
            center = self._learned.candidate
            candidate, mu, sigma = self._local_proposer(center)
            if not all(math.isfinite(v) for v in (mu, sigma)) or sigma < 0:
                raise ValueError('Invalid BO prediction')
            if not all(lo <= getattr(candidate, n) <= hi
                       for n, (lo, hi) in zip(('kp', 'ki', 'kd'), self._local_bounds(center))):
                raise ValueError('BO refinement outside its local bounds')
            margin = max(abs(self._learned.score)*self.config.improvement_fraction, 2*self.noise, 1e-9)
            if (candidate != center and
                    mu+self.config.uncertainty_multiplier*sigma < self._learned.score-margin):
                self.prediction = (mu, sigma)
                self.reason = f'Measure {self._learning_mode} BO refinement; GA retains search ownership.'
                return self._pending(candidate, 'BO refinement')
            self._finish_learning()

        if len(self.records) < self.config.baseline_repeats:
            return self._pending(self.seed_gains, 'Baseline')
        if self._reference_remaining or (
                self._since_reference >= self.config.reference_interval and
                self.config.budget-len(self.results) >= self.config.baseline_repeats):
            if not self._reference_remaining:
                self._reference_remaining = self.config.baseline_repeats
                self._reference_batch = []
            return self._pending(self.seed_gains, 'Reference')
        if self._since_exploration >= self.config.exploration_interval:
            return self._pending(self._space_filling_candidate(), 'Exploration')
        self.state = HybridState.GA
        self.reason = 'Evaluate GA individual; every generation remeasures survivors before selection.'
        g = self.ga.current_candidate().gains
        return self._pending(PidGainCandidate(g.kp, g.ki, g.kd), 'GA parent')

    def record_results(self, results):
        results = list(results)
        source = self.pending_source
        super().record_results(results)
        r = results[0]
        self.records[-1]['window_observations'] = len(self.optimizer.safe_observations)
        if source == 'BO refinement':
            self.records[-1]['learning_parent'] = asdict(self._parent.candidate)
            self.records[-1]['learning_mode'] = self._learning_mode
        if not r.safe or self.state == HybridState.STOPPED:
            self._parent = self._learned = None
            self._refinements_left = 0
            return
        if source == 'GA parent':
            self._parent = self._learned = r
            mode = self.config.learning_mode
            self._learning_mode = (('lamarckian' if self._learning_rng.random() <
                self.config.lamarckian_probability else 'baldwinian') if mode == 'mixed' else mode)
            self._refinements_left = self.config.refinement_trials
            if (not self.readiness()[0] or len(self.results) >= self.config.budget or
                    self._learning_rng.random() >= self.config.refinement_probability):
                self._finish_learning()
        elif source == 'BO refinement':
            margin = max(abs(self._learned.score)*self.config.improvement_fraction, 2*self.noise, 1e-9)
            improved = (self.eligible(r) and self._learned.score-r.score > margin)
            self.records[-1]['learning_improved'] = improved
            if improved:
                self._learned = r
            self._refinements_left -= 1
            if (not improved or not self._refinements_left or
                    len(self.results) >= self.config.budget or not self.readiness()[0]):
                self._finish_learning()


def create_hybrid_optimizer(bounds, seed_gains, *, approach='legacy', **settings):
    """Keep legacy defaults and its complete-history handover policy intact."""
    if approach == 'legacy':
        config = HybridConfig(**{k: v for k, v in settings.items() if k in HybridConfig.__dataclass_fields__})
        return HybridPIDOptimizer(bounds, seed_gains, config)
    config = RollingHybridConfig(**{k: v for k, v in settings.items()
                                   if k in RollingHybridConfig.__dataclass_fields__ and k != 'learning_mode'},
                                 learning_mode=approach)
    return RollingHybridPIDOptimizer(bounds, seed_gains, config)
