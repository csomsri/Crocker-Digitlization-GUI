# -*- coding: utf-8 -*-
"""Deterministic PID engines used by the PID/GA controller tab.

Two controller forms are provided:

``PIDController``
    Conventional signed-error PID retained for compatibility and unit tests.

``AdaptiveDirectionPIDController``
    Paper-schematic controller for beam-current regulation.  It computes the
    signed tracking error ``e = setpoint - measurement`` for diagnostics, then
    controls on the magnitude ``E = abs(e)``.  A separate direction term
    ``d = +1`` or ``-1`` is retained while the error magnitude decreases and is
    reversed when the magnitude increases.  The signed trim-coil increment is
    therefore ``delta_TC = d * limited_PID_magnitude``.

This module has no Qt dependency and can be tested independently from the GUI.
The final hardware loop should still execute in the deterministic control layer
rather than depend on the display refresh timer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class PIDGains:
    kp: float = 0.0
    ki: float = 0.0
    kd: float = 0.0

    def validated(self) -> "PIDGains":
        values = (float(self.kp), float(self.ki), float(self.kd))
        if not all(math.isfinite(v) for v in values):
            raise ValueError("PID gains must be finite")
        return PIDGains(*values)


@dataclass(frozen=True)
class PIDLimits:
    output_min: float = -100.0
    output_max: float = 100.0
    integral_min: float = -100.0
    integral_max: float = 100.0
    derivative_filter_tau: float = 0.05

    def validated(self) -> "PIDLimits":
        out_lo, out_hi = sorted((float(self.output_min), float(self.output_max)))
        int_lo, int_hi = sorted((float(self.integral_min), float(self.integral_max)))
        tau = max(0.0, float(self.derivative_filter_tau))
        values = (out_lo, out_hi, int_lo, int_hi, tau)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("PID limits must be finite")
        return PIDLimits(out_lo, out_hi, int_lo, int_hi, tau)


@dataclass(frozen=True)
class AdaptiveDirectionSettings:
    """Settings for the absolute-error/adaptive-direction PID.

    ``deadband``
        When ``abs(error)`` is at or below this value, the requested trim-coil
        increment is zero and the target is held.

    ``trend_tolerance``
        Changes in error magnitude smaller than this value are treated as
        unchanged.  This avoids reversing direction on small measurement noise.

    ``direction_check_interval``
        Minimum time between direction decisions.  The CNL plant identified in
        the paper has measurable delay, so direction should not be reversed on
        every display sample.
    """

    deadband: float = 0.0
    trend_tolerance: float = 0.0
    direction_check_interval: float = 1.0
    initial_direction: int = 1
    reset_integral_in_deadband: bool = False
    reset_integral_on_direction_change: bool = False

    def validated(self) -> "AdaptiveDirectionSettings":
        deadband = max(0.0, float(self.deadband))
        tolerance = max(0.0, float(self.trend_tolerance))
        interval = max(0.0, float(self.direction_check_interval))
        values = (deadband, tolerance, interval)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Adaptive PID settings must be finite")
        direction = 1 if int(self.initial_direction) >= 0 else -1
        return AdaptiveDirectionSettings(
            deadband=deadband,
            trend_tolerance=tolerance,
            direction_check_interval=interval,
            initial_direction=direction,
            reset_integral_in_deadband=bool(self.reset_integral_in_deadband),
            reset_integral_on_direction_change=bool(
                self.reset_integral_on_direction_change
            ),
        )


@dataclass(frozen=True)
class PIDResult:
    """One controller evaluation.

    The first six fields preserve the original public result interface.  The
    remaining fields expose the paper-specific magnitude and direction logic to
    the GUI and logger without requiring duplicate calculations.
    """

    output: float
    error: float
    proportional: float
    integral: float
    derivative: float
    saturated: bool
    error_magnitude: float = 0.0
    pid_magnitude: float = 0.0
    direction: int = 0
    error_trend: str = "UNKNOWN"
    direction_changed: bool = False
    in_deadband: bool = False


class PIDController:
    """Conventional signed-error PID with derivative-on-measurement.

    This class is retained because other development tests may still use a
    normal signed PID.  The beam-control page uses
    :class:`AdaptiveDirectionPIDController` below.
    """

    def __init__(
        self,
        gains: PIDGains | None = None,
        limits: PIDLimits | None = None,
    ):
        self.gains = (gains or PIDGains()).validated()
        self.limits = (limits or PIDLimits()).validated()
        self.reset()

    def set_gains(self, gains: PIDGains) -> None:
        self.gains = gains.validated()

    def set_limits(self, limits: PIDLimits) -> None:
        self.limits = limits.validated()
        self._integral_state = self._clamp(
            self._integral_state,
            self.limits.integral_min,
            self.limits.integral_max,
        )

    def reset(self, measurement: float | None = None) -> None:
        self._integral_state = 0.0
        self._previous_measurement = None if measurement is None else float(measurement)
        self._filtered_derivative = 0.0
        self._last_result = PIDResult(0.0, 0.0, 0.0, 0.0, 0.0, False)

    @property
    def last_result(self) -> PIDResult:
        return self._last_result

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, value))

    def update(
        self,
        setpoint: float,
        measurement: float,
        dt: float,
        *,
        feedforward: float = 0.0,
        hold_integrator: bool = False,
    ) -> PIDResult:
        setpoint = float(setpoint)
        measurement = float(measurement)
        dt = float(dt)
        feedforward = float(feedforward)
        if not all(math.isfinite(v) for v in (setpoint, measurement, dt, feedforward)):
            raise ValueError("PID inputs must be finite")
        if dt <= 0.0:
            raise ValueError("PID dt must be greater than zero")

        gains = self.gains
        limits = self.limits
        error = setpoint - measurement
        proportional = gains.kp * error

        if self._previous_measurement is None:
            raw_derivative = 0.0
        else:
            # Derivative on measurement avoids a large kick when setpoint moves.
            raw_derivative = -(measurement - self._previous_measurement) / dt

        tau = limits.derivative_filter_tau
        if tau <= 0.0:
            self._filtered_derivative = raw_derivative
        else:
            alpha = dt / (tau + dt)
            self._filtered_derivative += alpha * (
                raw_derivative - self._filtered_derivative
            )
        derivative = gains.kd * self._filtered_derivative

        candidate_integral = self._integral_state
        if not hold_integrator:
            candidate_integral += gains.ki * error * dt
            candidate_integral = self._clamp(
                candidate_integral,
                limits.integral_min,
                limits.integral_max,
            )

        unsaturated = proportional + candidate_integral + derivative + feedforward
        output = self._clamp(unsaturated, limits.output_min, limits.output_max)
        saturated = not math.isclose(
            output, unsaturated, rel_tol=0.0, abs_tol=1e-12
        )

        # Conditional integration: accept the new integral when not saturated,
        # or when the signed error would drive saturation back toward range.
        drives_back = (
            (unsaturated > limits.output_max and error < 0.0)
            or (unsaturated < limits.output_min and error > 0.0)
        )
        if not hold_integrator and (not saturated or drives_back):
            self._integral_state = candidate_integral
        else:
            unsaturated = (
                proportional + self._integral_state + derivative + feedforward
            )
            output = self._clamp(unsaturated, limits.output_min, limits.output_max)
            saturated = not math.isclose(
                output, unsaturated, rel_tol=0.0, abs_tol=1e-12
            )

        self._previous_measurement = measurement
        self._last_result = PIDResult(
            output=output,
            error=error,
            proportional=proportional,
            integral=self._integral_state,
            derivative=derivative,
            saturated=saturated,
            error_magnitude=abs(error),
            pid_magnitude=abs(output),
            direction=1 if output > 0.0 else (-1 if output < 0.0 else 0),
            error_trend="SIGNED PID",
        )
        return self._last_result


class AdaptiveDirectionPIDController:
    """Absolute-error PID with a separately learned actuator direction.

    The key distinction from a conventional PID is intentional:

    * The signed error ``e`` is retained for display and logging.
    * PID magnitude is calculated from ``E = abs(e)``.
    * The actuator sign is the independent state ``direction``.
    * If a completed actuator move makes ``E`` smaller, direction is kept.
    * If it makes ``E`` larger, direction is reversed.

    This lets the controller work when the local TC-to-beam-current response can
    have either sign.  A raw error sign change alone does not reverse the move;
    the direction changes only when the *magnitude* stops improving.
    """

    def __init__(
        self,
        gains: PIDGains | None = None,
        limits: PIDLimits | None = None,
        settings: AdaptiveDirectionSettings | None = None,
    ):
        self.gains = (gains or PIDGains()).validated()
        self.limits = (limits or PIDLimits(output_min=0.0)).validated()
        self.settings = (settings or AdaptiveDirectionSettings()).validated()
        self.reset()

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, value))

    @staticmethod
    def _trend(current: float, previous: float | None, tolerance: float) -> str:
        if previous is None:
            return "INITIALIZING"
        change = current - previous
        if change > tolerance:
            return "INCREASING"
        if change < -tolerance:
            return "DECREASING"
        return "STEADY"

    def set_gains(self, gains: PIDGains) -> None:
        self.gains = gains.validated()

    def set_limits(self, limits: PIDLimits) -> None:
        self.limits = limits.validated()
        int_lo, int_hi = self._integral_bounds()
        self._integral_state = self._clamp(
            self._integral_state,
            int_lo,
            int_hi,
        )

    def set_settings(self, settings: AdaptiveDirectionSettings) -> None:
        self.settings = settings.validated()
        if self._direction not in (-1, 1):
            self._direction = self.settings.initial_direction

    def _magnitude_bounds(self) -> tuple[float, float]:
        # The adaptive controller interprets output bounds as a nonnegative
        # magnitude.  A legacy negative lower field therefore becomes zero.
        lower = max(0.0, float(self.limits.output_min))
        upper = max(lower, float(self.limits.output_max))
        return lower, upper

    def _integral_bounds(self) -> tuple[float, float]:
        lower = max(0.0, float(self.limits.integral_min))
        upper = max(lower, float(self.limits.integral_max))
        return lower, upper

    def reset(
        self,
        *,
        setpoint: float | None = None,
        measurement: float | None = None,
        direction: int | None = None,
    ) -> None:
        self._integral_state = 0.0
        self._filtered_derivative = 0.0
        self._direction = (
            self.settings.initial_direction
            if direction is None
            else (1 if int(direction) >= 0 else -1)
        )
        self._previous_error_magnitude: float | None = None
        self._direction_reference_magnitude: float | None = None
        self._direction_elapsed = 0.0
        self._last_setpoint: float | None = None

        if setpoint is not None and measurement is not None:
            setpoint_f = float(setpoint)
            measurement_f = float(measurement)
            if math.isfinite(setpoint_f) and math.isfinite(measurement_f):
                magnitude = abs(setpoint_f - measurement_f)
                self._previous_error_magnitude = magnitude
                self._direction_reference_magnitude = magnitude
                self._last_setpoint = setpoint_f

        self._last_result = PIDResult(
            output=0.0,
            error=0.0,
            proportional=0.0,
            integral=0.0,
            derivative=0.0,
            saturated=False,
            direction=self._direction,
            error_trend="RESET",
        )

    @property
    def last_result(self) -> PIDResult:
        return self._last_result

    @property
    def direction(self) -> int:
        return self._direction

    def update(
        self,
        setpoint: float,
        measurement: float,
        dt: float,
        *,
        hold_integrator: bool = False,
    ) -> PIDResult:
        setpoint = float(setpoint)
        measurement = float(measurement)
        dt = float(dt)
        if not all(math.isfinite(v) for v in (setpoint, measurement, dt)):
            raise ValueError("Adaptive PID inputs must be finite")
        if dt <= 0.0:
            raise ValueError("Adaptive PID dt must be greater than zero")

        gains = self.gains
        limits = self.limits
        settings = self.settings

        signed_error = setpoint - measurement
        error_magnitude = abs(signed_error)

        setpoint_changed = (
            self._last_setpoint is not None
            and not math.isclose(
                setpoint,
                self._last_setpoint,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        )
        if self._last_setpoint is None or setpoint_changed:
            # A new reference invalidates both the derivative history and the
            # before/after comparison used to learn direction.
            self._previous_error_magnitude = error_magnitude
            self._direction_reference_magnitude = error_magnitude
            self._direction_elapsed = 0.0
            self._filtered_derivative = 0.0
            sample_trend = "SETPOINT CHANGED" if setpoint_changed else "INITIALIZING"
        else:
            sample_trend = self._trend(
                error_magnitude,
                self._previous_error_magnitude,
                settings.trend_tolerance,
            )

        in_deadband = error_magnitude <= settings.deadband
        if in_deadband:
            if settings.reset_integral_in_deadband:
                self._integral_state = 0.0
            # Figure 3 holds the TC target in the deadband.  Since ``output`` is
            # a per-sample target increment, zero means hold the current target.
            self._filtered_derivative = 0.0
            self._previous_error_magnitude = error_magnitude
            self._direction_reference_magnitude = error_magnitude
            self._direction_elapsed = 0.0
            self._last_setpoint = setpoint
            self._last_result = PIDResult(
                output=0.0,
                error=signed_error,
                proportional=0.0,
                integral=self._integral_state,
                derivative=0.0,
                saturated=False,
                error_magnitude=error_magnitude,
                pid_magnitude=0.0,
                direction=self._direction,
                error_trend="DEADBAND",
                direction_changed=False,
                in_deadband=True,
            )
            return self._last_result

        direction_changed = False
        self._direction_elapsed += dt
        if self._direction_reference_magnitude is None:
            self._direction_reference_magnitude = error_magnitude
            self._direction_elapsed = 0.0
        elif self._direction_elapsed >= settings.direction_check_interval:
            direction_delta = error_magnitude - self._direction_reference_magnitude
            if direction_delta > settings.trend_tolerance:
                # The last direction made |error| worse, regardless of whether
                # the signed error itself is positive or negative.
                self._direction *= -1
                direction_changed = True
                sample_trend = "INCREASING"
                if settings.reset_integral_on_direction_change:
                    self._integral_state = 0.0
            elif direction_delta < -settings.trend_tolerance:
                sample_trend = "DECREASING"
            else:
                sample_trend = "STEADY"
            self._direction_reference_magnitude = error_magnitude
            self._direction_elapsed = 0.0

        if self._previous_error_magnitude is None or setpoint_changed:
            raw_derivative = 0.0
        else:
            # The derivative is intentionally calculated on |error|, matching
            # the magnitude-based flow in the paper schematic.
            raw_derivative = (
                error_magnitude - self._previous_error_magnitude
            ) / dt

        tau = limits.derivative_filter_tau
        if tau <= 0.0:
            self._filtered_derivative = raw_derivative
        else:
            alpha = dt / (tau + dt)
            self._filtered_derivative += alpha * (
                raw_derivative - self._filtered_derivative
            )

        proportional = gains.kp * error_magnitude
        derivative = gains.kd * self._filtered_derivative

        int_lo, int_hi = self._integral_bounds()
        candidate_integral = self._integral_state
        if not hold_integrator:
            candidate_integral += gains.ki * error_magnitude * dt
            candidate_integral = self._clamp(candidate_integral, int_lo, int_hi)

        mag_lo, mag_hi = self._magnitude_bounds()
        unsaturated_magnitude = proportional + candidate_integral + derivative
        pid_magnitude = self._clamp(unsaturated_magnitude, mag_lo, mag_hi)
        saturated = not math.isclose(
            pid_magnitude,
            unsaturated_magnitude,
            rel_tol=0.0,
            abs_tol=1e-12,
        )

        # With E >= 0 and Ki >= 0, integration can only increase magnitude.
        # Retain it when unsaturated, and also when a negative derivative has
        # temporarily clamped magnitude at the lower limit.  Reject it at the
        # upper limit to prevent windup.
        lower_saturation_can_recover = unsaturated_magnitude < mag_lo
        if not hold_integrator and (not saturated or lower_saturation_can_recover):
            self._integral_state = candidate_integral
        else:
            unsaturated_magnitude = (
                proportional + self._integral_state + derivative
            )
            pid_magnitude = self._clamp(unsaturated_magnitude, mag_lo, mag_hi)
            saturated = not math.isclose(
                pid_magnitude,
                unsaturated_magnitude,
                rel_tol=0.0,
                abs_tol=1e-12,
            )

        signed_output = float(self._direction) * pid_magnitude

        self._previous_error_magnitude = error_magnitude
        self._last_setpoint = setpoint
        self._last_result = PIDResult(
            output=signed_output,
            error=signed_error,
            proportional=proportional,
            integral=self._integral_state,
            derivative=derivative,
            saturated=saturated,
            error_magnitude=error_magnitude,
            pid_magnitude=pid_magnitude,
            direction=self._direction,
            error_trend=sample_trend,
            direction_changed=direction_changed,
            in_deadband=False,
        )
        return self._last_result


__all__ = [
    "PIDGains",
    "PIDLimits",
    "AdaptiveDirectionSettings",
    "PIDResult",
    "PIDController",
    "AdaptiveDirectionPIDController",
]
