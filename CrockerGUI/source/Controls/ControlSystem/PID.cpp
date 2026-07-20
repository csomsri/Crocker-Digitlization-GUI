#include "Controls/ControlSystem/PID.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

PID::PID(double kp, double ki, double kd, double dt,
         double minOutput, double maxOutput)
    : _kp(kp),
      _ki(ki),
      _kd(kd),
      _dt(dt),
      _prevError(0.0),
      _integral(0.0),
      _min(minOutput),
      _max(maxOutput),
      _hasPreviousError(false) {

        
    if (!std::isfinite(kp) || !std::isfinite(ki) || !std::isfinite(kd)) {
        throw std::invalid_argument("PID gains must be finite");
    }
    if (!std::isfinite(dt) || dt <= 0.0) {
        throw std::invalid_argument("PID sample time must be finite and positive");
    }
    if (!std::isfinite(minOutput) || !std::isfinite(maxOutput) || minOutput >= maxOutput) {
        throw std::invalid_argument("PID output limits must be finite and ordered");
    }
}

double PID::update(double error) {
    if (!std::isfinite(error)) {
        throw std::invalid_argument("PID error must be finite");
    }

    const double derivative = _hasPreviousError ? (error - _prevError) / _dt : 0.0;
    _prevError = error;
    _hasPreviousError = true;

    const double candidateIntegral = _integral + error * _dt;
    const double candidateOutput =
        _kp * error + _ki * candidateIntegral + _kd * derivative;

    // Do not accumulate integral error if it would drive an already-saturated
    // output farther beyond its limit. Reversed error is still allowed to unwind it.
    const bool pushesAboveMaximum = candidateOutput > _max && _ki * error > 0.0;
    const bool pushesBelowMinimum = candidateOutput < _min && _ki * error < 0.0;
    if (!pushesAboveMaximum && !pushesBelowMinimum) {
        _integral = candidateIntegral;
    }

    const double output = _kp * error + _ki * _integral + _kd * derivative;
    return std::clamp(output, _min, _max);
}

void PID::reset() noexcept {
    _prevError = 0.0;
    _integral = 0.0;
    _hasPreviousError = false;
}
