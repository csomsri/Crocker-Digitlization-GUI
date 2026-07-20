// TEST
#include "Simulation/CyclotronModel.hpp"

#include <cmath>
#include <numbers>
#include <stdexcept>

namespace crocker::simulation {
namespace {
constexpr double ProtonCharge = 1.602176634e-19;
constexpr double ProtonMass = 1.67262192369e-27;
constexpr double SpeedOfLight = 299792458.0;
constexpr double ElectronVoltJoules = ProtonCharge;
}

CyclotronModel::CyclotronModel(CyclotronConfig config) : config_(config)
{
    ValidateConfig();
}

void CyclotronModel::ValidateConfig() const
{
    const bool finite = std::isfinite(config_.magneticFieldTesla)
        && std::isfinite(config_.rfFrequencyHz)
        && std::isfinite(config_.rfPeakElectricFieldVoltsPerMeter)
        && std::isfinite(config_.rfPhaseRadians)
        && std::isfinite(config_.gapHalfWidthMeters)
        && std::isfinite(config_.chamberRadiusMeters)
        && std::isfinite(config_.timeStepSeconds);
    if (!finite || config_.rfFrequencyHz < 0.0 || config_.gapHalfWidthMeters < 0.0
        || config_.chamberRadiusMeters <= 0.0 || config_.timeStepSeconds <= 0.0) {
        throw std::invalid_argument("Cyclotron configuration contains invalid values");
    }
}

void CyclotronModel::Reset(const ParticleState& state)
{
    if (!std::isfinite(state.xMeters) || !std::isfinite(state.yMeters)
        || !std::isfinite(state.pxKgMetersPerSecond)
        || !std::isfinite(state.pyKgMetersPerSecond) || !std::isfinite(state.timeSeconds)) {
        throw std::invalid_argument("Particle state must contain finite values");
    }
    state_ = state;
    completedSteps_ = 0;
    lost_ = std::hypot(state_.xMeters, state_.yMeters) >= config_.chamberRadiusMeters;
}

double CyclotronModel::Gamma(double px, double py) const noexcept
{
    const double momentumSquared = px * px + py * py;
    const double massTimesC = ProtonMass * SpeedOfLight;
    return std::sqrt(1.0 + momentumSquared / (massTimesC * massTimesC));
}

double CyclotronModel::ElectricFieldX(double xMeters, double timeSeconds) const noexcept
{
    if (std::abs(xMeters) > config_.gapHalfWidthMeters) {
        return 0.0;
    }
    const double omega = 2.0 * std::numbers::pi * config_.rfFrequencyHz;
    return config_.rfPeakElectricFieldVoltsPerMeter
        * std::cos(omega * timeSeconds + config_.rfPhaseRadians);
}

void CyclotronModel::Step()
{
    if (lost_) {
        return;
    }

    const double dt = config_.timeStepSeconds;
    const double electricField = ElectricFieldX(state_.xMeters, state_.timeSeconds + 0.5 * dt);

    // Relativistic Boris update in the x-y plane for B = (0, 0, Bz).
    double pxMinus = state_.pxKgMetersPerSecond + ProtonCharge * electricField * dt * 0.5;
    double pyMinus = state_.pyKgMetersPerSecond;
    const double gammaMinus = Gamma(pxMinus, pyMinus);
    const double t = ProtonCharge * config_.magneticFieldTesla * dt
        / (2.0 * ProtonMass * gammaMinus);
    const double s = 2.0 * t / (1.0 + t * t);

    const double pxPrime = pxMinus + pyMinus * t;
    const double pyPrime = pyMinus - pxMinus * t;
    const double pxPlus = pxMinus + pyPrime * s;
    const double pyPlus = pyMinus - pxPrime * s;

    state_.pxKgMetersPerSecond = pxPlus + ProtonCharge * electricField * dt * 0.5;
    state_.pyKgMetersPerSecond = pyPlus;

    const double gamma = Gamma(state_.pxKgMetersPerSecond, state_.pyKgMetersPerSecond);
    state_.xMeters += state_.pxKgMetersPerSecond * dt / (gamma * ProtonMass);
    state_.yMeters += state_.pyKgMetersPerSecond * dt / (gamma * ProtonMass);
    state_.timeSeconds += dt;
    ++completedSteps_;
    lost_ = std::hypot(state_.xMeters, state_.yMeters) >= config_.chamberRadiusMeters;
}

void CyclotronModel::Step(std::size_t count)
{
    for (std::size_t index = 0; index < count && !lost_; ++index) {
        Step();
    }
}

void CyclotronModel::SetMagneticFieldTesla(double magneticFieldTesla)
{
    if (!std::isfinite(magneticFieldTesla)) {
        throw std::invalid_argument("Magnetic field must be finite");
    }
    config_.magneticFieldTesla = magneticFieldTesla;
}

void CyclotronModel::SetRfPeakElectricField(double electricFieldVoltsPerMeter)
{
    if (!std::isfinite(electricFieldVoltsPerMeter)) {
        throw std::invalid_argument("RF electric field must be finite");
    }
    config_.rfPeakElectricFieldVoltsPerMeter = electricFieldVoltsPerMeter;
}

const CyclotronConfig& CyclotronModel::Config() const noexcept { return config_; }
const ParticleState& CyclotronModel::State() const noexcept { return state_; }

CyclotronDiagnostics CyclotronModel::Diagnostics() const noexcept
{
    const double gamma = Gamma(state_.pxKgMetersPerSecond, state_.pyKgMetersPerSecond);
    const double momentum = std::hypot(state_.pxKgMetersPerSecond, state_.pyKgMetersPerSecond);
    const double phase = std::fmod(
        2.0 * std::numbers::pi * config_.rfFrequencyHz * state_.timeSeconds
            + config_.rfPhaseRadians,
        2.0 * std::numbers::pi);
    return {
        (gamma - 1.0) * ProtonMass * SpeedOfLight * SpeedOfLight / ElectronVoltJoules,
        momentum / (gamma * ProtonMass),
        std::hypot(state_.xMeters, state_.yMeters),
        phase < 0.0 ? phase + 2.0 * std::numbers::pi : phase,
        completedSteps_,
        lost_
    };
}

} // namespace crocker::simulation
