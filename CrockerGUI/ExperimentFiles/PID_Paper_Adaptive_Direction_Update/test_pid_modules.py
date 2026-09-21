# -*- coding: utf-8 -*-
"""Dependency-free smoke tests for the conventional PID, adaptive PID, and GA.

Run from the project directory with::

    python test_pid_modules.py

The adaptive-direction tests intentionally exercise positive and negative signed
errors.  Direction decisions are based only on the change in ``abs(error)``.
"""

from __future__ import annotations

import math

from ga_pid_tuner import GAPIDTuner, GATuningConfig, GainBounds
from pid_controller import (
    AdaptiveDirectionPIDController,
    AdaptiveDirectionSettings,
    PIDController,
    PIDGains,
    PIDLimits,
)


def test_pid_engine() -> None:
    """Retain the original signed-PID backend smoke test."""
    pid = PIDController(
        PIDGains(kp=1.2, ki=0.4, kd=0.03),
        PIDLimits(output_min=-10.0, output_max=10.0),
    )
    measurement = 0.0
    dt = 0.01
    for _ in range(400):
        result = pid.update(setpoint=1.0, measurement=measurement, dt=dt)
        # Simple first-order demonstration plant.
        measurement += dt * (-measurement + result.output)
    assert 0.75 < measurement < 1.25, measurement


def _adaptive_controller(
    *,
    direction: int = 1,
    deadband: float = 0.0,
    tolerance: float = 0.0,
    check_interval: float = 1.0,
) -> AdaptiveDirectionPIDController:
    return AdaptiveDirectionPIDController(
        gains=PIDGains(kp=0.1, ki=0.0, kd=0.0),
        limits=PIDLimits(
            output_min=0.0,
            output_max=10.0,
            integral_min=0.0,
            integral_max=10.0,
            derivative_filter_tau=0.0,
        ),
        settings=AdaptiveDirectionSettings(
            deadband=deadband,
            trend_tolerance=tolerance,
            direction_check_interval=check_interval,
            initial_direction=direction,
        ),
    )


def test_adaptive_direction_uses_absolute_error() -> None:
    """A signed-error zero crossing must not by itself reverse direction.

    Sequence at a 10 nA setpoint:
      +10 nA error -> +8 nA error -> -2 nA error -> -4 nA error
      |10|         -> |8|         -> |2|         -> |4|

    The direction is retained through the signed-error crossing because the
    magnitude is still decreasing.  It reverses only at the final sample, where
    the magnitude increases from 2 nA to 4 nA.
    """
    pid = _adaptive_controller(direction=1, check_interval=1.0)
    pid.reset(setpoint=10.0, measurement=0.0, direction=1)

    result = pid.update(setpoint=10.0, measurement=2.0, dt=1.0)
    assert result.error == 8.0
    assert result.error_magnitude == 8.0
    assert result.error_trend == "DECREASING"
    assert result.direction == 1
    assert not result.direction_changed

    result = pid.update(setpoint=10.0, measurement=12.0, dt=1.0)
    assert result.error == -2.0
    assert result.error_magnitude == 2.0
    assert result.error_trend == "DECREASING"
    assert result.direction == 1, "signed-error crossing incorrectly changed direction"
    assert result.output > 0.0

    result = pid.update(setpoint=10.0, measurement=14.0, dt=1.0)
    assert result.error == -4.0
    assert result.error_magnitude == 4.0
    assert result.error_trend == "INCREASING"
    assert result.direction == -1
    assert result.direction_changed
    assert result.output < 0.0


def test_adaptive_direction_with_negative_error() -> None:
    """The same magnitude rule applies when the signed error starts negative."""
    pid = _adaptive_controller(direction=1, check_interval=1.0)
    pid.reset(setpoint=10.0, measurement=20.0, direction=1)

    result = pid.update(setpoint=10.0, measurement=18.0, dt=1.0)
    assert result.error == -8.0
    assert result.error_magnitude == 8.0
    assert result.error_trend == "DECREASING"
    assert result.direction == 1

    result = pid.update(setpoint=10.0, measurement=22.0, dt=1.0)
    assert result.error == -12.0
    assert result.error_magnitude == 12.0
    assert result.error_trend == "INCREASING"
    assert result.direction == -1
    assert result.direction_changed


def test_direction_waits_for_comparison_interval() -> None:
    """Plant-delay protection prevents a direction reversal on every sample."""
    pid = _adaptive_controller(direction=1, check_interval=2.0)
    pid.reset(setpoint=10.0, measurement=0.0, direction=1)

    # |e| is worse, but only one second has elapsed, so direction is retained.
    result = pid.update(setpoint=10.0, measurement=-1.0, dt=1.0)
    assert result.error_magnitude == 11.0
    assert result.direction == 1
    assert not result.direction_changed

    # At the two-second comparison point, |e| is still worse than the reference.
    result = pid.update(setpoint=10.0, measurement=-1.5, dt=1.0)
    assert result.error_magnitude == 11.5
    assert result.direction == -1
    assert result.direction_changed


def test_deadband_holds_target() -> None:
    pid = _adaptive_controller(direction=-1, deadband=0.5, check_interval=1.0)
    pid.reset(setpoint=10.0, measurement=9.8, direction=-1)
    result = pid.update(setpoint=10.0, measurement=9.8, dt=1.0)
    assert result.in_deadband
    assert result.error_magnitude <= 0.5
    assert result.output == 0.0
    assert result.pid_magnitude == 0.0
    assert result.error_trend == "DEADBAND"


def test_trend_tolerance_rejects_small_noise() -> None:
    pid = _adaptive_controller(direction=1, tolerance=0.05, check_interval=1.0)
    pid.reset(setpoint=10.0, measurement=0.0, direction=1)

    # The magnitude changes by only 0.02 nA, below the 0.05 nA tolerance.
    result = pid.update(setpoint=10.0, measurement=-0.02, dt=1.0)
    assert math.isclose(result.error_magnitude, 10.02)
    assert result.error_trend == "STEADY"
    assert result.direction == 1
    assert not result.direction_changed


def test_unknown_plant_sign_is_learned() -> None:
    """The adaptive rule converges for either local TC-to-beam response sign."""
    for plant_gain in (1.0, -1.0):
        pid = AdaptiveDirectionPIDController(
            gains=PIDGains(kp=0.10, ki=0.0, kd=0.0),
            limits=PIDLimits(
                output_min=0.0,
                output_max=1.0,
                integral_min=0.0,
                integral_max=1.0,
                derivative_filter_tau=0.0,
            ),
            settings=AdaptiveDirectionSettings(
                deadband=0.05,
                trend_tolerance=0.001,
                direction_check_interval=0.1,
                initial_direction=1,
            ),
        )
        beam_setpoint = 1.0
        tc_target = 0.0
        beam_measurement = plant_gain * tc_target
        pid.reset(
            setpoint=beam_setpoint,
            measurement=beam_measurement,
            direction=1,
        )

        result = pid.last_result
        for _ in range(200):
            result = pid.update(
                setpoint=beam_setpoint,
                measurement=beam_measurement,
                dt=0.1,
            )
            tc_target += result.output
            beam_measurement = plant_gain * tc_target
            if result.in_deadband:
                break

        assert abs(beam_setpoint - beam_measurement) <= 0.06, (
            plant_gain,
            beam_measurement,
            result,
        )
        expected_direction = 1 if plant_gain > 0.0 else -1
        assert result.direction == expected_direction


def test_ga_engine() -> None:
    tuner = GAPIDTuner(
        bounds=GainBounds(kp=(0.0, 2.0), ki=(0.0, 2.0), kd=(0.0, 1.0)),
        config=GATuningConfig(
            population_size=12,
            generations=12,
            random_seed=7,
        ),
    )
    candidate = tuner.initialize(PIDGains(0.0, 0.0, 0.0))
    while not tuner.finished:
        gains = candidate.gains
        # Synthetic objective only: optimum is approximately (1.1, 0.7, 0.25).
        fitness = (
            (gains.kp - 1.1) ** 2
            + (gains.ki - 0.7) ** 2
            + (gains.kd - 0.25) ** 2
        )
        candidate = tuner.submit_fitness(fitness)
        if candidate is None and not tuner.finished:
            candidate = tuner.current_candidate()

    best = tuner.best_candidate()
    assert best is not None
    assert float(best.fitness) < 0.08, best


def run_all_tests() -> None:
    test_pid_engine()
    test_adaptive_direction_uses_absolute_error()
    test_adaptive_direction_with_negative_error()
    test_direction_waits_for_comparison_interval()
    test_deadband_holds_target()
    test_trend_tolerance_rejects_small_noise()
    test_unknown_plant_sign_is_learned()
    test_ga_engine()


if __name__ == "__main__":
    run_all_tests()
    print("Conventional PID, adaptive-direction PID, and GA backend tests passed.")
