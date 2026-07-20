#pragma once

#include <cstddef>

namespace crocker::simulation {

struct ParticleState {
    double xMeters = 0.0;
    double yMeters = 0.0;
    double pxKgMetersPerSecond = 0.0;
    double pyKgMetersPerSecond = 0.0;
    double timeSeconds = 0.0;
};

struct CyclotronConfig {
    double magneticFieldTesla = 1.0;
    double rfFrequencyHz = 15.0e6;
    double rfPeakElectricFieldVoltsPerMeter = 1.0e5;
    double rfPhaseRadians = 0.0;
    double gapHalfWidthMeters = 0.0025;
    double chamberRadiusMeters = 1.0;
    double timeStepSeconds = 1.0e-10;
};

struct CyclotronDiagnostics {
    double kineticEnergyElectronVolts = 0.0;
    double speedMetersPerSecond = 0.0;
    double radiusMeters = 0.0;
    double rfPhaseRadians = 0.0;
    std::size_t completedSteps = 0;
    bool lost = false;
};

// Relativistic single-proton tracker. Magnetic motion is advanced with a
// Boris pusher, which avoids the artificial energy drift of forward Euler.
class CyclotronModel {
public:
    explicit CyclotronModel(CyclotronConfig config = {});

    void Reset(const ParticleState& state = {});
    void Step();
    void Step(std::size_t count);
    void SetMagneticFieldTesla(double magneticFieldTesla);
    void SetRfPeakElectricField(double electricFieldVoltsPerMeter);

    [[nodiscard]] const CyclotronConfig& Config() const noexcept;
    [[nodiscard]] const ParticleState& State() const noexcept;
    [[nodiscard]] CyclotronDiagnostics Diagnostics() const noexcept;
    [[nodiscard]] double ElectricFieldX(double xMeters, double timeSeconds) const noexcept;

private:
    [[nodiscard]] double Gamma(double px, double py) const noexcept;
    void ValidateConfig() const;

    CyclotronConfig config_;
    ParticleState state_{};
    std::size_t completedSteps_ = 0;
    bool lost_ = false;
};

} // namespace crocker::simulation
