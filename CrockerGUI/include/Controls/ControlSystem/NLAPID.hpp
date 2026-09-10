#pragma once

#include <deque>
#include <optional>
#include <string>
#include <utility>

namespace crocker::controls {

struct NLAPIDGains { double kp = 0.0, ki = 0.0, kd = 0.0; };
struct NLAPIDLimits {
    double outputMax = 100.0;       // Maximum returned increment, not target.
    double integralMax = 100.0;     // Maximum integral contribution per update.
    double derivativeFilterTau = 0.05;
};
struct NLAPIDSettings {
    double deadband = 0.0;
    double trendTolerance = 0.0;
    double directionCheckInterval = 1.0;
    int initialDirection = 1;
    bool resetIntegralInDeadband = false;
    int directionConfirmations = 2;
    int minimumDirectionSamples = 3;
    double integralWindowMultiplier = 2.0;
    double maxControlDt = 0.25;
    double integralMemorySeconds = 20.0;
};
struct NLAPIDResult {
    double output = 0.0, error = 0.0;
    double proportional = 0.0, integral = 0.0, derivative = 0.0;
    bool saturated = false;
    double errorMagnitude = 0.0, pidMagnitude = 0.0;
    int direction = 1;
    std::string errorTrend = "RESET";
    bool directionChanged = false, inDeadband = false;
};

// Numerical reference port of source/Python/Control/NLAPID.py.
// Stateful, single-owner engine. No transport, threading, or GUI dependencies.
class NLAPID {
public:
    NLAPID(NLAPIDGains gains = {}, NLAPIDLimits limits = {}, NLAPIDSettings settings = {});
    void setGains(NLAPIDGains gains);
    void setLimits(NLAPIDLimits limits);
    void setSettings(NLAPIDSettings settings);
    void reset(std::optional<double> setpoint = {}, std::optional<double> measurement = {},
               std::optional<int> direction = {});
    NLAPIDResult update(double setpoint, double measurement, double dt, bool holdIntegrator = false);
    const NLAPIDResult& lastResult() const noexcept { return result_; }
    int direction() const noexcept { return direction_; }

private:
    static std::string trend(double current, std::optional<double> previous, double tolerance);
    double integralWindowSeconds() const;
    void clearIntegral();
    void appendIntegral(double magnitude, double dt);
    void removeLastIntegral();
    void trimIntegral(double window);
    void clearDirectionWindow();
    std::pair<std::string, bool> evaluateDirectionWindow();

    NLAPIDGains gains_;
    NLAPIDLimits limits_;
    NLAPIDSettings settings_;
    NLAPIDResult result_;
    int direction_ = 1, worseningWindows_ = 0, directionSamples_ = 0;
    double filteredDerivative_ = 0.0, integralArea_ = 0.0, integralElapsed_ = 0.0;
    double directionArea_ = 0.0, directionElapsed_ = 0.0;
    std::optional<double> previousMagnitude_, previousMean_, lastSetpoint_;
    std::deque<std::pair<double, double>> integralHistory_;
};
} // namespace crocker::controls
