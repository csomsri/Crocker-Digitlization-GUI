"""Bounded, seeded genetic gain search. No GUI, transport or PID execution."""
from dataclasses import dataclass, replace
import math
import random
from source.Python.Control.NLAPID import PIDGains
from . import october_ga


@dataclass(frozen=True)
class GainBounds:
    kp: tuple[float, float]
    ki: tuple[float, float]
    kd: tuple[float, float]

    def validated(self):
        for bounds in (self.kp, self.ki, self.kd):
            if len(bounds) != 2 or not all(math.isfinite(v) for v in bounds) or not 0 <= bounds[0] <= bounds[1]:
                raise ValueError('Gain bounds must be finite, nonnegative and ordered')
        return self


@dataclass(frozen=True)
class GATuningConfig:
    population_size: int = 4
    generations: int = 2
    seed: int = 0
    mutation_probability: float = 0.25
    mutation_scale: float = 0.1

    def validated(self):
        if self.population_size < 4 or self.generations < 1:
            raise ValueError('Population must be at least four; generations must be positive')
        if not 0 <= self.mutation_probability <= 1 or not 0 <= self.mutation_scale <= 1:
            raise ValueError('Mutation settings must be between zero and one')
        return self


@dataclass(frozen=True)
class PIDCandidate:
    gains: PIDGains
    generation: int
    index: int
    fitness: float | None = None
    valid: bool = True


class GAPIDTuner:
    def __init__(self, bounds, config):
        self.bounds, self.config = bounds.validated(), config.validated()
        self.rng = random.Random(config.seed)

        self.history = []
        self.finished = False

        self.population = []
        self.generation = self.index = 0

    def initialize(self, gains):
        values = (gains.kp, gains.ki, gains.kd)
        bounds = (self.bounds.kp, self.bounds.ki, self.bounds.kd)

        if any(not math.isfinite(v) or not lo <= v <= hi for v, (lo, hi) in zip(values, bounds)):
            raise ValueError('Seed gains must lie within the search bounds')
        
        self.history.clear()
        self.rng.seed(self.config.seed)

        self.finished = False
        self.generation = self.index = 0

        self.population = [gains] + [PIDGains(*(self.rng.uniform(*b) for b in bounds)) for _ in range(self.config.population_size - 1)]

        return self.current_candidate()

    def current_candidate(self):
        if self.finished or not self.population:
            raise RuntimeError('No pending candidate')
        return PIDCandidate(self.population[self.index], self.generation, self.index)

    def best_candidate(self):
        valid = [c for c in self.history if c.valid]
        return min(valid, key=lambda c: c.fitness) if valid else None

    def progress(self):
        return self.generation + 1, self.config.generations, self.index + 1, self.config.population_size

    def submit_fitness(self, fitness, *, valid=True):
        if not math.isfinite(fitness) or fitness < 0:
            raise ValueError('Fitness must be finite and nonnegative')

        self.history.append(replace(self.current_candidate(), fitness=float(fitness), valid=bool(valid)))
        self.index += 1

        if self.index == self.config.population_size:
            if self.generation + 1 == self.config.generations:
                self.finished = True
                self.index -= 1

                return None

            # Use OctoberPID's validity-aware tournament, blend crossover,
            # mutation and elitism while retaining the hybrid optimizer API.
            engine = october_ga.GAPIDTuner(
                october_ga.GainBounds(self.bounds.kp, self.bounds.ki, self.bounds.kd),
                october_ga.GATuningConfig(
                    population_size=self.config.population_size,
                    generations=self.config.generations,
                    mutation_probability=self.config.mutation_probability,
                    mutation_scale=self.config.mutation_scale,
                    random_seed=self.config.seed))
            engine._rng = self.rng
            engine.generation_index = self.generation
            engine.population = [october_ga.PIDCandidate(
                c.gains, c.fitness, c.generation, c.index, c.valid)
                for c in self.history[-self.config.population_size:]]
            population = [c.gains for c in engine._create_next_generation()]
            self.population = population

            self.generation += 1
            self.index = 0
        return self.current_candidate()
