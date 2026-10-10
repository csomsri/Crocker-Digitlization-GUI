# -*- coding: utf-8 -*-
"""Automatic candidate evaluator for GA-tuned PID beam-current control.

This module intentionally contains no Qt or hardware code.  The GUI/controller
integration starts and stops the existing PID loop, feeds one sample at a time
into :class:`GACandidateEvaluator`, and uses the returned lower-is-better score
with ``GAPIDTuner.submit_fitness``.

The fitness follows the five-term structure used by the CNL paper:

    J = w_track J_track + w_ss J_ss + w_move J_move
        + w_sat J_sat + w_osc J_osc

where the terms measure normalized tracking error, residual steady-state error,
trim-coil motion, saturation, and oscillatory response. Invalid numeric data or
an interrupted test produce an aborted result with a large penalty. Finite
beam errors, zero beam, TC displacement, and saturation are scored without
candidate-level threshold aborts.
"""

from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

from source.Python.Control.NLAPID import PIDGains


class EvaluationPhase(str, Enum):
    """State of one candidate evaluation."""

    IDLE = "IDLE"
    WARMUP = "WARMUP"
    SCORING = "SCORING"
    COMPLETE = "COMPLETE"
    ABORTED = "ABORTED"


@dataclass(frozen=True)
class GAFitnessWeights:
    """Weights for the paper-style lower-is-better fitness function."""

    tracking: float = 1.0
    steady_state: float = 2.0
    movement: float = 0.25
    saturation: float = 5.0
    oscillation: float = 1.0
    safety_violation: float = 1_000_000.0

    def validated(self) -> "GAFitnessWeights":
        values = (
            float(self.tracking),
            float(self.steady_state),
            float(self.movement),
            float(self.saturation),
            float(self.oscillation),
            float(self.safety_violation),
        )
        if not all(math.isfinite(value) and value >= 0.0 for value in values):
            raise ValueError("GA fitness weights must be finite and nonnegative")
        return GAFitnessWeights(*values)


@dataclass(frozen=True)
class GAEvaluationConfig:
    """Timing, sample sufficiency, and score scales for a candidate test.

    ``movement_normalization_a`` is only the scale used for the movement
    fitness term. It does not limit commanded or measured TC displacement.
    """

    warmup_s: float = 5.0
    evaluation_s: float = 30.0
    steady_state_window_s: float = 5.0
    minimum_scored_samples: int = 2
    error_normalization_nA: float = 0.0
    movement_normalization_a: float = 10.0

    def validated(self) -> "GAEvaluationConfig":
        warmup = max(0.0, float(self.warmup_s))
        evaluation = max(0.1, float(self.evaluation_s))
        steady = max(0.0, min(evaluation, float(self.steady_state_window_s)))
        minimum_samples = max(2, int(self.minimum_scored_samples))
        normalization = max(0.0, float(self.error_normalization_nA))
        movement_normalization = float(self.movement_normalization_a)
        if not math.isfinite(movement_normalization) or movement_normalization <= 0.0:
            raise ValueError("GA movement normalization must be finite and greater than zero")
        values = (
            warmup,
            evaluation,
            steady,
            normalization,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("GA evaluation settings must be finite")
        return GAEvaluationConfig(
            warmup_s=warmup,
            evaluation_s=evaluation,
            steady_state_window_s=steady,
            minimum_scored_samples=minimum_samples,
            error_normalization_nA=normalization,
            movement_normalization_a=movement_normalization,
        )


@dataclass(frozen=True)
class GAEvaluationSample:
    """One time-aligned sample from a candidate test."""

    elapsed_s: float
    beam_nA: float
    setpoint_nA: float
    error_nA: float
    tc_target_a: float
    tc_actual_a: float
    pid_delta_a: float
    saturated: bool
    scoring: bool


@dataclass(frozen=True)
class GAFitnessTerms:
    """Unweighted normalized terms used to construct the total score."""

    tracking: float
    steady_state: float
    movement: float
    saturation: float
    oscillation: float
    safety: float = 0.0


@dataclass(frozen=True)
class GAEvaluationResult:
    """Completed or aborted candidate evaluation."""

    candidate_number: int
    generation_number: int
    gains: PIDGains
    score: float
    terms: GAFitnessTerms
    phase: EvaluationPhase
    reason: str
    duration_s: float
    scored_samples: int
    total_samples: int
    maximum_abs_error_nA: float
    maximum_tc_excursion_a: float  # Observed target displacement; not an abort limit.
    samples: tuple[GAEvaluationSample, ...]

    @property
    def safety_violation(self) -> bool:
        return self.phase == EvaluationPhase.ABORTED


@dataclass(frozen=True)
class EvaluationUpdate:
    """Return value from :meth:`GACandidateEvaluator.observe`."""

    phase: EvaluationPhase
    progress: float
    scored_samples: int
    result: GAEvaluationResult | None = None


class GACandidateEvaluator:
    """State machine for evaluating one PID-gain candidate.

    ``observe`` must be called once per *new* beam sample.  Duplicate or
    out-of-order timestamps are ignored.  The class does not command the plant;
    it evaluates finite samples over the requested timing windows.
    """

    def __init__(
        self,
        config: GAEvaluationConfig | None = None,
        weights: GAFitnessWeights | None = None,
    ):
        self.config = (config or GAEvaluationConfig()).validated()
        self.weights = (weights or GAFitnessWeights()).validated()
        self.reset()

    def reset(self) -> None:
        self.phase = EvaluationPhase.IDLE
        self.candidate_number = 0
        self.generation_number = 0
        self.gains = PIDGains()
        self.setpoint_nA = 0.0
        self.baseline_target_a = 0.0
        self.baseline_actual_a = 0.0
        self._start_timestamp_s = 0.0
        self._last_timestamp_s = 0.0
        self._samples: list[GAEvaluationSample] = []
        self._result: GAEvaluationResult | None = None

    @property
    def active(self) -> bool:
        return self.phase in (EvaluationPhase.WARMUP, EvaluationPhase.SCORING)

    @property
    def result(self) -> GAEvaluationResult | None:
        return self._result

    @property
    def start_timestamp_s(self) -> float:
        """Monotonic timestamp used as the beginning of this candidate test."""
        return float(self._start_timestamp_s)

    def elapsed_s(self, timestamp_s: float | None = None) -> float:
        """Return elapsed candidate time without exposing internal state."""
        timestamp = self._last_timestamp_s if timestamp_s is None else float(timestamp_s)
        return max(0.0, timestamp - self._start_timestamp_s)

    def start(
        self,
        *,
        candidate_number: int,
        generation_number: int,
        gains: PIDGains,
        setpoint_nA: float,
        baseline_target_a: float,
        timestamp_s: float,
        baseline_actual_a: float | None = None,
    ) -> None:
        baseline_actual = (
            float(baseline_target_a)
            if baseline_actual_a is None
            else float(baseline_actual_a)
        )
        values = (
            float(setpoint_nA),
            float(baseline_target_a),
            baseline_actual,
            float(timestamp_s),
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("GA candidate start values must be finite")
        self.reset()
        self.candidate_number = max(1, int(candidate_number))
        self.generation_number = max(1, int(generation_number))
        self.gains = gains.validated()
        self.setpoint_nA = float(setpoint_nA)
        self.baseline_target_a = float(baseline_target_a)
        self.baseline_actual_a = baseline_actual
        self._start_timestamp_s = float(timestamp_s)
        self.phase = (
            EvaluationPhase.WARMUP
            if self.config.warmup_s > 0.0
            else EvaluationPhase.SCORING
        )

    def safety_reason(
        self,
        *,
        beam_nA: float,
        tc_target_a: float,
        tc_actual_a: float | None = None,
    ) -> str | None:
        """Return a numeric-data error before another command, if present.

        This compatibility entry point does not apply beam-error, beam-loss,
        or TC-displacement thresholds.
        """
        try:
            beam = float(beam_nA)
            target = float(tc_target_a)
            actual = None if tc_actual_a is None else float(tc_actual_a)
        except (TypeError, ValueError):
            return "NON-NUMERIC FEEDBACK"
        if not math.isfinite(beam):
            return "NON-FINITE BEAM FEEDBACK"
        if not math.isfinite(target):
            return "NON-FINITE TC TARGET"
        if actual is not None and not math.isfinite(actual):
            return "NON-FINITE TC READBACK"

        return None

    def observe(
        self,
        *,
        timestamp_s: float,
        beam_nA: float,
        tc_target_a: float,
        tc_actual_a: float,
        pid_delta_a: float,
        saturated: bool,
    ) -> EvaluationUpdate:
        if not self.active:
            return EvaluationUpdate(self.phase, self.progress(timestamp_s), self.scored_samples)

        timestamp = float(timestamp_s)
        values = (
            timestamp,
            float(beam_nA),
            float(tc_target_a),
            float(tc_actual_a),
            float(pid_delta_a),
        )
        if not all(math.isfinite(value) for value in values):
            result = self.abort("NON-FINITE CANDIDATE SAMPLE", timestamp_s=timestamp)
            return EvaluationUpdate(self.phase, 1.0, self.scored_samples, result)

        if self._last_timestamp_s > 0.0 and timestamp <= self._last_timestamp_s:
            return EvaluationUpdate(self.phase, self.progress(timestamp), self.scored_samples)
        self._last_timestamp_s = timestamp

        reason = self.safety_reason(
            beam_nA=beam_nA,
            tc_target_a=tc_target_a,
            tc_actual_a=tc_actual_a,
        )
        if reason is not None:
            result = self.abort(reason, timestamp_s=timestamp)
            return EvaluationUpdate(self.phase, 1.0, self.scored_samples, result)

        elapsed = max(0.0, timestamp - self._start_timestamp_s)
        scoring = elapsed >= self.config.warmup_s
        if scoring:
            self.phase = EvaluationPhase.SCORING

        error = self.setpoint_nA - float(beam_nA)
        sample = GAEvaluationSample(
            elapsed_s=elapsed,
            beam_nA=float(beam_nA),
            setpoint_nA=self.setpoint_nA,
            error_nA=error,
            tc_target_a=float(tc_target_a),
            tc_actual_a=float(tc_actual_a),
            pid_delta_a=float(pid_delta_a),
            saturated=bool(saturated),
            scoring=scoring,
        )
        self._samples.append(sample)

        result = self.finish_if_due(timestamp_s=timestamp)
        if result is not None:
            return EvaluationUpdate(self.phase, 1.0, self.scored_samples, result)

        return EvaluationUpdate(
            self.phase,
            self.progress(timestamp),
            self.scored_samples,
        )

    def finish_if_due(self, *, timestamp_s: float) -> GAEvaluationResult | None:
        """Finish a due test using its existing scored data.

        ``timestamp_s`` must use the same clock as the candidate start. A GUI
        timer may call this without a new sample to stop at the requested
        warm-up plus evaluation duration. Early calls return ``None``; a due
        test with insufficient scored samples returns an invalid result. Once
        finished or aborted, later calls return the original result unchanged.
        """
        if self._result is not None:
            return self._result
        if not self.active:
            return None
        timestamp = float(timestamp_s)
        if not math.isfinite(timestamp):
            raise ValueError("GA completion timestamp must be finite")
        required_elapsed = self.config.warmup_s + self.config.evaluation_s
        if timestamp - self._start_timestamp_s < required_elapsed:
            return None
        if self.scored_samples < self.config.minimum_scored_samples:
            return self.abort(
                f"ONLY {self.scored_samples} SCORED SAMPLES; "
                f"MINIMUM IS {self.config.minimum_scored_samples}",
                timestamp_s=timestamp,
            )
        return self._finish(
            phase=EvaluationPhase.COMPLETE,
            reason="CANDIDATE EVALUATION COMPLETE",
            timestamp_s=timestamp,
        )

    @property
    def scored_samples(self) -> int:
        return sum(1 for sample in self._samples if sample.scoring)

    def progress(self, timestamp_s: float | None = None) -> float:
        if self.phase == EvaluationPhase.IDLE:
            return 0.0
        if self.phase in (EvaluationPhase.COMPLETE, EvaluationPhase.ABORTED):
            return 1.0
        timestamp = self._last_timestamp_s if timestamp_s is None else float(timestamp_s)
        elapsed = max(0.0, timestamp - self._start_timestamp_s)
        total = self.config.warmup_s + self.config.evaluation_s
        return max(0.0, min(1.0, elapsed / max(total, 1e-9)))

    def provisional_score(self) -> tuple[float, GAFitnessTerms] | None:
        """Return a live lower-is-better score estimate for scored samples.

        The value is informational only and is never submitted to the GA.  The
        final score remains the one calculated after the full evaluation or a
        test interruption.
        """
        scored = [sample for sample in self._samples if sample.scoring]
        if not scored:
            return None
        terms = self._calculate_terms(
            scored,
            all_samples=self._samples,
            safety=False,
        )
        w = self.weights
        score = (
            w.tracking * terms.tracking
            + w.steady_state * terms.steady_state
            + w.movement * terms.movement
            + w.saturation * terms.saturation
            + w.oscillation * terms.oscillation
        )
        return float(score), terms

    def abort(
        self,
        reason: str,
        *,
        timestamp_s: float | None = None,
    ) -> GAEvaluationResult:
        if self._result is not None:
            return self._result
        timestamp = (
            self._last_timestamp_s
            if timestamp_s is None
            else float(timestamp_s)
        )
        self._result = self._finish(
            phase=EvaluationPhase.ABORTED,
            reason=str(reason),
            timestamp_s=timestamp,
        )
        return self._result

    def _finish(
        self,
        *,
        phase: EvaluationPhase,
        reason: str,
        timestamp_s: float,
    ) -> GAEvaluationResult:
        scored = [sample for sample in self._samples if sample.scoring]
        terms = self._calculate_terms(
            scored,
            all_samples=self._samples,
            safety=(phase == EvaluationPhase.ABORTED),
        )
        w = self.weights
        score = (
            w.tracking * terms.tracking
            + w.steady_state * terms.steady_state
            + w.movement * terms.movement
            + w.saturation * terms.saturation
            + w.oscillation * terms.oscillation
            + terms.safety
        )
        duration = max(0.0, float(timestamp_s) - self._start_timestamp_s)
        maximum_error = max(
            (abs(sample.error_nA) for sample in self._samples),
            default=0.0,
        )
        maximum_excursion = max(
            (
                abs(sample.tc_target_a - self.baseline_target_a)
                for sample in self._samples
            ),
            default=0.0,
        )
        self.phase = phase
        self._result = GAEvaluationResult(
            candidate_number=self.candidate_number,
            generation_number=self.generation_number,
            gains=self.gains,
            score=float(score),
            terms=terms,
            phase=phase,
            reason=str(reason),
            duration_s=duration,
            scored_samples=len(scored),
            total_samples=len(self._samples),
            maximum_abs_error_nA=maximum_error,
            maximum_tc_excursion_a=maximum_excursion,
            samples=tuple(self._samples),
        )
        return self._result

    def _calculate_terms(
        self,
        samples: Iterable[GAEvaluationSample],
        *,
        all_samples: Iterable[GAEvaluationSample] | None = None,
        safety: bool,
    ) -> GAFitnessTerms:
        values = list(samples)
        full_values = list(all_samples) if all_samples is not None else list(values)
        if not values:
            return GAFitnessTerms(
                tracking=1_000.0,
                steady_state=1_000.0,
                movement=1_000.0,
                saturation=1.0,
                oscillation=1_000.0,
                safety=self.weights.safety_violation if safety else 0.0,
            )

        error_scale = self.config.error_normalization_nA
        if error_scale <= 0.0:
            error_scale = max(abs(self.setpoint_nA), 1.0e-6)
        errors = [sample.error_nA for sample in values]
        abs_errors = [abs(value) for value in errors]

        # J_track: time-normalized mean absolute tracking error.
        tracking = self._time_weighted_mean(values, abs_errors) / error_scale

        # J_ss: residual error during the final configured time window.
        end_time = values[-1].elapsed_s
        window_start = max(values[0].elapsed_s, end_time - self.config.steady_state_window_s)
        steady_samples = [sample for sample in values if sample.elapsed_s >= window_start]
        steady_abs_errors = [abs(sample.error_nA) for sample in steady_samples]
        steady_state = (
            self._time_weighted_mean(steady_samples, steady_abs_errors) / error_scale
        )

        # J_move: total variation of the commanded TC target divided by a
        # fixed score scale. Reversals are intentionally penalized. This scale
        # does not impose a displacement limit or cap the movement score.
        motion_values = full_values if full_values else values
        targets = [self.baseline_target_a] + [
            sample.tc_target_a for sample in motion_values
        ]
        total_variation = sum(
            abs(targets[index] - targets[index - 1])
            for index in range(1, len(targets))
        )
        movement = total_variation / self.config.movement_normalization_a

        # J_sat: fraction of scored samples at a PID or actuator limit.
        saturation_values = full_values if full_values else values
        saturation = (
            sum(sample.saturated for sample in saturation_values)
            / len(saturation_values)
        )

        # J_osc: excess error variation plus setpoint-crossing rate. A monotonic
        # approach to the setpoint has little excess variation; repeated hunting
        # produces a larger value even when the final error is small.
        oscillation_values = full_values if full_values else values
        oscillation_errors = [sample.error_nA for sample in oscillation_values]
        normalized_errors = [value / error_scale for value in oscillation_errors]
        variation = sum(
            abs(normalized_errors[index] - normalized_errors[index - 1])
            for index in range(1, len(normalized_errors))
        )
        net_change = abs(normalized_errors[-1] - normalized_errors[0])
        excess_variation = max(0.0, variation - net_change)
        crossings = 0
        previous_sign = 0
        for error in oscillation_errors:
            sign = 1 if error > 0.0 else (-1 if error < 0.0 else 0)
            if sign != 0:
                if previous_sign != 0 and sign != previous_sign:
                    crossings += 1
                previous_sign = sign
        denominator = max(1, len(oscillation_values) - 1)
        oscillation = excess_variation / denominator + crossings / denominator

        return GAFitnessTerms(
            tracking=float(tracking),
            steady_state=float(steady_state),
            movement=float(movement),
            saturation=float(saturation),
            oscillation=float(oscillation),
            safety=self.weights.safety_violation if safety else 0.0,
        )

    @staticmethod
    def _time_weighted_mean(
        samples: list[GAEvaluationSample],
        values: list[float],
    ) -> float:
        if not samples or not values:
            return 0.0
        n = min(len(samples), len(values))
        if n == 1:
            return float(values[0])
        integral = 0.0
        duration = max(0.0, samples[n - 1].elapsed_s - samples[0].elapsed_s)
        if duration <= 0.0:
            return sum(values[:n]) / n
        for index in range(1, n):
            dt = max(0.0, samples[index].elapsed_s - samples[index - 1].elapsed_s)
            integral += 0.5 * (values[index] + values[index - 1]) * dt
        return integral / duration


def write_evaluation_csv(result: GAEvaluationResult, path: str | Path) -> Path:
    """Write all time-aligned samples for one candidate evaluation."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = [field for field in GAEvaluationSample.__dataclass_fields__]
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for sample in result.samples:
            writer.writerow(asdict(sample))
    return destination


def append_summary_csv(result: GAEvaluationResult, path: str | Path) -> Path:
    """Append one candidate result to a run-level summary CSV."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "generation": result.generation_number,
        "candidate": result.candidate_number,
        "kp": result.gains.kp,
        "ki": result.gains.ki,
        "kd": result.gains.kd,
        "fitness": result.score,
        "j_track": result.terms.tracking,
        "j_ss": result.terms.steady_state,
        "j_move": result.terms.movement,
        "j_sat": result.terms.saturation,
        "j_osc": result.terms.oscillation,
        "safety_penalty": result.terms.safety,
        "phase": result.phase.value,
        "reason": result.reason,
        "duration_s": result.duration_s,
        "scored_samples": result.scored_samples,
        "total_samples": result.total_samples,
        "max_abs_error_nA": result.maximum_abs_error_nA,
        "max_tc_excursion_a": result.maximum_tc_excursion_a,
    }
    fieldnames = list(row)
    write_header = not destination.exists() or destination.stat().st_size == 0
    with destination.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    return destination


__all__ = [
    "EvaluationPhase",
    "GAFitnessWeights",
    "GAEvaluationConfig",
    "GAEvaluationSample",
    "GAFitnessTerms",
    "GAEvaluationResult",
    "EvaluationUpdate",
    "GACandidateEvaluator",
    "write_evaluation_csv",
    "append_summary_csv",
]

FitnessTerms = GAFitnessTerms
Phase = EvaluationPhase
