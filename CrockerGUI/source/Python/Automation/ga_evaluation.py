"""GA candidate scoring in beam nA and trim-coil A; lower cost is better."""
from dataclasses import dataclass, asdict
from enum import Enum
from types import SimpleNamespace
import csv
import math


@dataclass(frozen=True)
class GAEvaluationConfig:
    warmup_s: float = 5
    evaluation_s: float = 30
    steady_state_window_s: float = 5
    max_tc_excursion_a: float = .5
    max_abs_beam_error_nA: float = 3
    minimum_valid_beam_nA: float = .05
    max_saturation_s: float = 5
    minimum_scored_samples: int = 10

    def validated(self):
        if not all(math.isfinite(v) and v >= 0 for v in asdict(self).values()):
            raise ValueError('Evaluation settings must be finite and nonnegative')
        if self.evaluation_s <= 0 or self.minimum_scored_samples < 1 or self.max_tc_excursion_a <= 0:
            raise ValueError('Evaluation interval, sample count and excursion must be positive')
        return self


@dataclass(frozen=True)
class GAFitnessWeights:
    tracking: float = 1
    steady_state: float = 1
    movement: float = 1
    saturation: float = 1
    oscillation: float = 1

    def validated(self):
        if not all(math.isfinite(v) and v >= 0 for v in asdict(self).values()):
            raise ValueError('Weights must be finite and nonnegative')
        if not any(asdict(self).values()):
            raise ValueError('At least one fitness weight must be positive')
        return self


@dataclass(frozen=True)
class FitnessTerms:
    tracking: float = 0
    steady_state: float = 0
    movement: float = 0
    saturation: float = 0
    oscillation: float = 0


@dataclass(frozen=True)
class GAEvaluationResult:
    candidate_number: int
    generation_number: int
    score: float
    terms: FitnessTerms
    safety_violation: bool
    reason: str
    samples: tuple
    gains: object


class Phase(Enum):
    IDLE = 'IDLE'
    WARMUP = 'WARMUP'
    SCORING = 'SCORING'
    COMPLETE = 'COMPLETE'


class GACandidateEvaluator:
    def __init__(self, config=None, weights=None):
        self.config = (config or GAEvaluationConfig()).validated()
        self.weights = (weights or GAFitnessWeights()).validated()
        self.active = False
        self.phase = Phase.IDLE
        self.samples = []

    def start(self, *, candidate_number, generation_number, gains, setpoint_nA,
              baseline_target_a, baseline_actual_a, timestamp_s):
        if not all(math.isfinite(v) for v in (setpoint_nA, baseline_target_a, baseline_actual_a, timestamp_s)):
            raise ValueError('Candidate reference must be finite')
        self.candidate_number, self.generation_number, self.gains = candidate_number, generation_number, gains
        self.setpoint, self.baseline, self.actual_baseline = setpoint_nA, baseline_target_a, baseline_actual_a
        self.start_time = self.last_time = timestamp_s
        self.saturation_time = 0
        self.samples = []
        self.active = True
        self.phase = Phase.WARMUP

    @property
    def target_bounds(self):
        return self.baseline-self.config.max_tc_excursion_a, self.baseline+self.config.max_tc_excursion_a

    @property
    def scored_samples(self):
        return len(self.samples)

    def elapsed_s(self, timestamp_s):
        return max(0, timestamp_s-self.start_time)

    def safety_reason(self, *, beam_nA, tc_target_a, tc_actual_a):
        if not all(math.isfinite(v) for v in (beam_nA, tc_target_a, tc_actual_a)):
            return 'Nonfinite feedback'
        if abs(beam_nA) < self.config.minimum_valid_beam_nA:
            return 'Beam output lost'
        if abs(self.setpoint-beam_nA) > self.config.max_abs_beam_error_nA:
            return 'Beam error limit exceeded'
        if abs(tc_target_a-self.baseline) > self.config.max_tc_excursion_a + 1e-9 or abs(tc_actual_a-self.actual_baseline) > self.config.max_tc_excursion_a + 1e-9:
            return 'Trim-coil excursion exceeded'
        return None

    def observe(self, *, timestamp_s, beam_nA, tc_target_a, tc_actual_a, pid_delta_a, saturated):
        if not self.active:
            raise RuntimeError('No active candidate')
        if not math.isfinite(timestamp_s) or not math.isfinite(pid_delta_a):
            return SimpleNamespace(result=self.abort('Invalid sample', timestamp_s=self.last_time))
        if timestamp_s <= self.last_time:
            return SimpleNamespace(result=None)
        dt = timestamp_s-self.last_time
        self.last_time = timestamp_s
        reason = self.safety_reason(beam_nA=beam_nA, tc_target_a=tc_target_a, tc_actual_a=tc_actual_a)
        self.saturation_time = self.saturation_time + dt if saturated else 0
        if saturated and self.saturation_time > self.config.max_saturation_s:
            reason = 'Saturation timeout'
        if reason:
            return SimpleNamespace(result=self.abort(reason, timestamp_s=timestamp_s))
        elapsed = self.elapsed_s(timestamp_s)
        if elapsed >= self.config.warmup_s:
            self.phase = Phase.SCORING
            self.samples.append(dict(time_s=elapsed, error=self.setpoint-beam_nA, beam_nA=beam_nA,
                                     target_a=tc_target_a, actual_a=tc_actual_a, delta_a=pid_delta_a,
                                     saturated=bool(saturated), dt=min(dt, elapsed-self.config.warmup_s)))
        if elapsed >= self.config.warmup_s+self.config.evaluation_s:
            if len(self.samples) < self.config.minimum_scored_samples:
                return SimpleNamespace(result=self.abort('Insufficient scored samples', timestamp_s=timestamp_s))
            return SimpleNamespace(result=self._finish(False, 'Completed'))
        return SimpleNamespace(result=None)

    def provisional_score(self):
        if not self.samples:
            return None
        duration = sum(s['dt'] for s in self.samples) or 1
        last = self.samples[-1]['time_s']
        steady = [s for s in self.samples if s['time_s'] >= last-self.config.steady_state_window_s]
        terms = FitnessTerms(
            tracking=sum(abs(s['error'])*s['dt'] for s in self.samples)/duration,
            steady_state=sum(abs(s['error']) for s in steady)/len(steady),
            movement=sum(abs(s['delta_a']) for s in self.samples),
            saturation=sum(s['dt'] for s in self.samples if s['saturated'])/duration,
            oscillation=sum(a['error']*b['error'] < 0 for a,b in zip(self.samples,self.samples[1:])),
        )
        # Bounded monotone cost leaves safety penalties strictly worse than any valid score.
        raw = sum(getattr(self.weights,k)*v for k,v in asdict(terms).items())
        return 999999 * (1 - 1/(1+raw)), terms

    def _finish(self, unsafe, reason):
        score, terms = self.provisional_score() or (0, FitnessTerms())
        self.active = False
        self.phase = Phase.COMPLETE
        return GAEvaluationResult(self.candidate_number, self.generation_number,
                                  1000000+score if unsafe else score, terms, unsafe, reason,
                                  tuple(self.samples), self.gains)

    def abort(self, reason, timestamp_s):
        return self._finish(True, reason)


def write_evaluation_csv(result, path):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        fields = ['time_s','error','beam_nA','target_a','actual_a','delta_a','saturated','dt']
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result.samples)


def append_summary_csv(result, path):
    from pathlib import Path
    exists = Path(path).exists()
    row = dict(generation=result.generation_number, candidate=result.candidate_number,
               **asdict(result.gains), score=result.score, unsafe=result.safety_violation,
               reason=result.reason, **asdict(result.terms))
    with open(path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        if not exists:
            writer.writeheader()
        writer.writerow(row)
