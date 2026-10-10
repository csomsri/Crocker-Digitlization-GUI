# -*- coding: utf-8 -*-
"""Genetic-algorithm candidate manager for PID gain auto-tuning.

The tuner is intentionally independent of Qt and hardware.  A separate test
runner should apply each candidate to the plant/simulator, measure the response,
calculate a scalar fitness (lower is better), and call ``submit_fitness``.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterable, Sequence

from source.Python.Control.NLAPID import PIDGains


@dataclass(frozen=True)
class GainBounds:
    kp: tuple[float, float] = (0.0, 10.0)
    ki: tuple[float, float] = (0.0, 5.0)
    kd: tuple[float, float] = (0.0, 2.0)

    def validated(self) -> "GainBounds":
        def pair(values: tuple[float, float]) -> tuple[float, float]:
            lo, hi = sorted((float(values[0]), float(values[1])))
            if not all(math.isfinite(v) for v in (lo, hi)):
                raise ValueError("GA gain bounds must be finite")
            return lo, hi

        return GainBounds(kp=pair(self.kp), ki=pair(self.ki), kd=pair(self.kd))


@dataclass(frozen=True)
class GATuningConfig:
    population_size: int = 18
    generations: int = 25
    elite_fraction: float = 0.20
    mutation_probability: float = 0.25
    mutation_scale: float = 0.12
    crossover_blend: float = 0.25
    tournament_size: int = 3
    random_seed: int | None = None

    def validated(self) -> "GATuningConfig":
        population_size = max(4, int(self.population_size))
        generations = max(1, int(self.generations))
        elite_fraction = min(0.80, max(1.0 / population_size, float(self.elite_fraction)))
        mutation_probability = min(1.0, max(0.0, float(self.mutation_probability)))
        mutation_scale = max(0.0, float(self.mutation_scale))
        crossover_blend = max(0.0, float(self.crossover_blend))
        tournament_size = max(2, min(population_size, int(self.tournament_size)))
        values = (
            elite_fraction,
            mutation_probability,
            mutation_scale,
            crossover_blend,
        )
        if not all(math.isfinite(v) for v in values):
            raise ValueError("GA configuration values must be finite")
        return GATuningConfig(
            population_size=population_size,
            generations=generations,
            elite_fraction=elite_fraction,
            mutation_probability=mutation_probability,
            mutation_scale=mutation_scale,
            crossover_blend=crossover_blend,
            tournament_size=tournament_size,
            random_seed=self.random_seed,
        )


@dataclass
class PIDCandidate:
    gains: PIDGains
    fitness: float | None = None
    generation: int = 0
    index: int = 0
    # A failed test can still have a finite diagnostic penalty.  Validity must
    # therefore be kept separately from the number used to rank failed tests.
    valid: bool = True

    @property
    def evaluated(self) -> bool:
        """Whether a result was submitted, including an invalid result."""
        return self.fitness is not None


@dataclass(frozen=True)
class FitnessWeights:
    integrated_absolute_error: float = 1.0
    overshoot: float = 4.0
    settling_time: float = 1.0
    control_movement: float = 0.15
    saturation_fraction: float = 6.0
    safety_violation: float = 1_000_000.0


def calculate_pid_fitness(
    errors: Sequence[float] | Iterable[float],
    outputs: Sequence[float] | Iterable[float],
    *,
    dt: float,
    setpoint: float,
    measurements: Sequence[float] | Iterable[float] | None = None,
    output_saturated: Sequence[bool] | Iterable[bool] | None = None,
    settling_band_fraction: float = 0.02,
    safety_violation: bool = False,
    weights: FitnessWeights | None = None,
) -> float:
    """Calculate a lower-is-better PID response score.

    This helper is a starting point.  The final CNL fitness definition should be
    reviewed for the specific plant, ramp constraints, and beam objective.
    """

    w = weights or FitnessWeights()
    dt = float(dt)
    if dt <= 0.0 or not math.isfinite(dt):
        raise ValueError("dt must be finite and greater than zero")

    error_values = [float(v) for v in errors]
    output_values = [float(v) for v in outputs]
    n = min(len(error_values), len(output_values))
    if n == 0:
        return float("inf")
    error_values = error_values[:n]
    output_values = output_values[:n]
    if not all(math.isfinite(v) for v in error_values + output_values):
        return float("inf")

    iae = sum(abs(v) for v in error_values) * dt
    movement = sum(abs(output_values[i] - output_values[i - 1]) for i in range(1, n))

    measurement_values: list[float]
    if measurements is None:
        measurement_values = [float(setpoint) - err for err in error_values]
    else:
        measurement_values = [float(v) for v in measurements][:n]
        if len(measurement_values) < n:
            measurement_values.extend([measurement_values[-1]] * (n - len(measurement_values)))

    if setpoint >= 0.0:
        overshoot = max(0.0, max(measurement_values) - float(setpoint))
    else:
        overshoot = max(0.0, float(setpoint) - min(measurement_values))

    band = max(abs(float(setpoint)) * max(0.0, float(settling_band_fraction)), 1e-9)
    settling_time = n * dt
    for i in range(n):
        if all(abs(err) <= band for err in error_values[i:]):
            settling_time = i * dt
            break

    if output_saturated is None:
        saturation_fraction = 0.0
    else:
        saturation = [bool(v) for v in output_saturated][:n]
        saturation_fraction = sum(saturation) / max(1, len(saturation))

    score = (
        w.integrated_absolute_error * iae
        + w.overshoot * overshoot
        + w.settling_time * settling_time
        + w.control_movement * movement
        + w.saturation_fraction * saturation_fraction
    )
    if safety_violation:
        score += w.safety_violation
    return float(score)


class GAPIDTuner:
    """Stateful GA that yields one PID candidate at a time."""

    def __init__(
        self,
        bounds: GainBounds | None = None,
        config: GATuningConfig | None = None,
    ):
        self.bounds = (bounds or GainBounds()).validated()
        self.config = (config or GATuningConfig()).validated()
        self._rng = random.Random(self.config.random_seed)
        self.population: list[PIDCandidate] = []
        self.generation_index = 0
        self.candidate_index = 0
        self.finished = False
        self.best_overall: PIDCandidate | None = None

    def initialize(self, seed_gains: PIDGains | None = None) -> PIDCandidate:
        self.population = []
        self.generation_index = 0
        self.candidate_index = 0
        self.finished = False
        self.best_overall = None

        if seed_gains is not None:
            gains = self._clamp_gains(seed_gains.validated())
            self.population.append(PIDCandidate(gains=gains, generation=0, index=0))

        while len(self.population) < self.config.population_size:
            idx = len(self.population)
            self.population.append(
                PIDCandidate(
                    gains=self._random_gains(),
                    generation=0,
                    index=idx,
                )
            )
        return self.current_candidate()

    def current_candidate(self) -> PIDCandidate:
        if not self.population:
            raise RuntimeError("GA population has not been initialized")
        if self.finished:
            raise RuntimeError("GA tuning is complete")
        return self.population[self.candidate_index]

    def submit_fitness(
        self,
        fitness: float,
        *,
        valid: bool = True,
    ) -> PIDCandidate | None:
        """Complete the current test and return the next gain candidate.

        ``valid=False`` retains a finite diagnostic score, but excludes the
        candidate from the reported best result. Non-finite scores are stored
        as positive infinity and are always invalid. A submitted failure still
        completes its population slot so that subsequent generations can run.
        """
        if self.finished:
            raise RuntimeError("GA tuning is already complete")
        candidate = self.current_candidate()
        fitness = float(fitness)
        if not math.isfinite(fitness):
            fitness = float("inf")
            valid = False
        candidate.fitness = fitness
        candidate.valid = bool(valid)
        self._update_best(candidate)

        self.candidate_index += 1
        if self.candidate_index < len(self.population):
            return self.current_candidate()

        # Generation finished.
        if self.generation_index + 1 >= self.config.generations:
            self.finished = True
            return None

        self.population = self._create_next_generation()
        self.generation_index += 1
        self.candidate_index = 0
        return self.current_candidate()

    def best_candidate(self) -> PIDCandidate | None:
        return self.best_overall

    def progress(self) -> tuple[int, int, int, int]:
        """Return generation, max generations, candidate, population (1-based)."""
        generation = min(self.generation_index + 1, self.config.generations)
        candidate = min(self.candidate_index + 1, self.config.population_size)
        return generation, self.config.generations, candidate, self.config.population_size

    def _update_best(self, candidate: PIDCandidate) -> None:
        if (
            not candidate.evaluated
            or not candidate.valid
            or not math.isfinite(float(candidate.fitness))
        ):
            return
        if self.best_overall is None or float(candidate.fitness) < float(self.best_overall.fitness):
            self.best_overall = PIDCandidate(
                gains=candidate.gains,
                fitness=float(candidate.fitness),
                generation=candidate.generation,
                index=candidate.index,
                valid=candidate.valid,
            )

    def _random_gains(self) -> PIDGains:
        return PIDGains(
            kp=self._rng.uniform(*self.bounds.kp),
            ki=self._rng.uniform(*self.bounds.ki),
            kd=self._rng.uniform(*self.bounds.kd),
        )

    def _clamp_gains(self, gains: PIDGains) -> PIDGains:
        def clamp(value: float, limits: tuple[float, float]) -> float:
            return max(limits[0], min(limits[1], float(value)))

        return PIDGains(
            kp=clamp(gains.kp, self.bounds.kp),
            ki=clamp(gains.ki, self.bounds.ki),
            kd=clamp(gains.kd, self.bounds.kd),
        )

    def _ranked_population(self) -> list[PIDCandidate]:
        if not self.population or not all(candidate.evaluated for candidate in self.population):
            raise RuntimeError("Every candidate must have a fitness before evolution")
        return sorted(self.population, key=self._ranking_key)

    @staticmethod
    def _ranking_key(candidate: PIDCandidate) -> tuple[bool, float]:
        fitness = (
            float("inf")
            if candidate.fitness is None
            else float(candidate.fitness)
        )
        finite = math.isfinite(fitness)
        return (not (candidate.valid and finite), fitness if finite else float("inf"))

    def _tournament(self, ranked: Sequence[PIDCandidate]) -> PIDCandidate:
        # Invalid tests cannot displace valid parents simply because their
        # diagnostic penalty has a smaller numerical value. If every test
        # failed, bounded evolution may continue using the failed population,
        # but there is still no valid best result to apply.
        valid_parents = [item for item in ranked if not self._ranking_key(item)[0]]
        parent_pool = valid_parents or list(ranked)
        participants = self._rng.sample(
            parent_pool,
            k=min(self.config.tournament_size, len(parent_pool)),
        )
        return min(participants, key=self._ranking_key)

    def _crossover(self, a: PIDGains, b: PIDGains) -> PIDGains:
        blend = self.config.crossover_blend

        def child_value(v1: float, v2: float) -> float:
            low, high = sorted((v1, v2))
            span = high - low
            return self._rng.uniform(low - blend * span, high + blend * span)

        return self._clamp_gains(
            PIDGains(
                kp=child_value(a.kp, b.kp),
                ki=child_value(a.ki, b.ki),
                kd=child_value(a.kd, b.kd),
            )
        )

    def _mutate(self, gains: PIDGains) -> PIDGains:
        probability = self.config.mutation_probability
        scale = self.config.mutation_scale

        def mutate(value: float, bounds: tuple[float, float]) -> float:
            if self._rng.random() >= probability:
                return value
            sigma = max(1e-12, (bounds[1] - bounds[0]) * scale)
            return value + self._rng.gauss(0.0, sigma)

        return self._clamp_gains(
            PIDGains(
                kp=mutate(gains.kp, self.bounds.kp),
                ki=mutate(gains.ki, self.bounds.ki),
                kd=mutate(gains.kd, self.bounds.kd),
            )
        )

    def _create_next_generation(self) -> list[PIDCandidate]:
        ranked = self._ranked_population()
        elite_count = max(1, round(self.config.population_size * self.config.elite_fraction))
        next_generation: list[PIDCandidate] = []

        # Elites are copied, but must be re-evaluated if the plant is time-varying.
        for elite in ranked[:elite_count]:
            next_generation.append(
                PIDCandidate(
                    gains=elite.gains,
                    generation=self.generation_index + 1,
                    index=len(next_generation),
                )
            )

        while len(next_generation) < self.config.population_size:
            parent_a = self._tournament(ranked)
            parent_b = self._tournament(ranked)
            child_gains = self._mutate(self._crossover(parent_a.gains, parent_b.gains))
            next_generation.append(
                PIDCandidate(
                    gains=child_gains,
                    generation=self.generation_index + 1,
                    index=len(next_generation),
                )
            )
        return next_generation


__all__ = [
    "GainBounds",
    "GATuningConfig",
    "PIDCandidate",
    "FitnessWeights",
    "calculate_pid_fitness",
    "GAPIDTuner",
]
