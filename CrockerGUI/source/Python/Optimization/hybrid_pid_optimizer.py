"""GA-first PID search with measured, paired BO handover. No device or GUI access."""
from collections import defaultdict, deque
from dataclasses import dataclass
import math
from statistics import mean, stdev

from source.Python.Control.NLAPID import PIDGains
from .genetic_optimizer import GAPIDTuner, GainBounds, GATuningConfig
from .pid_gain_adapter import BotorchPidOptimizer, PidGainCandidate
from .training import build_training_tensors
from .surrogate_model import fit_single_task_gp, predict_posterior_mean_variance
from .acquisition import propose_expected_improvement_batch


@dataclass(frozen=True)
class HybridConfig:
    population: int = 6
    baseline_repeats: int = 3
    minimum_distinct: int = 12
    coverage: float = .35
    improvement_fraction: float = .05
    confirmation_pairs: int = 3
    plateau_trials: int = 5
    mutation_probability: float = .25
    mutation_scale: float = .1
    seed: int = 1729
    budget: int = 48

    def validate(self):
        if min(self.population, self.minimum_distinct) < 4 or self.baseline_repeats < 2:
            raise ValueError('Use at least four population/distinct points and two baseline repeats')
        if self.confirmation_pairs < 3 or self.plateau_trials < 1:
            raise ValueError('At least three confirmation pairs and one plateau trial are required')
        if self.budget < self.baseline_repeats + self.population:
            raise ValueError('Budget must cover baseline repeats and one GA generation')
        if not all(math.isfinite(x) and 0 < x <= 1 for x in
                   (self.coverage, self.improvement_fraction)):
            raise ValueError('Coverage and improvement must be fractions in (0, 1]')
        return self


class HybridPIDOptimizer(BotorchPidOptimizer):
    def __init__(self, bounds, seed_gains, config=HybridConfig(), *, proposer=None):
        self.config = config.validate()
        self.bounds = bounds

        super().__init__(*bounds, use_cuda=False, initial_safe_trials=config.minimum_distinct,
                         seed=config.seed)
        self.seed_gains = seed_gains

        self.ga = GAPIDTuner(GainBounds(*bounds), GATuningConfig(
            population_size=config.population, generations=config.budget,
            mutation_probability=config.mutation_probability, mutation_scale=config.mutation_scale,
            seed=config.seed))

        self.ga.initialize(PIDGains(seed_gains.kp, seed_gains.ki, seed_gains.kd))
        
        # Keep the seed and a nearby perturbation; distribute the remaining genes
        # in strata so early GP training is not confined to a local GA cluster.
        self.ga.population[1] = PIDGains(*(max(lo, min(hi, v+self.ga.rng.uniform(-.05,.05)*(hi-lo)))
            for v,(lo,hi) in zip((seed_gains.kp,seed_gains.ki,seed_gains.kd),bounds)))

        count = config.population-2

        axes = []
        for lo,hi in bounds:
            values = [lo+(hi-lo)*(i+self.ga.rng.random())/count for i in range(count)]
            self.ga.rng.shuffle(values)
            axes.append(values)

        self.ga.population[2:] = [PIDGains(*(axis[i] for axis in axes)) for i in range(count)]
        
        self.phase = 'Baseline'
        self.reason = 'Measure repeated baseline responses before GA exploration.'
        self.pending = None
        self.pending_source = None
        self.prediction = None
        self.records = []
        self.events = []
        self._queue = deque()
        self._pairs = []
        self._incumbent = None
        self._challenger = None
        self._last_bo_attempt = -1
        self._bo_stalls = 0
        self._prediction_misses = 0
        self._proposer = proposer or self._model_proposal

    @property
    def best_result(self):
        groups = defaultdict(list)
        for r in self.safe_results:
            if r.candidate not in self.rejected_validation_candidates and r.metrics and not r.metrics.sustained_oscillation:
                groups[r.candidate].append(r)
        if not groups:
            return None
        group = min(groups.values(), key=lambda rs: mean(r.score for r in rs))
        average = mean(r.score for r in group)
        return min(group, key=lambda r: abs(r.score-average))

    def candidate_mean(self, candidate):
        return mean(r.score for r in self.safe_results if r.candidate == candidate)

    @staticmethod
    def beam_error(result):
        value = getattr(result.metrics, 'mean_absolute_error', None)
        return value if value is not None and math.isfinite(value) and value >= 0 else None

    def candidate_error(self, candidate):
        values = [self.beam_error(r) for r in self.safe_results if r.candidate == candidate]
        return mean(values) if values and all(v is not None for v in values) else None

    @property
    def error_noise(self):
        values = [r['beam_mae_nA'] for r in self.records if r['source'] == 'Baseline' and r['safe']]
        return stdev(values) if len(values) >= 2 and all(v is not None for v in values) else math.inf

    def error_gate(self, incumbents, challengers, critical=None):
        """Measured MAE improvement, with its own nA noise/statistical margin."""
        if not incumbents or len(incumbents) != len(challengers) or any(
                v is None or not math.isfinite(v) or v < 0 for v in incumbents+challengers):
            return dict(passed=False, improvement_nA=None, required_nA=None,
                        reason='Missing or invalid measured beam MAE')
        
        differences = [a-b for a,b in zip(incumbents, challengers)]

        margin = max(self.config.improvement_fraction*mean(incumbents), 2*self.error_noise, 1e-9)
        if critical is not None:
            margin = max(margin, critical*stdev(differences)/math.sqrt(len(differences)))

        improvement = mean(differences)

        return dict(passed=improvement > margin, improvement_nA=improvement,
                    required_nA=margin if math.isfinite(margin) else None,
                    reason='Measured beam MAE must improve beyond its relative/noise margin')

    @property
    def noise(self):
        scores = [r['cost'] for r in self.records if r['source'] == 'Baseline' and r['safe']]
        return stdev(scores) if len(scores) >= 2 else 0.0

    def readiness(self):
        points = {tuple((getattr(r.candidate,n)-lo)/(hi-lo) for n,(lo,hi) in
                        zip(('kp','ki','kd'), self.bounds)) for r in self.safe_results}
        spans = [max(p[i] for p in points)-min(p[i] for p in points) for i in range(3)] if points else [0]*3
        return len(points) >= self.config.minimum_distinct and min(spans) >= self.config.coverage, len(points), min(spans)

    def _transition(self, phase, reason):
        self.phase, self.reason = phase, reason
        self.events.append(dict(after_trial=len(self.results), phase=phase, reason=reason))

    def _model_proposal(self):
        """Fit once, propose with qLogEI, and return cost uncertainty at that point."""
        o = self.optimizer
        o._require_botorch()

        x,y = build_training_tensors(observations=o.safe_observations, parameter_space=o.parameter_space,
                                     torch=o._torch, tensor_options=o._tensor_options())
        bounds = o._bounds_tensor()
        model = fit_single_task_gp(train_x=x, train_y=y, bounds=bounds, dimension=3)

        points = propose_expected_improvement_batch(model=model, train_y=y, bounds=bounds,
            batch_size=1, torch=o._torch, seed=o.seed+len(self.results), mc_samples=o.mc_samples,
            num_restarts=o.num_restarts, raw_samples=o.raw_samples)
        
        mu,var = predict_posterior_mean_variance(model=model, query_x=points, torch=o._torch)
        candidate = self._to_pid_candidate(o.parameter_space.candidates_from_tensor_rows(points)[0])

        return candidate, -mu[0], math.sqrt(max(0,var[0]))

    def propose_batch(self, batch_size):
        """Propose a single candidate for sequential hybrid trials. The caller must record the result before proposing again."""
        if batch_size != 1 or self.pending is not None:
            raise ValueError('Hybrid trials must be sequential with one result per proposal')
        
        if len(self.results) >= self.config.budget or self.phase == 'Stopped':
            raise RuntimeError('Hybrid budget exhausted or session stopped')
        
        self.prediction = None

        if len(self.records) < self.config.baseline_repeats:
            candidate, source = self.seed_gains, 'Baseline'
        elif self._queue:
            candidate,source = self._queue.popleft()
        else:
            ready,distinct,coverage = self.readiness()
            generation_boundary = self.ga.index == 0

            attempt = self.phase == 'BO' or (ready and generation_boundary and self.ga.generation != self._last_bo_attempt)

            if attempt:
                self._last_bo_attempt = self.ga.generation
                candidate,mu,sigma = self._proposer()

                if not all(math.isfinite(x) for x in (mu,sigma)) or sigma < 0:
                    raise ValueError('Invalid BO prediction')
                
                if not all(lo <= getattr(candidate,n) <= hi for n,(lo,hi) in zip(('kp','ki','kd'),self.bounds)):
                    raise ValueError('BO proposal outside bounds')
                
                best = self.best_result
                threshold = max(abs(self.candidate_mean(best.candidate))*self.config.improvement_fraction,
                                2*self.noise, 1e-9) if best else math.inf
                # Conservative one-standard-deviation margin is a trial gate,
                # never evidence for handover or a safety guarantee.
                promising = best and mu+sigma < self.candidate_mean(best.candidate) - threshold

                if self.phase == 'BO' or promising:
                    self.prediction = (mu,sigma)

                    source = 'BO' if self.phase == 'BO' else 'BO challenger'
                    if source == 'BO challenger':
                        self._incumbent, self._challenger = best.candidate, candidate
                        self._transition('BO challenger', 'Prediction merits a trial; measured confirmation is still required.')
                    return self._pending(candidate,source)
                
                self.reason = 'BO prediction did not clear the improvement/noise margin; continue GA.'
            elif not ready:
                self.reason = f'GA exploration: {distinct}/{self.config.minimum_distinct} distinct points; minimum gain span {coverage:.0%}.'

            self.phase = 'GA'
            g = self.ga.current_candidate().gains
            candidate,source = PidGainCandidate(g.kp,g.ki,g.kd), 'GA'

        return self._pending(candidate,source)

    def _pending(self,candidate,source):
        self.pending,self.pending_source = candidate,source
        return [candidate]

    @staticmethod
    def eligible(result):
        m = result.metrics
        return bool(result.safe and m and m.settled and not m.sustained_oscillation
                    and m.steady_state_error <= m.tolerance)

    def record_results(self, results):
        results = list(results)

        if len(results) != 1 or results[0].candidate != self.pending:
            raise ValueError('Result does not match the outstanding hybrid proposal')
        r = results[0]

        source = self.pending_source
        previous_best = self.candidate_mean(self.best_result.candidate) if self.best_result else math.inf
        super().record_results(results)
        self.records.append(dict(trial=len(self.results), source=source, phase=self.phase,
            kp=r.candidate.kp, ki=r.candidate.ki, kd=r.candidate.kd, cost=r.score if r.safe else None,
            safe=r.safe, settled=bool(r.metrics and r.metrics.settled),
            beam_mae_nA=self.beam_error(r) if r.safe else None,
            steady_error_nA=r.metrics.steady_state_error if r.safe and r.metrics else None,
            prediction=self.prediction[0] if self.prediction else None,
            prediction_std=self.prediction[1] if self.prediction else None,
            reason=r.termination_reason))

        self.pending = self.pending_source = None
        if not r.safe:
            self._transition('Stopped', 'Trial fault or incomplete response; no optimizer fallback.')
            self._queue.clear()
            return
        if source == 'GA':
            self.ga.submit_fitness(r.score)
        elif source == 'Baseline' and len(self.records) == self.config.baseline_repeats:
            self._transition('GA', f'Baseline measured; cost noise standard deviation {self.noise:.4g}.')
        elif source == 'BO challenger':
            incumbent_cost = self.candidate_mean(self._incumbent)
            margin = max(abs(incumbent_cost)*self.config.improvement_fraction, 2*self.noise, 1e-9)

            error_gate = self.error_gate([self.candidate_error(self._incumbent)], [self.beam_error(r)])
            self.records[-1]['beam_error_gate'] = error_gate
            if self.eligible(r) and incumbent_cost-r.score > margin and error_gate['passed']:
                self._pairs = []
                for i in range(self.config.confirmation_pairs):
                    pair = [(self._incumbent,'Confirm incumbent'),(self._challenger,'Confirm BO')]
                    self._queue.extend(pair if i%2 == 0 else reversed(pair))
                self._transition('Confirmation', 'Repeat both candidates in alternating order before handover.')
            else:
                self._transition('GA', 'BO challenger failed cost, measured beam-error improvement, or response checks.')

        elif source.startswith('Confirm'):
            self._pairs.append((source,r))

            if not self._queue:
                incumbents = [x.score for s,x in self._pairs if s == 'Confirm incumbent']
                challengers = [x.score for s,x in self._pairs if s == 'Confirm BO']

                differences = [a-b for a,b in zip(incumbents,challengers)]
                # Two-sided 95% Student-t critical values (small repeat counts).
                n = len(differences)
                critical = {2:12.706,3:4.303,4:3.182,5:2.776,6:2.571,7:2.447,8:2.365,9:2.306,10:2.262}.get(n,2.262)

                margin = max(abs(mean(incumbents))*self.config.improvement_fraction,
                             critical*stdev(differences)/math.sqrt(n),2*self.noise,1e-9)
                stable = all(self.eligible(x) for s,x in self._pairs if s == 'Confirm BO')
                error_gate = self.error_gate(
                    [self.beam_error(x) for s,x in self._pairs if s == 'Confirm incumbent'],
                    [self.beam_error(x) for s,x in self._pairs if s == 'Confirm BO'], critical)
                self.records[-1]['beam_error_gate'] = error_gate
                if stable and mean(differences) > margin and error_gate['passed']:
                    self._bo_stalls = self._prediction_misses = 0
                    self._transition('BO', f'Paired cost improvement {mean(differences):.4g} > {margin:.4g}; '
                        f'beam MAE improvement {error_gate["improvement_nA"]:.4g} nA > '
                        f'{error_gate["required_nA"]:.4g} nA; response checks passed. BO takes over.')

                else:
                    self._transition('GA', 'Paired confirmation failed cost, measured beam-error improvement/noise, or response checks.')
        elif source == 'BO':
            improved = self.eligible(r) and previous_best-r.score > max(abs(previous_best)*self.config.improvement_fraction,2*self.noise,1e-9)
            self._bo_stalls = 0 if improved else self._bo_stalls+1

            mu,sigma = self.prediction
            missed = abs(r.score-mu) > max(3*sigma,2*self.noise,abs(mu)*self.config.improvement_fraction,1e-9)

            self._prediction_misses = self._prediction_misses+1 if missed else 0

            if self._bo_stalls >= self.config.plateau_trials or self._prediction_misses >= 3:
                self._transition('GA', 'BO plateau or three unreliable predictions; run another GA generation.')

                # BO's best measured gains seed the fallback population.
                best = self.best_result.candidate

                self.ga.population[0] = PIDGains(best.kp,best.ki,best.kd)
                self._last_bo_attempt = self.ga.generation
