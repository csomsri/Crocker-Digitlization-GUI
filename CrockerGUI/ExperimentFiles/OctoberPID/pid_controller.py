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
    reversed when the magnitude increases. The revised adaptive engine treats
    the PID magnitude as a trim-coil movement rate and returns the time-scaled
    increment ``delta_TC = d * rate_magnitude * dt``.

This module has no Qt dependency and can be tested independently from the GUI.
The final hardware loop should still execute in the deterministic control layer
rather than depend on the display refresh timer.
"""

from __future__ import annotations

import math
from collections import deque
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

    ``direction_check_interval``
        Duration of one error-trend observation window in legacy window mode.
        This interval is not used when ``direction_each_update`` is enabled.

    ``direction_confirmations``
        Number of consecutive worsening windows required before the trim-coil
        direction is reversed. The default value of two suppresses chatter while
        still allowing a 0.5 s direction window to reverse after about 1 s.

    ``minimum_direction_samples``
        Minimum number of fresh beam samples required in a direction window.
        This prevents a single delayed sample from making a direction decision.

    ``integral_window_multiplier``
        Legacy fallback used only when ``integral_memory_s`` is set to zero.
        It keeps compatibility with earlier controller files.

    ``max_control_dt``
        Maximum time step used in PID mathematics. A delayed packet therefore
        cannot create one abnormally large trim-coil increment.

    ``integral_memory_s``
        Duration of the moving integral window. Only error measured during the
        most recent interval contributes to the integral. The default is 20 s,
        so old error leaves continuously instead of being cleared by a sudden
        periodic reset.

    The active GUI sets ``direction_each_update=True`` and compares each fresh
    averaged error directly with the preceding value. With this setting false,
    the legacy branch compares complete window means and uses the configured
    interval, minimum sample count, and reversal confirmations.
    """

    deadband: float = 0.0
    direction_check_interval: float = 1.0
    initial_direction: int = 1
    reset_integral_in_deadband: bool = False
    reset_integral_on_direction_change: bool = False
    direction_confirmations: int = 2
    minimum_direction_samples: int = 3
    integral_window_multiplier: float = 2.0
    max_control_dt: float = 0.25
    integral_memory_s: float = 20.0
    # The revised GUI enables this: one direction comparison per fresh mean.
    # Legacy callers retain their existing window-based behavior by default.
    direction_each_update: bool = False

    def validated(self) -> "AdaptiveDirectionSettings":
        deadband = max(0.0, float(self.deadband))
        interval = max(0.0, float(self.direction_check_interval))
        confirmations = max(1, int(self.direction_confirmations))
        minimum_samples = max(1, int(self.minimum_direction_samples))
        integral_multiplier = max(1.0, float(self.integral_window_multiplier))
        max_control_dt = max(1.0e-4, float(self.max_control_dt))
        integral_memory_s = max(0.0, float(self.integral_memory_s))
        values = (
            deadband,
            interval,
            integral_multiplier,
            max_control_dt,
            integral_memory_s,
        )
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Adaptive PID settings must be finite")
        direction = 1 if int(self.initial_direction) >= 0 else -1
        return AdaptiveDirectionSettings(
            deadband=deadband,
            direction_check_interval=interval,
            initial_direction=direction,
            reset_integral_in_deadband=bool(self.reset_integral_in_deadband),
            reset_integral_on_direction_change=bool(
                self.reset_integral_on_direction_change
            ),
            direction_confirmations=confirmations,
            minimum_direction_samples=minimum_samples,
            integral_window_multiplier=integral_multiplier,
            max_control_dt=max_control_dt,
            integral_memory_s=integral_memory_s,
            direction_each_update=bool(self.direction_each_update),
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
    """Stable adaptive-direction PID for trim-coil target increments.

    The original implementation calculated a position-form PID magnitude and
    then the GUI added that complete value to the trim-coil target on every
    sample. That effectively accumulated the proportional term and could create
    a large limit cycle after several minutes.

    This revision keeps the user's intended direction rule but changes the
    controller output to a *time-scaled target increment*:

    ``error = setpoint - measurement``
    ``E = abs(error)``
    ``rate = Kp*E + Ki*window_integral(E) + damping_D``
    ``delta_TC = direction * rate * dt``

    Therefore the same gains produce approximately the same trim-coil movement
    per second when the beam-sample rate changes. The GUI can continue to use
    ``target_next = target_current + result.output`` without modification.

    With ``direction_each_update=True``, each fresh averaged ``E`` is compared
    directly with the previous value: an increase reverses direction; a decrease
    or exact equality keeps it. The legacy mode instead compares time-weighted
    window means directly and retains its configured confirmation count.
    Integral memory is a 20 s moving window by default: only recent error
    contributes, and old error leaves continuously as new samples arrive. The
    legacy mode clears it on reversal; the per-update mode uses the existing
    ``reset_integral_on_direction_change`` setting.

    ``PIDLimits.output_max`` remains a final emergency limit on one returned
    target increment. ``output_min`` is intentionally ignored by this adaptive
    controller so a forced minimum step cannot sustain a limit cycle near the
    setpoint. The conventional ``PIDController`` above is unchanged.
    """

    def __init__(
        self,
        gains: PIDGains | None = None,
        limits: PIDLimits | None = None,
        settings: AdaptiveDirectionSettings | None = None,
    ):
        self.gains = self._validated_adaptive_gains(gains or PIDGains())
        self.limits = (limits or PIDLimits(output_min=0.0)).validated()
        self.settings = (settings or AdaptiveDirectionSettings()).validated()
        self.reset()

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, value))

    @staticmethod
    def _validated_adaptive_gains(gains: PIDGains) -> PIDGains:
        validated = gains.validated()
        if validated.kp < 0.0 or validated.ki < 0.0 or validated.kd < 0.0:
            raise ValueError(
                "Adaptive-direction PID gains Kp, Ki and Kd must be nonnegative"
            )
        return validated

    @staticmethod
    def _trend(current: float, previous: float | None) -> str:
        if previous is None:
            return "INITIALIZING"
        if current > previous:
            return "INCREASING"
        if current < previous:
            return "DECREASING"
        return "STEADY"

    def set_gains(self, gains: PIDGains) -> None:
        self.gains = self._validated_adaptive_gains(gains)

    def set_limits(self, limits: PIDLimits) -> None:
        # The limits object is retained for complete backwards compatibility.
        # In adaptive mode output_max is a final emergency per-update guard;
        # output_min is not forced because a nonzero minimum causes chatter.
        self.limits = limits.validated()

    def set_settings(self, settings: AdaptiveDirectionSettings) -> None:
        self.settings = settings.validated()
        if self._direction not in (-1, 1):
            self._direction = self.settings.initial_direction
        self._trim_integral_history(self._integral_window_s())

    def _integral_window_s(self) -> float:
        """Return the finite integral-memory horizon in seconds.

        A positive ``integral_memory_s`` selects a fixed moving window. Setting
        it to zero restores the earlier compatibility behavior in which the
        horizon is derived from the direction-check interval.
        """
        memory_s = float(self.settings.integral_memory_s)
        if memory_s > 0.0:
            return max(0.1, memory_s)
        return max(
            1.0,
            self.settings.integral_window_multiplier
            * max(0.0, self.settings.direction_check_interval),
        )

    def _clear_integral(self) -> None:
        self._integral_history.clear()
        self._integral_area = 0.0
        self._integral_elapsed = 0.0

    def _append_integral_sample(self, error_magnitude: float, dt: float) -> None:
        duration = max(0.0, float(dt))
        magnitude = max(0.0, float(error_magnitude))
        if duration <= 0.0:
            return
        self._integral_history.append([duration, magnitude])
        self._integral_elapsed += duration
        self._integral_area += duration * magnitude
        self._trim_integral_history(self._integral_window_s())

    def _remove_last_integral_sample(self) -> None:
        if not self._integral_history:
            return
        duration, magnitude = self._integral_history.pop()
        self._integral_elapsed = max(0.0, self._integral_elapsed - duration)
        self._integral_area = max(
            0.0,
            self._integral_area - duration * magnitude,
        )

    def _trim_integral_history(self, window_s: float) -> None:
        keep = max(1.0e-6, float(window_s))
        while self._integral_history and self._integral_elapsed > keep:
            excess = self._integral_elapsed - keep
            duration, magnitude = self._integral_history[0]
            if duration <= excess + 1.0e-12:
                self._integral_history.popleft()
                self._integral_elapsed -= duration
                self._integral_area -= duration * magnitude
            else:
                self._integral_history[0][0] = duration - excess
                self._integral_elapsed -= excess
                self._integral_area -= excess * magnitude
                break
        self._integral_elapsed = max(0.0, self._integral_elapsed)
        self._integral_area = max(0.0, self._integral_area)

    def _clear_direction_window(self) -> None:
        self._direction_window_area = 0.0
        self._direction_window_elapsed = 0.0
        self._direction_window_samples = 0

    def _append_direction_sample(self, error_magnitude: float, dt: float) -> None:
        duration = max(0.0, float(dt))
        if duration <= 0.0:
            return
        self._direction_window_area += max(0.0, error_magnitude) * duration
        self._direction_window_elapsed += duration
        self._direction_window_samples += 1

    def _evaluate_direction_window(self) -> tuple[str | None, bool]:
        settings = self.settings
        required_interval = max(
            settings.direction_check_interval,
            min(settings.max_control_dt, 0.05),
        )
        if self._direction_window_elapsed < required_interval:
            return None, False
        if self._direction_window_samples < settings.minimum_direction_samples:
            return None, False

        mean_error = (
            self._direction_window_area / self._direction_window_elapsed
        )
        previous_mean = self._previous_direction_window_mean
        # Compare the window means directly. The beam-error deadband controls
        # zero output; it is not a threshold for changes in error magnitude.
        trend = self._trend(mean_error, previous_mean)
        direction_changed = False

        if previous_mean is None:
            self._worsening_windows = 0
            trend = "INITIALIZING"
            self._previous_direction_window_mean = mean_error
        elif trend == "INCREASING":
            self._worsening_windows += 1
            if self._worsening_windows >= settings.direction_confirmations:
                self._direction *= -1
                direction_changed = True
                self._worsening_windows = 0
                # Integral memory was accumulated while the opposite actuator
                # sign was active. Applying it after reversal caused the large
                # high/low limit cycle seen in long tests, so it is always reset.
                self._clear_integral()
                self._filtered_derivative = 0.0
                # The first average under the new direction is compared against
                # the condition that triggered the reversal.
                self._previous_direction_window_mean = mean_error
            # Before confirmation, retain the same reference. This lets gradual
            # worsening accumulate instead of being hidden by moving the
            # reference a small amount on every window.
        elif trend == "DECREASING":
            self._worsening_windows = 0
            # Improvement establishes a new best reference for the current
            # direction. Future worsening is measured from this lower value.
            self._previous_direction_window_mean = mean_error
        else:
            # A steady window neither moves the reference nor confirms a
            # reversal. Keeping the reference also detects slow cumulative drift.
            self._worsening_windows = 0

        self._clear_direction_window()
        return trend, direction_changed

    def reset(
        self,
        *,
        setpoint: float | None = None,
        measurement: float | None = None,
        direction: int | None = None,
    ) -> None:
        self._filtered_derivative = 0.0
        self._direction = (
            self.settings.initial_direction
            if direction is None
            else (1 if int(direction) >= 0 else -1)
        )
        self._previous_error_magnitude: float | None = None
        self._previous_direction_window_mean: float | None = None
        self._worsening_windows = 0
        self._last_setpoint: float | None = None
        self._integral_history: deque[list[float]] = deque()
        self._integral_area = 0.0
        self._integral_elapsed = 0.0
        self._direction_window_area = 0.0
        self._direction_window_elapsed = 0.0
        self._direction_window_samples = 0

        if setpoint is not None and measurement is not None:
            setpoint_f = float(setpoint)
            measurement_f = float(measurement)
            if math.isfinite(setpoint_f) and math.isfinite(measurement_f):
                magnitude = abs(setpoint_f - measurement_f)
                self._previous_error_magnitude = magnitude
                self._previous_direction_window_mean = magnitude
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

        # A delayed packet must not create one large target jump. Timing,
        # derivative, integral, and rate-to-increment conversion all use the
        # same bounded control step.
        # In the simplified mode use real elapsed time in I/D mathematics.
        # Only the commanded increment is capped to one configured loop interval;
        # delayed feedback must never create a large catch-up target jump.
        control_dt = dt if settings.direction_each_update else min(dt, settings.max_control_dt)
        step_dt = min(dt, settings.max_control_dt)
        long_gap = dt > 2.0 * settings.max_control_dt

        signed_error = setpoint - measurement
        error_magnitude = abs(signed_error)
        setpoint_changed = (
            self._last_setpoint is not None
            and not math.isclose(
                setpoint,
                self._last_setpoint,
                rel_tol=0.0,
                abs_tol=1.0e-12,
            )
        )

        if self._last_setpoint is None or setpoint_changed:
            self._previous_error_magnitude = error_magnitude
            self._previous_direction_window_mean = error_magnitude
            self._worsening_windows = 0
            self._clear_direction_window()
            self._clear_integral()
            self._filtered_derivative = 0.0
            sample_trend = (
                "SETPOINT CHANGED" if setpoint_changed else "INITIALIZING"
            )
        else:
            sample_trend = self._trend(
                error_magnitude,
                self._previous_error_magnitude,
            )

        in_deadband = error_magnitude <= settings.deadband or (
            settings.direction_each_update and math.isclose(
                error_magnitude, settings.deadband, rel_tol=1e-12, abs_tol=1e-12))
        if in_deadband:
            if settings.reset_integral_in_deadband:
                self._clear_integral()
            else:
                # Add zero-error time so finite integral memory naturally ages
                # out even when hard reset is not selected in the GUI.
                self._append_integral_sample(0.0, control_dt)
            self._filtered_derivative = 0.0
            self._previous_error_magnitude = error_magnitude
            self._previous_direction_window_mean = error_magnitude
            self._worsening_windows = 0
            self._clear_direction_window()
            self._last_setpoint = setpoint
            self._last_result = PIDResult(
                output=0.0,
                error=signed_error,
                proportional=0.0,
                integral=0.0,
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

        if settings.direction_each_update:
            # Measurement is already a complete beam-input average. Do not
            # average absolute errors again or run a second direction timer.
            direction_changed = sample_trend == "INCREASING"
            if direction_changed:
                self._direction *= -1
                if settings.reset_integral_on_direction_change:
                    self._clear_integral()
                self._filtered_derivative = 0.0
        else:
            self._append_direction_sample(error_magnitude, control_dt)
            window_trend, direction_changed = self._evaluate_direction_window()
            if window_trend is not None:
                sample_trend = window_trend

        if long_gap or self._previous_error_magnitude is None or setpoint_changed or (direction_changed and settings.direction_each_update):
            raw_derivative = 0.0
            self._filtered_derivative = 0.0
        else:
            raw_derivative = (
                error_magnitude - self._previous_error_magnitude
            ) / control_dt
            tau = limits.derivative_filter_tau
            if tau <= 0.0:
                self._filtered_derivative = raw_derivative
            else:
                alpha = control_dt / (tau + control_dt)
                self._filtered_derivative += alpha * (
                    raw_derivative - self._filtered_derivative
                )

        if direction_changed and not settings.direction_each_update:
            # Hold one sample at the reversal so LabVIEW does not receive an
            # abrupt command under the new direction on the same measurement
            # that triggered the reversal.
            self._previous_error_magnitude = error_magnitude
            self._last_setpoint = setpoint
            self._last_result = PIDResult(
                output=0.0,
                error=signed_error,
                proportional=0.0,
                integral=0.0,
                derivative=0.0,
                saturated=False,
                error_magnitude=error_magnitude,
                pid_magnitude=0.0,
                direction=self._direction,
                error_trend="INCREASING",
                direction_changed=True,
                in_deadband=False,
            )
            return self._last_result

        # Finite-window integration prevents the absolute-error integral from
        # growing forever. hold_integrator adds zero-error time, which ages old
        # memory out instead of freezing it indefinitely.
        if hold_integrator:
            self._append_integral_sample(0.0, control_dt)
            integral_sample_added = False
        else:
            self._append_integral_sample(error_magnitude, control_dt)
            integral_sample_added = True

        # Kp/Ki/Kd define a trim-coil movement rate. Multiplication by dt below
        # converts those rate components into the actual A/update values shown
        # by the GUI and added to the current target.
        proportional_rate = gains.kp * error_magnitude
        integral_rate = gains.ki * self._integral_area

        # In adaptive-direction control, positive dE/dt means the present
        # actuator direction is becoming worse and should be handled by the
        # direction logic. It must not accelerate farther in that same direction.
        # The derivative is therefore damping-only: a decreasing error can slow
        # the move as the setpoint is approached; an increasing error adds zero.
        raw_derivative_rate = gains.kd * self._filtered_derivative
        derivative_rate = min(0.0, raw_derivative_rate)

        proportional_step = proportional_rate * step_dt
        integral_step = integral_rate * step_dt
        derivative_step = derivative_rate * step_dt

        # Retain the legacy integral maximum only as a hidden numerical guard.
        # The lower value is not forced in adaptive mode.
        integral_upper = max(0.0, float(limits.integral_max))
        integral_limited = False
        if integral_step > integral_upper:
            integral_step = integral_upper
            integral_limited = True

        unsaturated_step = max(
            0.0,
            proportional_step + integral_step + derivative_step,
        )
        # output_min is intentionally ignored: forced minimum target increments
        # are a known source of chatter around the deadband.
        output_upper = max(0.0, float(limits.output_max))
        pid_magnitude = min(unsaturated_step, output_upper)
        saturated = integral_limited or not math.isclose(
            pid_magnitude,
            unsaturated_step,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        )

        # Conditional anti-windup. If the newest integration sample helped push
        # the step into its emergency ceiling, remove that sample and recompute.
        if saturated and integral_sample_added and gains.ki > 0.0:
            self._remove_last_integral_sample()
            integral_rate = gains.ki * self._integral_area
            integral_step = min(
                integral_rate * step_dt,
                integral_upper,
            )
            unsaturated_step = max(
                0.0,
                proportional_step + integral_step + derivative_step,
            )
            pid_magnitude = min(unsaturated_step, output_upper)
            saturated = not math.isclose(
                pid_magnitude,
                unsaturated_step,
                rel_tol=0.0,
                abs_tol=1.0e-12,
            )

        signed_output = float(self._direction) * pid_magnitude

        self._previous_error_magnitude = error_magnitude
        self._last_setpoint = setpoint
        self._last_result = PIDResult(
            output=signed_output,
            error=signed_error,
            proportional=proportional_step,
            integral=integral_step,
            derivative=derivative_step,
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
