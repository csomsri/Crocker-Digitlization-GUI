#include "Controls/ControlSystem/NLAPID.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace crocker::controls {
namespace {
void finite(double value) {
    if (!std::isfinite(value)) throw std::invalid_argument("NLAPID values must be finite");
}
bool different(double a, double b) { return std::abs(a - b) > 1.0e-12; }
}

NLAPID::NLAPID(NLAPIDGains gains, NLAPIDLimits limits, NLAPIDSettings settings) {
    setGains(gains); setLimits(limits); setSettings(settings); reset();
}
void NLAPID::setGains(NLAPIDGains gains) {
    for (double v : {gains.kp, gains.ki, gains.kd}) {
        finite(v);
        if (v < 0) throw std::invalid_argument("NLAPID gains must be nonnegative");
    }
    gains_ = gains;
}
void NLAPID::setLimits(NLAPIDLimits limits) {
    finite(limits.outputMax); finite(limits.integralMax); finite(limits.derivativeFilterTau);
    limits.derivativeFilterTau = std::max(0.0, limits.derivativeFilterTau);
    limits_ = limits;
}
void NLAPID::setSettings(NLAPIDSettings s) {
    for (double v : {s.deadband, s.trendTolerance, s.directionCheckInterval,
                    s.integralWindowMultiplier, s.maxControlDt, s.integralMemorySeconds}) finite(v);
    s.deadband = std::max(0.0, s.deadband);
    s.trendTolerance = std::max(0.0, s.trendTolerance);
    s.directionCheckInterval = std::max(0.0, s.directionCheckInterval);
    s.directionConfirmations = std::max(1, s.directionConfirmations);
    s.minimumDirectionSamples = std::max(1, s.minimumDirectionSamples);
    s.integralWindowMultiplier = std::max(1.0, s.integralWindowMultiplier);
    s.maxControlDt = std::max(1.0e-4, s.maxControlDt);
    s.integralMemorySeconds = std::max(0.0, s.integralMemorySeconds);
    s.initialDirection = s.initialDirection >= 0 ? 1 : -1;
    settings_ = s;
    trimIntegral(integralWindowSeconds());
}
std::string NLAPID::trend(double current, std::optional<double> previous, double tolerance) {
    if (!previous) return "INITIALIZING";
    if (current - *previous > tolerance) return "INCREASING";
    if (current - *previous < -tolerance) return "DECREASING";
    return "STEADY";
}
double NLAPID::integralWindowSeconds() const {
    if (settings_.integralMemorySeconds > 0) return std::max(0.1, settings_.integralMemorySeconds);
    return std::max(1.0, settings_.integralWindowMultiplier * settings_.directionCheckInterval);
}
void NLAPID::clearIntegral() {
    integralHistory_.clear(); integralArea_ = integralElapsed_ = 0.0;
}
void NLAPID::appendIntegral(double magnitude, double dt) {
    integralHistory_.emplace_back(dt, magnitude);
    integralElapsed_ += dt; integralArea_ += dt * magnitude;
    trimIntegral(integralWindowSeconds());
}
void NLAPID::removeLastIntegral() {
    if (integralHistory_.empty()) return;
    const auto [duration, magnitude] = integralHistory_.back();
    integralHistory_.pop_back();
    integralElapsed_ = std::max(0.0, integralElapsed_ - duration);
    integralArea_ = std::max(0.0, integralArea_ - duration * magnitude);
}
void NLAPID::trimIntegral(double window) {
    const double keep = std::max(1.0e-6, window);
    while (!integralHistory_.empty() && integralElapsed_ > keep) {
        const double excess = integralElapsed_ - keep;
        const auto [duration, magnitude] = integralHistory_.front();
        if (duration <= excess + 1.0e-12) {
            integralHistory_.pop_front();
            integralElapsed_ -= duration; integralArea_ -= duration * magnitude;
        } else {
            integralHistory_.front().first = duration - excess;
            integralElapsed_ -= excess; integralArea_ -= excess * magnitude;
            break;
        }
    }
    integralElapsed_ = std::max(0.0, integralElapsed_);
    integralArea_ = std::max(0.0, integralArea_);
}
void NLAPID::clearDirectionWindow() {
    directionArea_ = directionElapsed_ = 0.0; directionSamples_ = 0;
}
std::pair<std::string, bool> NLAPID::evaluateDirectionWindow() {
    if (directionElapsed_ < std::max(settings_.directionCheckInterval,
                                     std::min(settings_.maxControlDt, 0.05)) ||
        directionSamples_ < settings_.minimumDirectionSamples) return {"", false};
    const double mean = directionArea_ / directionElapsed_;
    std::string state = trend(mean, previousMean_, std::max(settings_.trendTolerance, settings_.deadband));
    bool changed = false;
    if (!previousMean_) {
        worseningWindows_ = 0; previousMean_ = mean;
    } else if (state == "INCREASING") {
        if (++worseningWindows_ >= settings_.directionConfirmations) {
            direction_ *= -1; changed = true; worseningWindows_ = 0;
            clearIntegral(); filteredDerivative_ = 0.0; previousMean_ = mean;
        }
    } else if (state == "DECREASING") {
        worseningWindows_ = 0; previousMean_ = mean;
    } else {
        worseningWindows_ = 0;
    }
    clearDirectionWindow();
    return {state, changed};
}
void NLAPID::reset(std::optional<double> setpoint, std::optional<double> measurement,
                   std::optional<int> direction) {
    filteredDerivative_ = 0.0;
    direction_ = direction ? (*direction >= 0 ? 1 : -1) : settings_.initialDirection;
    previousMagnitude_.reset(); previousMean_.reset(); lastSetpoint_.reset();
    worseningWindows_ = 0; clearIntegral(); clearDirectionWindow();
    if (setpoint && measurement && std::isfinite(*setpoint) && std::isfinite(*measurement)) {
        previousMagnitude_ = previousMean_ = std::abs(*setpoint - *measurement);
        lastSetpoint_ = setpoint;
    }
    result_ = {}; result_.direction = direction_;
}
NLAPIDResult NLAPID::update(double setpoint, double measurement, double dt, bool holdIntegrator) {
    finite(setpoint); finite(measurement); finite(dt);
    if (dt <= 0) throw std::invalid_argument("NLAPID dt must be positive");
    const double step = std::min(dt, settings_.maxControlDt);
    const bool longGap = dt > 2.0 * settings_.maxControlDt;
    const double error = setpoint - measurement, magnitude = std::abs(error);
    const bool setpointChanged = lastSetpoint_ && different(setpoint, *lastSetpoint_);
    std::string state;
    if (!lastSetpoint_ || setpointChanged) {
        previousMagnitude_ = previousMean_ = magnitude;
        worseningWindows_ = 0; clearDirectionWindow(); clearIntegral(); filteredDerivative_ = 0.0;
        state = setpointChanged ? "SETPOINT CHANGED" : "INITIALIZING";
    } else {
        state = trend(magnitude, previousMagnitude_, settings_.trendTolerance);
    }
    result_ = {}; result_.error = error; result_.errorMagnitude = magnitude;
    if (magnitude <= settings_.deadband) {
        if (settings_.resetIntegralInDeadband) clearIntegral(); else appendIntegral(0.0, step);
        filteredDerivative_ = 0.0; previousMagnitude_ = previousMean_ = magnitude;
        worseningWindows_ = 0; clearDirectionWindow(); lastSetpoint_ = setpoint;
        result_.direction = direction_; result_.errorTrend = "DEADBAND"; result_.inDeadband = true;
        return result_;
    }
    directionArea_ += magnitude * step; directionElapsed_ += step; ++directionSamples_;
    const auto [windowTrend, changed] = evaluateDirectionWindow();
    if (!windowTrend.empty()) state = windowTrend;
    if (longGap || !previousMagnitude_ || setpointChanged) {
        filteredDerivative_ = 0.0;
    } else {
        const double raw = (magnitude - *previousMagnitude_) / step;
        if (limits_.derivativeFilterTau <= 0) filteredDerivative_ = raw;
        else filteredDerivative_ += step / (limits_.derivativeFilterTau + step) * (raw - filteredDerivative_);
    }
    result_.direction = direction_;
    if (changed) {
        previousMagnitude_ = magnitude; lastSetpoint_ = setpoint;
        result_.errorTrend = "INCREASING"; result_.directionChanged = true;
        return result_;
    }
    appendIntegral(holdIntegrator ? 0.0 : magnitude, step);
    result_.proportional = gains_.kp * magnitude * step;
    result_.integral = gains_.ki * integralArea_ * step;
    result_.derivative = std::min(0.0, gains_.kd * filteredDerivative_) * step;
    const double integralUpper = std::max(0.0, limits_.integralMax);
    const bool integralLimited = result_.integral > integralUpper;
    result_.integral = std::min(result_.integral, integralUpper);
    double unsaturated = std::max(0.0, result_.proportional + result_.integral + result_.derivative);
    const double outputUpper = std::max(0.0, limits_.outputMax);
    result_.pidMagnitude = std::min(unsaturated, outputUpper);
    result_.saturated = integralLimited || different(result_.pidMagnitude, unsaturated);
    if (result_.saturated && !holdIntegrator && gains_.ki > 0) {
        removeLastIntegral();
        result_.integral = std::min(gains_.ki * integralArea_ * step, integralUpper);
        unsaturated = std::max(0.0, result_.proportional + result_.integral + result_.derivative);
        result_.pidMagnitude = std::min(unsaturated, outputUpper);
        result_.saturated = different(result_.pidMagnitude, unsaturated);
    }
    result_.output = direction_ * result_.pidMagnitude;
    result_.errorTrend = state;
    previousMagnitude_ = magnitude; lastSetpoint_ = setpoint;
    return result_;
}
} // namespace crocker::controls
