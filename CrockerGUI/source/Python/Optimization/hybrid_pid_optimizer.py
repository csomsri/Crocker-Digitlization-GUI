"""
    GA-first PID search with measured, paired BO handover. No device or GUI access.

    Author(s): Chotrawit Benko and Samar Ahuja

    Date: 09/25/2026
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from enum import StrEnum
import math
from random import Random
from statistics import mean, stdev

from source.Python.Control.NLAPID import PIDGains
from .genetic_optimizer import GAPIDTuner, GainBounds, GATuningConfig
from .pid_gain_adapter import BotorchPidOptimizer, PidGainCandidate
from .training import build_training_tensors
from .surrogate_model import fit_single_task_gp, predict_posterior_mean_variance
from .acquisition import propose_expected_improvement_batch


class HybridState(StrEnum):
    """
        Search states; values remain readable in UI, JSON and database records.

        Reference and exploration are trial sources within GA or BO, not states.
        Recovery and final validation belong to the page's execution workflow.
    """

    BASELINE     = 'Baseline'                # Repeat starting gains to estimate measurement noise.
    GA           = 'GA'                      # Evolve gains and collect diverse measured responses for BO.
    CHALLENGER   = 'BO challenger'           # Measure a promising BO proposal before confirmation.
    CONFIRMATION = 'Confirmation'            # Compare incumbent and challenger in paired trials.
    BO           = 'BO'                      # Use BO proposals until progress stalls or predictions become unreliable.
    STOPPED      = 'Stopped'                 # Reject further proposals after a fault or detected drift.


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

    reference_interval: int = 8
    exploration_interval: int = 5
    drift_fraction: float = .2

    # Validate the configuration parameters to ensure they are within acceptable ranges before use.
    def validate(self):
        # Validate the configuration parameters to ensure they are within acceptable ranges.
        if self.reference_interval < 1 or self.exploration_interval < 1:  
            raise ValueError('Reference and exploration intervals must be positive')
        # Ensure that the drift fraction is a valid finite number within the expected range.
        if not math.isfinite(self.drift_fraction) or not 0 < self.drift_fraction <= 1:
            raise ValueError('Drift fraction must be in (0, 1]')
        # Ensure that the population and baseline repeats meet minimum requirements.
        if min(self.population, self.minimum_distinct) < 4 or self.baseline_repeats < 2:
            raise ValueError('Use at least four population/distinct points and two baseline repeats')
        # Ensure that the confirmation pairs and plateau trials meet minimum requirements.
        if self.confirmation_pairs < 3 or self.plateau_trials < 1:
            raise ValueError('At least three confirmation pairs and one plateau trial are required')
        # Ensure that the budget is sufficient to cover baseline repeats and at least one GA generation.
        if self.budget < self.baseline_repeats + self.population:
            raise ValueError('Budget must cover baseline repeats and one GA generation')
        # Ensure that coverage and improvement fraction are valid fractions within (0, 1].
        if not all(math.isfinite(x) and 0 < x <= 1 for x in 
                   (self.coverage, self.improvement_fraction)):
            raise ValueError('Coverage and improvement must be fractions in (0, 1]')
        # If all validations pass, return the validated configuration.
        return self


# Hybrid PID optimizer that combines genetic algorithm (GA) tuning with Bayesian optimization (BoTorch).
class HybridPIDOptimizer(BotorchPidOptimizer):
    def __init__(self, bounds, seed_gains, config=HybridConfig(), *, proposer=None):
        self.config = config.validate()
        self.bounds = bounds

        super().__init__(*bounds, use_cuda=False, initial_safe_trials=config.minimum_distinct,
                         seed=config.seed)
        self.seed_gains = seed_gains

        # Initialize the GA tuner with the specified bounds and configuration.
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

        # Initialize the state, reason, and various internal state variables for the hybrid optimizer.
        self.state = HybridState.BASELINE
        self.reason = 'Measure repeated baseline responses before GA exploration.'

        self.pending = None                                                                             # Candidate currently being evaluated.
        self.pending_source = None                                                                      # Source of the currently evaluated candidate.

        self.prediction = None                                                                          # Predicted performance of the current candidate.
        self.records = []                                                                               # Historical evaluation records.

        self.events = []                                                                                # Event log for the optimizer.
        self._queue = deque()                                                                           # Internal queue for managing optimizer tasks.

        self._pairs = []                                                                                # Pairs of candidates for comparison.
        self._incumbent = None                                                                          # Current best candidate.

        self._challenger = None                                                                         # Candidate challenging the incumbent.
        self._last_bo_attempt = -1                                                                      # Iteration of the last Bayesian optimization attempt.

        self._bo_stalls = 0                                                                             # Count of consecutive BO stalls.
        self._prediction_misses = 0                                                                     # Count of prediction misses.
        self._proposer = proposer or self._model_proposal                                               # Function to propose new candidates.

        # Independent random streams: confirmation does not change GA evolution.
        self._pair_rng = Random(config.seed+1)
        self._exploration_rng = Random(config.seed+2)

        self._since_reference = self._since_exploration = 0                                             # Counters for iterations since last reference and exploration steps.
        self._reference_remaining = 0                                                                   # Remaining reference evaluations in the current batch.

        self._reference_batch = []                                                                      # Current batch of reference evaluations.
        self._reference_noise = self._reference_error_noise = 0.0                                       # Noise parameters for reference evaluations.

        self.feasibility_observations = []                                                              # Observations related to feasibility checks.
        self.reference_drift_detected = False                                                           # Flag indicating if reference drift has been detected.


    # Initial State, before BO have enough observations to make informed proposals.
    def _space_filling_candidate(self):
        """Choose the most distant of 64 uniform points, using locations only."""
        observed = [tuple((getattr(r.candidate,n)-lo)/(hi-lo)
                    for n,(lo,hi) in zip(('kp','ki','kd'),self.bounds)) for r in self.safe_results]

        points = [tuple(self._exploration_rng.random() for _ in range(3)) for _ in range(64)]

        point = max(points, key=lambda p: min(sum((a-b)**2 for a,b in zip(p,q))
                                             for q in observed))


        return PidGainCandidate(*(lo+x*(hi-lo) for x,(lo,hi) in zip(point,self.bounds)))


    # Check if the reference response has drifted significantly.
    def _check_reference_drift(self):
        baseline = [r for r in self.records if r['source']=='Baseline' and r['safe']]
        details = {}

        for key in ('cost', 'beam_mae_nA'):
            initial = [r[key] for r in baseline]
            current = [r[key] for r in self._reference_batch]

            if any(v is None or not math.isfinite(v) for v in initial+current):
                details[key] = dict(drift=True, reason='Missing reference metric')
                continue

            threshold = max(self.config.drift_fraction * abs(mean(initial)),
                            3 * stdev(initial) * math.sqrt( (1 / len(initial)) + (1 / len(current))), 1e-9)
            shift = abs(mean(current) - mean(initial))
            details[key] = dict(drift=shift>threshold, shift=shift, threshold=threshold)

        self.records[-1]['reference_check'] = details

        if any(d['drift'] for d in details.values()):
            self.reference_drift_detected = True
            self._transition(HybridState.STOPPED, 'Reference response drift detected; start a new session before comparing more gains.')
        else:
            self._reference_noise = stdev(r['cost'] for r in self._reference_batch)
            self._reference_error_noise = stdev(r['beam_mae_nA'] for r in self._reference_batch)
            self._transition(self.state, 'Reference response check passed; continue search.')


    @property
    def best_result(self):
        """
            Get the best result based on the current safe and validated candidates.

            Args:
                Self

            Returns:
                Best result based on the current safe and validated candidates.
        """
        if self.reference_drift_detected:
            return None
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
        """
            Get the mean absolute error of the beam for the given result.

            Args:
                result: The result object containing beam metrics.

            Returns:
                The mean absolute error of the beam if available and valid, otherwise None.
        """

        value = getattr(result.metrics, 'mean_absolute_error', None)
        return value if value is not None and math.isfinite(value) and value >= 0 else None

    def candidate_error(self, candidate):
        """
            Get the mean absolute error of the beam for the given candidate.

            Args:
                candidate: The candidate for which to calculate the mean beam error.

            Returns:
                The mean absolute error of the beam if available and valid, otherwise None.
        """

        values = [self.beam_error(r) for r in self.safe_results if r.candidate == candidate]
        return mean(values) if values and all(v is not None for v in values) else None

    @property
    def error_noise(self):
        """
            Get the noise level of the beam MAE for the baseline records.

            Returns:
                The noise level of the beam MAE, considering both the standard deviation of the baseline records and the reference error noise.
        """

        values = [r['beam_mae_nA'] for r in self.records if r['source'] == 'Baseline' and r['safe']]
        return max(stdev(values), self._reference_error_noise) if len(values) >= 2 and all(v is not None for v in values) else math.inf

    def error_gate(self, incumbents, challengers, critical=None):
        """
            Measured MAE improvement, with its own nA noise/statistical margin.

            Args:
                incumbents: List of incumbent beam MAE values.
                challengers: List of challenger beam MAE values.
                critical: Optional critical value for statistical margin.

            Returns:
                A dictionary indicating whether the improvement passed, the measured improvement, the required improvement, and the reason.
        """

        # If its not the best or the length of the incumbents and challengers lists do not match, or if any values are invalid, return early.
        if not incumbents or len(incumbents) != len(challengers) or any(
                v is None or not math.isfinite(v) or v < 0 for v in incumbents+challengers):
            return dict(passed=False, improvement_nA=None, required_nA=None,
                        reason='Missing or invalid measured beam MAE')

        differences = [a - b for a,b in zip(incumbents, challengers)]

        margin = max(self.config.improvement_fraction*mean(incumbents), 2*self.error_noise, 1e-9)

        if critical is not None:
            margin = max(margin, critical*stdev(differences)/math.sqrt(len(differences)))

        improvement = mean(differences)

        return dict(passed=improvement > margin, improvement_nA=improvement,
                    required_nA=margin if math.isfinite(margin) else None,
                    reason='Measured beam MAE must improve beyond its relative/noise margin')

    @property
    def noise(self):
        """
            Get the noise level of the baseline measurements.

            Returns:
                The noise level of the baseline measurements as a float.
        """
        scores = [r['cost'] for r in self.records if r['source'] == 'Baseline' and r['safe']]

        return max(stdev(scores), self._reference_noise) if len(scores) >= 2 else 0.0


    

    def readiness(self):
        """
            Assess the readiness of the optimizer based on the coverage and distinct points criteria.

            Returns:
                A tuple containing a boolean indicating readiness, the number of distinct points, and the minimum span across the parameter space.
        """
        points = {tuple((getattr(r.candidate,n)-lo)/(hi-lo) for n,(lo,hi) in
                        zip(('kp','ki','kd'), self.bounds)) for r in self.safe_results}

        spans = [max(p[i] for p in points)-min(p[i] for p in points) for i in range(3)] if points else [0] * 3

        return len(points) >= self.config.minimum_distinct and min(spans) >= self.config.coverage, len(points), min(spans)




    def _transition(self, state: HybridState | str, reason: str):
        """
            Transition the optimizer to a new state with a given reason.

            Args:
                state: The new state to transition to.
                reason: The reason for the state transition.

            Returns:
                None. The method updates the optimizer's state and records the transition event.
        """
        self.state, self.reason = HybridState(state), reason
        self.events.append(dict(after_trial=len(self.results), state=self.state, reason=reason))


    def _model_proposal(self):
        """
            Fit once, propose with qLogEI, and return cost uncertainty at that point.

            Args:
                None.

            Returns:
                A tuple containing the proposed candidate, the predicted mean cost, and the predicted cost uncertainty.
        """
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
        """
            Propose a single candidate for sequential hybrid trials. The caller must record the result before proposing again.

            Args:
                batch_size: The number of candidates to propose (must be 1 for sequential hybrid trials).

            Returns:
                A tuple containing the proposed candidate and its source.
        """
        if batch_size != 1 or self.pending is not None:
            raise ValueError('Hybrid trials must be sequential with one result per proposal')

        if len(self.results) >= self.config.budget or self.state == HybridState.STOPPED:
            raise RuntimeError('Hybrid budget exhausted or session stopped')

        self.prediction = None

        # Determine which type of candidate to propose based on the current state and configuration.
        if len(self.records) < self.config.baseline_repeats:
            candidate, source = self.seed_gains, 'Baseline'
        elif self._queue:
            candidate,source = self._queue.popleft()
        
        elif self._reference_remaining or (
                self._since_reference >= self.config.reference_interval
                and self.config.budget-len(self.results) >= self.config.baseline_repeats):
            
            if not self._reference_remaining:
                self._reference_remaining = self.config.baseline_repeats
                self._reference_batch = []

            candidate,source = self.seed_gains,'Reference'
        
        elif self._since_exploration >= self.config.exploration_interval:
            candidate,source = self._space_filling_candidate(),'Exploration'
        
        else:
            ready,distinct,coverage = self.readiness()
            generation_boundary = self.ga.index == 0

            attempt = self.state == HybridState.BO or (ready and generation_boundary and self.ga.generation != self._last_bo_attempt)

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

                if self.state == HybridState.BO or promising:
                    self.prediction = (mu,sigma)

                    source = 'BO' if self.state == HybridState.BO else 'BO challenger'
                    if source == 'BO challenger':
                        self._incumbent, self._challenger = best.candidate, candidate
                        self._transition(HybridState.CHALLENGER, 'Prediction merits a trial; measured confirmation is still required.')
                    return self._pending(candidate,source)

                self.reason = 'BO prediction did not clear the improvement/noise margin; continue GA.'
            elif not ready:
                self.reason = f'GA exploration: {distinct}/{self.config.minimum_distinct} distinct points; minimum gain span {coverage:.0%}.'

            self.state = HybridState.GA
            g = self.ga.current_candidate().gains
            candidate,source = PidGainCandidate(g.kp,g.ki,g.kd), 'GA'

        return self._pending(candidate,source)

    def _pending(self,candidate,source):
        """
            Record the pending candidate and its source.

            Args:
                candidate: The proposed PID gain candidate.
                source: The source of the candidate ('GA', 'BO', or 'BO challenger').

            Returns:
                A list containing the pending candidate.
        """
        self.pending,self.pending_source = candidate,source
        return [candidate]

    @staticmethod
    def eligible(result):
        """
            Determine if a given result is eligible based on safety and performance metrics.

            Args:
                result: The result object containing metrics and safety information.

            Returns:
                True if the result is eligible, False otherwise.
        """
        m = result.metrics
        return bool(result.safe and m and m.settled and not m.sustained_oscillation
                    and m.steady_state_error <= m.tolerance)

    def record_results(self, results):
        """
            Record the results of a trial for the hybrid PID optimizer.

            Args:
                results: A list containing the result object for the pending candidate.

            Raises:
                ValueError: If the result does not match the outstanding pending candidate.
        """

        results = list(results)

        if len(results) != 1 or results[0].candidate != self.pending:
            raise ValueError('Result does not match the outstanding hybrid proposal')
        r = results[0]

        source = self.pending_source
        previous_best = self.candidate_mean(self.best_result.candidate) if self.best_result else math.inf

        super().record_results(results)
        self.feasibility_observations.append(dict(candidate=dict(kp=r.candidate.kp, ki=r.candidate.ki, kd=r.candidate.kd), valid=r.safe,
                                                  reason=r.termination_reason, source=source))
        
        self.records.append(dict(trial=len(self.results), source=source, state=self.state,
            kp=r.candidate.kp, ki=r.candidate.ki, kd=r.candidate.kd, cost=r.score if r.safe else None,
            safe=r.safe, settled=bool(r.metrics and r.metrics.settled),

            beam_mae_nA=self.beam_error(r) if r.safe else None,
            steady_error_nA=r.metrics.steady_state_error if r.safe and r.metrics else None,

            prediction=self.prediction[0] if self.prediction else None,
            prediction_std=self.prediction[1] if self.prediction else None,

            reason=r.termination_reason))
        
        self.records[-1]['valid_response'] = r.safe

        self.pending = self.pending_source = None

        if not r.safe:
            self._transition(HybridState.STOPPED, 'Trial fault or incomplete response; no optimizer fallback.')
            self._queue.clear()
            return
        
        if source not in ('Baseline','Reference'):
            self._since_reference += 1
            self._since_exploration += 1

        if source == 'Reference':
            self._reference_batch.append(self.records[-1])
            self._reference_remaining -= 1

            if not self._reference_remaining:
                self._since_reference = 0
                self._check_reference_drift()
                
            return
        if source == 'Exploration':
            self._since_exploration = 0
            return  # Observations train BO, but must not consume a GA population slot.
        if source == 'GA':
            self.ga.submit_fitness(r.score)
            
        elif source == 'Baseline' and len(self.records) == self.config.baseline_repeats:
            self._transition(HybridState.GA, f'Baseline measured; cost noise standard deviation {self.noise:.4g}.')

        elif source == 'BO challenger':
            incumbent_cost = self.candidate_mean(self._incumbent)
            margin = max(abs(incumbent_cost)*self.config.improvement_fraction, 2*self.noise, 1e-9)

            error_gate = self.error_gate([self.candidate_error(self._incumbent)], [self.beam_error(r)])
            self.records[-1]['beam_error_gate'] = error_gate
            
            if self.eligible(r) and incumbent_cost-r.score > margin and error_gate['passed']:
                self._pairs = []
                start = self._pair_rng.randrange(2)

                orders = [(i+start)%2 for i in range(self.config.confirmation_pairs)]
                self._pair_rng.shuffle(orders)

                for reverse in orders:
                    pair = [(self._incumbent,'Confirm incumbent'),(self._challenger,'Confirm BO')]
                    self._queue.extend(reversed(pair) if reverse else pair)

                self.records[-1]['confirmation_order'] = [s for _,s in self._queue]
                self._transition(HybridState.CONFIRMATION, 'Repeat both candidates in randomized, balanced pair order before handover.')
            else:
                self._transition(HybridState.GA, 'BO challenger failed cost, measured beam-error improvement, or response checks.')

        elif source.startswith('Confirm'):
            self._pairs.append((source,r))

            if not self._queue:
                incumbents = [x.score for s,x in self._pairs if s == 'Confirm incumbent']
                challengers = [x.score for s,x in self._pairs if s == 'Confirm BO']

                differences = [a-b for a,b in zip(incumbents,challengers)]
                # Two-sided 95% Student-t critical values (small repeat counts).
                n = len(differences)
                critical = {2:12.706, 3:4.303, 4:3.182, 5:2.776, 6:2.571, 7:2.447, 8:2.365, 9:2.306, 10:2.262}.get(n, 2.262)

                margin = max(abs(mean(incumbents))*self.config.improvement_fraction,
                             critical * stdev(differences) / math.sqrt(n), 2 * self.noise, 1e-9)
                
                stable = all(self.eligible(x) for s,x in self._pairs if s == 'Confirm BO')

                error_gate = self.error_gate(
                    [self.beam_error(x) for s,x in self._pairs if s == 'Confirm incumbent'],
                    [self.beam_error(x) for s,x in self._pairs if s == 'Confirm BO'], critical)
                
                self.records[-1]['beam_error_gate'] = error_gate

                if stable and mean(differences) > margin and error_gate['passed']:
                    self._bo_stalls = self._prediction_misses = 0
                    self._transition(
                        
                        HybridState.BO, 
                        f'Paired cost improvement {mean(differences):.4g} > {margin:.4g}; '
                        f'beam MAE improvement {error_gate["improvement_nA"]:.4g} nA > '
                        f'{error_gate["required_nA"]:.4g} nA; response checks passed. BO takes over.'
                        
                        )

                else:
                    self._transition(HybridState.GA, 'Paired confirmation failed cost, measured beam-error improvement/noise, or response checks.')

        elif source == 'BO':
            improved = self.eligible(r) and previous_best-r.score > max(abs(previous_best)*self.config.improvement_fraction,2*self.noise,1e-9)
            self._bo_stalls = 0 if improved else self._bo_stalls+1

            mu,sigma = self.prediction
            missed = abs(r.score-mu) > max(3*sigma,2*self.noise,abs(mu)*self.config.improvement_fraction,1e-9)

            self._prediction_misses = self._prediction_misses+1 if missed else 0

            if self._bo_stalls >= self.config.plateau_trials or self._prediction_misses >= 3:
                self._transition(HybridState.GA, 'BO plateau or three unreliable predictions; run another GA generation.')

                # BO's best measured gains seed the fallback population.
                best = self.best_result.candidate

                self.ga.population[0] = PIDGains(best.kp,best.ki,best.kd)
                self._last_bo_attempt = self.ga.generation
