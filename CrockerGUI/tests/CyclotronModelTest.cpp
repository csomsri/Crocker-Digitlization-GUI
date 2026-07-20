#include "Simulation/CyclotronModel.hpp"

#include <cassert>
#include <cmath>

namespace {
constexpr double ProtonCharge = 1.602176634e-19;
constexpr double ProtonMass = 1.67262192369e-27;
constexpr double ElectronVoltJoules = ProtonCharge;

double momentumFromKineticEnergy(double energyElectronVolts)
{
    // Non-relativistic initialization is adequate for this 10 keV validation case.
    return std::sqrt(2.0 * ProtonMass * energyElectronVolts * ElectronVoltJoules);
}
}

int main()
{
    using namespace crocker::simulation;

    CyclotronConfig config;
    config.magneticFieldTesla = 1.0;
    config.rfPeakElectricFieldVoltsPerMeter = 0.0;
    config.chamberRadiusMeters = 1.0;
    config.timeStepSeconds = 1.0e-10;

    const double initialMomentum = momentumFromKineticEnergy(10'000.0);
    const double expectedOrbitRadius = initialMomentum / (ProtonCharge * config.magneticFieldTesla);
    ParticleState initial;
    initial.xMeters = 0.0;
    initial.yMeters = expectedOrbitRadius;
    initial.pxKgMetersPerSecond = initialMomentum;

    CyclotronModel model(config);
    model.Reset(initial);
    const double initialEnergy = model.Diagnostics().kineticEnergyElectronVolts;

    // Approximately two non-relativistic cyclotron periods.
    const double period = 2.0 * std::acos(-1.0) * ProtonMass
        / (ProtonCharge * config.magneticFieldTesla);
    model.Step(static_cast<std::size_t>(2.0 * period / config.timeStepSeconds));

    const auto final = model.Diagnostics();
    const auto state = model.State();
    assert(std::abs(final.kineticEnergyElectronVolts - initialEnergy) / initialEnergy < 1.0e-8);
    assert(std::hypot(state.xMeters, state.yMeters - expectedOrbitRadius)
        < expectedOrbitRadius * 0.03);
    assert(!final.lost);

    // With B and RF frequency disabled, the gap becomes a uniform DC field.
    // Momentum should then follow the exact impulse p = qEt.
    CyclotronConfig accelerationConfig;
    accelerationConfig.magneticFieldTesla = 0.0;
    accelerationConfig.rfFrequencyHz = 0.0;
    accelerationConfig.rfPeakElectricFieldVoltsPerMeter = 50'000.0;
    accelerationConfig.gapHalfWidthMeters = 1.0;
    accelerationConfig.chamberRadiusMeters = 2.0;
    accelerationConfig.timeStepSeconds = 1.0e-10;
    CyclotronModel accelerationModel(accelerationConfig);
    constexpr std::size_t accelerationSteps = 1'000;
    accelerationModel.Step(accelerationSteps);
    const double expectedMomentum = ProtonCharge
        * accelerationConfig.rfPeakElectricFieldVoltsPerMeter
        * accelerationConfig.timeStepSeconds * accelerationSteps;
    assert(std::abs(accelerationModel.State().pxKgMetersPerSecond - expectedMomentum)
        / expectedMomentum < 1.0e-12);
    assert(accelerationModel.Diagnostics().kineticEnergyElectronVolts > 0.0);

    // A particle outside the chamber must be marked lost and stop advancing.
    initial.xMeters = config.chamberRadiusMeters;
    model.Reset(initial);
    model.Step(10);
    assert(model.Diagnostics().lost);
    assert(model.Diagnostics().completedSteps == 0);
    return 0;
}
