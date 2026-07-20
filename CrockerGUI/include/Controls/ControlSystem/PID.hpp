#pragma once

class PID {
public:
    PID(double kp, double ki, double kd, double dt,
        double minOutput = -100.0, double maxOutput = 100.0);

    double update(double error);
    void reset() noexcept;

private:
    double _kp;
    double _ki;
    double _kd;
    double _dt;
    double _prevError;
    double _integral;
    double _min;
    double _max;
    bool _hasPreviousError;
};
