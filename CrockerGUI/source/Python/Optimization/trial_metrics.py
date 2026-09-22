"""Shared, time-weighted trial metrics and oscillation-aware PID cost."""
from dataclasses import dataclass, asdict
import math


@dataclass(frozen=True)
class TuningQuality:
    """Performance criteria only; never used as hardware abort limits."""
    settling_tolerance: float = 0.2
    hold_seconds: float = 2.0
    oscillation_amplitude: float = 0.2
    oscillation_min_seconds: float = 10.0
    oscillation_min_cycles: int = 4

    def __post_init__(self):
        for value in asdict(self).values():
            if not math.isfinite(value) or value <= 0:
                raise ValueError('Tuning quality values must be finite and positive')
        if self.oscillation_min_cycles < 2 or int(self.oscillation_min_cycles) != self.oscillation_min_cycles:
            raise ValueError('Oscillation detection requires at least two whole cycles')


@dataclass(frozen=True)
class TrialMetrics:
    settling_time: float
    transient_time: float

    steady_state_error: float
    steady_state_rms: float

    overshoot: float
    oscillation_amplitude: float

    oscillation_cycles: float
    oscillation_penalty: float

    sustained_oscillation: bool
    settled: bool

    entered_tolerance: bool
    control_effort: float

    tolerance: float
    tracking_error: float

    command_movement: float | None
    saturation_time: float | None
    mean_absolute_error: float | None = None
    quality_settings: dict | None = None


def evaluate_trial(samples, target, *, deadband=0.0, hold_seconds=0.5, quality=None):
    """Rows: (seconds, measurement, error, effort[, command, saturated]).

    Four-column response recordings lack actuator data and cannot be scored.
    Integrals use right-endpoint samples; movement is sampled total variation.
    """
    # Reject invalid samples; never let a missing response become a good trial.
    rows = []
    for row in samples:
        if len(row) not in (4, 6) or not all(math.isfinite(v) for v in row):
            raise ValueError("Nonfinite trial sample")
        if rows and len(row) != len(rows[0]):
            raise ValueError("Inconsistent trial sample columns")
        if len(row) == 6 and row[5] not in (0, 1):
            raise ValueError("Saturation flag must be boolean")
        if rows and row[0] < rows[-1][0]:
            raise ValueError("Out-of-order trial samples")
        if rows and row[0] == rows[-1][0]:
            rows[-1] = row
        else:
            rows.append(row)
    if len(rows) < 2 or rows[-1][0] <= rows[0][0]:
        raise ValueError("Not enough fresh samples for trial metrics")
    
    end = rows[-1][0]
    duration = end - rows[0][0]

    tolerance = max(quality.settling_tolerance if quality else 0.1,
                    0.01 * max(abs(target), 1.0), deadband)
    if quality is not None:
        hold_seconds = quality.hold_seconds
    oscillation_threshold = quality.oscillation_amplitude if quality else tolerance
    inside = [abs(row[2]) <= tolerance for row in rows]

    first = next((i for i, value in enumerate(inside) if value), None)
    last_out = max((i for i, value in enumerate(inside) if not value), default=-1)

    settle_index = last_out + 1
    settled = settle_index < len(rows) and end - rows[settle_index][0] >= hold_seconds

    settling = rows[settle_index][0] if settled else end
    transient = rows[first][0] if first is not None else end

    tail_start = end - 0.2 * duration
    weights = [(row, max(0.0, row[0] - max(prev[0], tail_start))) for prev, row in zip(rows, rows[1:])]

    tail_time = sum(weight for _, weight in weights)
    mean_error = sum(abs(row[2]) * weight for row, weight in weights) / tail_time

    rms = math.sqrt(sum(row[2]**2 * weight for row, weight in weights) / tail_time)
    direction = 1 if rows[0][2] >= 0 else -1

    overshoot = max(0.0, max(direction * (row[1]-target) for row in rows))
    effort = sum(abs(row[3]) * (row[0]-prev[0]) for prev, row in zip(rows, rows[1:]))

    tracking = sum(abs(row[2]) * (row[0]-prev[0]) for prev, row in zip(rows, rows[1:]))
    movement = (sum(abs(row[4]-prev[4]) for prev, row in zip(rows, rows[1:]))
                if len(rows[0]) == 6 else None)
    
    saturation = (sum(row[5] * (row[0]-prev[0]) for prev, row in zip(rows, rows[1:]))
                  if len(rows[0]) == 6 else None)
    
    # Hysteretic turning points detect oscillations even away from the setpoint.
    extrema = [rows[0][2]]
    extreme = rows[0][2]
    trend = 0
    initial_low = initial_high = extreme

    for row in rows[1:]:
        value = row[2]
        if trend == 0:
            # Track the initial range, not just distance from the first sample.
            # Otherwise a waveform starting at its midpoint can be missed even
            # when its full peak-to-peak swing exceeds the threshold.
            initial_low = min(initial_low, value)
            initial_high = max(initial_high, value)
            if value - initial_low > 2*oscillation_threshold:
                extrema = [initial_low]
                trend, extreme = 1, value
            elif initial_high - value > 2*oscillation_threshold:
                extrema = [initial_high]
                trend, extreme = -1, value
        elif (value-extreme)*trend >= 0:
            extreme = value
        elif (extreme-value)*trend > 2*oscillation_threshold:
            extrema.append(extreme)
            extreme = value
            trend *= -1

    # Only compare completed swings: the last, partial swing depends on the
    # sampling phase and must not make a persistent oscillation look damped.
    swings = [abs(b-a) for a,b in zip(extrema, extrema[1:]) if abs(b-a) > 2*oscillation_threshold]
    cycles = max(0.0, (len(swings)-1)/2)

    amplitude = max(swings[-4:], default=0.0)/2 if cycles >= 1 else 0.0
    sustained = len(swings) >= 4 and sum(swings[-2:]) >= 0.8 * sum(swings[-4:-2])
    if quality is not None:
        sustained = (sustained and duration >= quality.oscillation_min_seconds
                     and cycles >= quality.oscillation_min_cycles)

    penalty = 10.0 * cycles * amplitude / oscillation_threshold
    if sustained:
        penalty += 100.0 * (1 + amplitude/oscillation_threshold)
        
    return TrialMetrics(settling, transient, mean_error, rms, overshoot,
                        amplitude, cycles, penalty, sustained, settled, first is not None,
                        effort, tolerance, tracking, movement, saturation, tracking / duration,
                        asdict(quality) if quality is not None else None)


def trial_cost(metrics, profile="Balanced"):
    """Five-term PID objective; weights are engineering defaults, not paper values."""

    if metrics.command_movement is None or metrics.saturation_time is None:
        raise ValueError("PID cost requires command and saturation telemetry")
    
    tracking_weight = 3.0 if profile == "Fast response" else 1.0
    precision_weight = 8.0 if profile == "High precision" else 4.0

    movement_weight = 0.08 if profile in {"Low control movement", "Low control effort"} else 0.01
    saturation_weight = 10.0

    oscillation_weight = 2.0 if profile == "Suppress oscillation" else 1.0
    
    return (tracking_weight * metrics.tracking_error
            + precision_weight * metrics.steady_state_error
            + movement_weight * metrics.command_movement
            + saturation_weight * metrics.saturation_time
            + oscillation_weight * metrics.oscillation_penalty)
