from __future__ import annotations

import csv
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SafeCandidate:
    channel: int
    command: float
    reason: str
    allowed_step: float
    current_error: float


class AssistedTrialSuggester:
    """Small, dependency-light suggester for one-at-a-time hardware trials.

    This is intentionally conservative: it starts with random space-filling
    candidates inside the safety envelope, then uses a simple surrogate-like
    weighted score estimate plus an exploration bonus. The UI owns hardware
    safety checks and operator approval; this class only proposes and records.
    """

    def __init__(
        self,
        channel_names: list[str],
        log_path: Path,
        seed: int = 1729,
    ) -> None:
        self.channel_names = channel_names
        self.log_path = log_path
        self.random = random.Random(seed)
        self.trials: list[dict[str, Any]] = []

    def propose(
        self,
        channel: int,
        current_command: float,
        current_actual: float,
        target_actual: float,
        min_command: float,
        max_command: float,
        max_step: float,
        min_step: float,
    ) -> SafeCandidate:
        minimum = min(min_command, max_command)
        maximum = max(min_command, max_command)
        current_error = target_actual - current_actual
        allowed_step = self.adaptive_step(
            current_error=current_error,
            max_step=max_step,
            min_step=min_step,
        )
        lower = max(minimum, current_command - allowed_step)
        upper = min(maximum, current_command + allowed_step)
        if lower >= upper:
            command = lower
        else:
            command = self._next_command(
                channel,
                current_command,
                current_error,
                lower,
                upper,
                allowed_step,
            )

        mode = "target-directed seed" if len(self.safe_trials(channel)) < 3 else "score-guided probe"
        reason = f"{mode}; adaptive range +/-{allowed_step:.3f}"
        return SafeCandidate(
            channel=channel,
            command=command,
            reason=reason,
            allowed_step=allowed_step,
            current_error=current_error,
        )

    @staticmethod
    def adaptive_step(
        current_error: float,
        max_step: float,
        min_step: float,
    ) -> float:
        lower = min(max(min_step, 0.0), max_step)
        upper = max(max_step, lower)
        return min(upper, max(lower, abs(current_error)))

    def safe_trials(self, channel: int) -> list[dict[str, Any]]:
        return [trial for trial in self.trials if trial["channel_index"] == channel and trial["safe"]]

    def score_trial(
        self,
        target_actual: float,
        samples: list[float],
    ) -> tuple[float, float, float]:
        actual = sum(samples) / max(len(samples), 1)
        error = abs(target_actual - actual)
        overshoot = max(0.0, max(samples, default=actual) - target_actual)
        score = error + 0.25 * overshoot
        return actual, target_actual - actual, score

    def record_trial(
        self,
        candidate: SafeCandidate,
        target_actual: float,
        actual: float,
        score: float,
        safe: bool,
        message: str,
        dry_run: bool,
    ) -> dict[str, Any]:
        trial = {
            "trial": len(self.trials) + 1,
            "channel_index": candidate.channel,
            "channel": self.channel_names[candidate.channel],
            "candidate": candidate.command,
            "allowed_step": candidate.allowed_step,
            "actual": actual,
            "error": target_actual - actual,
            "score": score,
            "safe": safe,
            "message": message,
            "dry_run": dry_run,
        }
        self.trials.append(trial)
        self.log_trial(trial)
        return trial

    def log_trial(self, trial: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        exists = self.log_path.exists()
        with self.log_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", *trial.keys()])
            if not exists:
                writer.writeheader()
            writer.writerow({"timestamp": f"{time.time():.6f}", **trial})

    def _next_command(
        self,
        channel: int,
        current_command: float,
        current_error: float,
        lower: float,
        upper: float,
        allowed_step: float,
    ) -> float:
        channel_trials = self.safe_trials(channel)
        if len(channel_trials) < 3:
            direction = 1.0 if current_error >= 0.0 else -1.0
            magnitude = self.random.uniform(0.55, 1.0) * allowed_step
            return min(upper, max(lower, current_command + direction * magnitude))

        best = min(channel_trials, key=lambda trial: float(trial["score"]))
        best_command = float(best["candidate"])
        width = max((upper - lower) * 0.35, allowed_step * 0.2)
        probes = [self.random.uniform(lower, upper) for _ in range(24)]
        probes.extend(min(upper, max(lower, best_command + self.random.gauss(0.0, width))) for _ in range(24))
        return min(probes, key=lambda command: self._acquisition_score(channel, command, allowed_step))

    def _acquisition_score(self, channel: int, command: float, max_step: float) -> float:
        channel_trials = self.safe_trials(channel)
        if not channel_trials:
            return 0.0

        weighted_score = 0.0
        total_weight = 0.0
        nearest = float("inf")
        for trial in channel_trials:
            distance = abs(command - float(trial["candidate"]))
            nearest = min(nearest, distance)
            weight = math.exp(-(distance * distance) / max(max_step**2, 1.0))
            weighted_score += weight * float(trial["score"])
            total_weight += weight

        predicted_score = weighted_score / max(total_weight, 1.0e-9)
        exploration_bonus = min(nearest / max(max_step, 1.0), 1.0)
        return predicted_score - 0.2 * exploration_bonus
