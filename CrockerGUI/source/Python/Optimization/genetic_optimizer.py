"""Bounded, seeded genetic gain search. No GUI, transport or PID execution."""
from dataclasses import dataclass, replace
import math
import random
from source.Python.Control.NLAPID import PIDGains


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
        return min(self.history, key=lambda c: c.fitness) if self.history else None

    def progress(self):
        return self.generation + 1, self.config.generations, self.index + 1, self.config.population_size

    def submit_fitness(self, fitness):
        if not math.isfinite(fitness) or fitness < 0:
            raise ValueError('Fitness must be finite and nonnegative')

        self.history.append(replace(self.current_candidate(), fitness=float(fitness)))
        self.index += 1

        if self.index == self.config.population_size:
            if self.generation + 1 == self.config.generations:
                self.finished = True
                self.index -= 1

                return None

            ranked = sorted(self.history[-self.config.population_size:], key=lambda c: c.fitness)
            parents = ranked[:max(2, len(ranked)//2)]

            population = [ranked[0].gains]

            while len(population) < self.config.population_size:
                a, b = self.rng.sample(parents, 2)
                genes = []

                for name in ('kp', 'ki', 'kd'):
                    low, high = getattr(self.bounds, name)
                    mix = self.rng.random()

                    value = mix * getattr(a.gains, name) + (1-mix) * getattr(b.gains, name)
                    if self.rng.random() < self.config.mutation_probability:
                        value += self.rng.gauss(0, self.config.mutation_scale * (high-low))

                    genes.append(max(low, min(high, value)))

                population.append(PIDGains(*genes))
            self.population = population

            self.generation += 1
            self.index = 0
        return self.current_candidate()
