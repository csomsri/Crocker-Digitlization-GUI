#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

// Control Variables
namespace crocker::controls {

inline constexpr std::size_t ChannelCount = 14;
using ChannelId = std::size_t;

enum class ChannelStatus {
    Unknown,
    Disabled,
    Off,
    Ready,
    Warning,
    Fault,
    Interlocked
};

enum class ConnectionState {
    Disconnected,
    Connecting,
    Connected,
    Degraded,
    Faulted
};

enum class AlarmSeverity {
    Info,
    Warning,
    Error,
    Critical
};

enum class PidTrialState {
    Idle,
    Running,
    Completed,
    Stopped,
    Faulted
};

enum class SequenceRunState {
    Idle,
    Running,
    Dwelling,
    Completed,
    Stopped,
    Faulted
};

// Desired state for one hardware channel, expressed in engineering units.
struct ChannelCommand {
    double target = 0.0;
    bool on = false;
    bool enabled = false;
};

using ControlCommand = std::array<ChannelCommand, ChannelCount>;

struct ScalingPoint {
    double input = 0.0;
    double output = 0.0;
};

struct LinearChannelScaling {
    double rawToEngineeringGain = 1.0;
    double rawToEngineeringOffset = 0.0;
    double engineeringToRawGain = 1.0;
    double engineeringToRawOffset = 0.0;
    std::vector<ScalingPoint> rawToEngineeringCurve;
    std::vector<ScalingPoint> engineeringToRawCurve;
    bool rawToEngineeringUsesCurve = false;
    bool engineeringToRawUsesCurve = false;
    bool enabled = false;
};

using ControlScaling = std::array<LinearChannelScaling, ChannelCount>;

// Configuration for a bounded PID field trial. Allocation coefficients map the
// scalar PID output onto hardware channels; zero leaves a channel untouched.
struct PidTrialConfig {
    ChannelId measurementChannel = 0;
    double setpoint = 0.0;
    double kp = 0.0;
    double ki = 0.0;
    double kd = 0.0;
    double updateRateHz = 20.0;
    double durationSeconds = 3.0;
    double telemetryTimeoutSeconds = 1.0;
    double maxAbsoluteError = 1.0e12;
    double maxOvershoot = 1.0e12;
    double maxControlOutput = 1.0e12;
    double maxSaturationSeconds = 1.0e12;
    std::array<double, ChannelCount> allocation{};
    std::array<double, ChannelCount> commandBias{};
    std::array<double, ChannelCount> minimumCommand{};
    std::array<double, ChannelCount> maximumCommand{};
    std::array<double, ChannelCount> maximumSlewPerSecond{};
    bool allocationCalibrated = false;
    bool hardwareArmed = false;
    bool dryRun = true;
};

struct PidTrialStatus {
    PidTrialState state = PidTrialState::Idle;
    std::string message = "Idle";
    double elapsedSeconds = 0.0;
    double measuredField = 0.0;
    double error = 0.0;
    double controlOutput = 0.0;
    std::uint64_t iterations = 0;
    bool saturated = false;
    bool rateLimited = false;
    bool watchdogHealthy = false;
};

// Latest measured state for one hardware channel.
struct ChannelTelemetry {
    double actual = 0.0;
    double raw = 0.0;
    ChannelStatus status = ChannelStatus::Unknown;
    bool on = false;
    bool enabled = false;
    bool interlocked = false;
};

// Safety
struct Alarm {
    std::uint64_t id = 0;
    double timestampUnixSeconds = 0.0;
    AlarmSeverity severity = AlarmSeverity::Info;
    std::optional<ChannelId> channel;
    std::string code;
    std::string message;
    bool acknowledged = false;
};

// Immutable-by-convention value returned to UI and logging consumers.
struct TelemetrySnapshot {
    std::array<ChannelTelemetry, ChannelCount> channels{};
    std::vector<Alarm> activeAlarms;
    double timestampUnixSeconds = 0.0;
    double latencyMilliseconds = 0.0;
    std::uint64_t sequenceNumber = 0;
    ConnectionState connection = ConnectionState::Disconnected;
    bool simulated = false;
};

// Status of System
struct HealthStatus {
    ConnectionState connection = ConnectionState::Disconnected;
    std::string endpoint;
    std::string lastError;
    double lastPacketUnixSeconds = 0.0;
    double packetAgeMilliseconds = 0.0;
    double updateRateHz = 0.0;
    std::uint64_t receivedPackets = 0;
    std::uint64_t sentPackets = 0;
    std::uint64_t droppedPackets = 0;
    std::uint64_t decodeErrors = 0;
    bool simulated = false;
};

// A sparse sequence point. nullopt means "leave this channel unchanged".
struct SequencePoint {
    double timeSeconds = 0.0;
    std::array<std::optional<double>, ChannelCount> targets{};
};

using Sequence = std::vector<SequencePoint>;

struct SequenceRunConfig {
    Sequence sequence;
    double updateRateHz = 20.0;
    double targetTolerance = 0.5;
    double stepTimeoutSeconds = 30.0;
    bool requireConnected = true;
    bool disableChannelsOnStop = false;
};

struct SequenceRunStatus {
    SequenceRunState state = SequenceRunState::Idle;
    std::string message = "Idle";
    std::size_t stepIndex = 0;
    std::size_t stepCount = 0;
    double elapsedSeconds = 0.0;
    double dwellRemainingSeconds = 0.0;
    bool targetReached = false;
    bool watchdogHealthy = false;
};

[[nodiscard]] constexpr bool IsValidChannel(ChannelId channel) noexcept {
    return channel < ChannelCount;
}

} // namespace crocker::controls
