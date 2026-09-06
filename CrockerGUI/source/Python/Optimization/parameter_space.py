"""Parameter-space types and validation for standalone optimization."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class OptimizationParameter:
    name: str
    bounds: tuple[float, float]


@dataclass(frozen=True)
class OptimizationCandidate:
    values: dict[str, float]

    def value(self, name: str) -> float:
        return self.values[name]


class ParameterSpace:
    def __init__(
        self,
        parameters: Sequence[OptimizationParameter | tuple[str, tuple[float, float]]],
    ) -> None:
        self.parameters = self._validate_parameters(parameters)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(parameter.name for parameter in self.parameters)

    @property
    def dimension(self) -> int:
        return len(self.parameters)

    def validate_candidate(self, candidate: OptimizationCandidate) -> None:
        missing = [name for name in self.names if name not in candidate.values]
        if missing:
            raise ValueError(f"Candidate is missing parameter(s): {', '.join(missing)}")
        for parameter in self.parameters:
            value = float(candidate.values[parameter.name])
            if not math.isfinite(value):
                raise ValueError(f"{parameter.name} must be finite")
            lower, upper = parameter.bounds
            if not lower <= value <= upper:
                raise ValueError(
                    f"{parameter.name}={value} lies outside bounds {parameter.bounds}"
                )

    def candidate_vector(self, candidate: OptimizationCandidate) -> list[float]:
        return [candidate.values[parameter.name] for parameter in self.parameters]

    def candidates_from_tensor_rows(self, values: Any) -> list[OptimizationCandidate]:
        names = self.names
        return [
            OptimizationCandidate(
                {name: float(value) for name, value in zip(names, row)}
            )
            for row in values
        ]

    @classmethod
    def _validate_parameters(
        cls,
        parameters: Sequence[OptimizationParameter | tuple[str, tuple[float, float]]],
    ) -> tuple[OptimizationParameter, ...]:
        parsed: list[OptimizationParameter] = []
        seen: set[str] = set()
        for entry in parameters:
            parameter = (
                entry
                if isinstance(entry, OptimizationParameter)
                else OptimizationParameter(name=str(entry[0]), bounds=entry[1])
            )
            name = parameter.name.strip()
            if not name:
                raise ValueError("Parameter names must not be empty")
            if name in seen:
                raise ValueError(f"Duplicate optimization parameter: {name}")
            parsed.append(
                OptimizationParameter(
                    name=name,
                    bounds=cls._validate_bounds(name, parameter.bounds),
                )
            )
            seen.add(name)
        if not parsed:
            raise ValueError("At least one optimization parameter is required")
        return tuple(parsed)

    @staticmethod
    def _validate_bounds(name: str, bounds: tuple[float, float]) -> tuple[float, float]:
        if len(bounds) != 2:
            raise ValueError(f"{name} bounds must contain exactly two values")
        lower, upper = (float(bounds[0]), float(bounds[1]))
        if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
            raise ValueError(f"{name} bounds must be finite and strictly increasing")
        return lower, upper

