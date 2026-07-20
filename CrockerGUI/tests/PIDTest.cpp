#include "Controls/ControlSystem/PID.hpp"

#include <cassert>
#include <cmath>
#include <stdexcept>

namespace {
bool nearlyEqual(double lhs, double rhs) {
    return std::abs(lhs - rhs) < 1e-9;
}
}

int main() {
    PID proportional(2.0, 0.0, 0.0, 0.1);
    assert(nearlyEqual(proportional.update(3.0), 6.0));

    PID derivative(0.0, 0.0, 1.0, 0.5);
    assert(nearlyEqual(derivative.update(10.0), 0.0));
    assert(nearlyEqual(derivative.update(12.0), 4.0));
    derivative.reset();
    assert(nearlyEqual(derivative.update(20.0), 0.0));

    PID boundedIntegral(0.0, 1.0, 0.0, 1.0, -10.0, 10.0);
    for (int i = 0; i < 100; ++i) {
        boundedIntegral.update(10.0);
    }
    assert(nearlyEqual(boundedIntegral.update(-1.0), 9.0));

    bool rejectedInvalidSampleTime = false;
    try {
        PID invalid(1.0, 0.0, 0.0, 0.0);
    } catch (const std::invalid_argument&) {
        rejectedInvalidSampleTime = true;
    }
    assert(rejectedInvalidSampleTime);

    return 0;
}
