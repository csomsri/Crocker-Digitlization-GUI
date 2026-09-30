#pragma once
#include "Controls/ChannelId.hpp"
#include <array>
#include <chrono>
#include <optional>
#include <string>
#include <vector>

namespace crocker::controls {
using SequenceClock = std::chrono::steady_clock;
using SequenceDuration = std::chrono::duration<double>;
enum class SequenceRunState {
    Idle, Applying, Running, Settling, Dwelling, Stopping, Completed, Stopped, Faulted
};
enum class StopPolicy { KeepTargets, DisableChannels };
// Default application input range matches Field Control. These are not a
// substitute for commissioned, channel-specific machine operating limits.
struct SequenceTargetLimits {
    std::array<double, ChannelCount> minimum{};
    std::array<double, ChannelCount> maximum = [] {
        std::array<double, ChannelCount> result{};
        result.fill(1000.0);
        return result;
    }();
};
struct SequenceFault {
    std::string code;
    std::string message;
    std::optional<ChannelId> channel;
};
struct SequenceStep {
    SequenceDuration dwell{0};
    SequenceDuration settle{0.2};
    SequenceDuration reachTimeout{30};
    std::array<std::optional<double>, ChannelCount> targets{};
    std::array<double, ChannelCount> tolerance{};
};
struct SequenceDefinition {
    std::vector<SequenceStep> steps;
    SequenceTargetLimits limits;
    SequenceDuration telemetryTimeout{1};
    double updateRateHz = 20;
    StopPolicy stopPolicy = StopPolicy::KeepTargets;
    StopPolicy faultPolicy = StopPolicy::KeepTargets;
};
struct SequenceRunStatus {
    SequenceRunState state = SequenceRunState::Idle;
    std::string message = "Ready to run";
    std::size_t stepIndex = 0;
    std::size_t stepCount = 0;
    double elapsedSeconds = 0;
    double dwellRemainingSeconds = 0;
    bool targetReached = false;
    bool watchdogHealthy = false;
    std::optional<SequenceFault> fault;
};
struct SequenceEvent {
    SequenceRunState state;
    std::size_t stepIndex;
    double elapsedSeconds;
    std::string message;
};
struct SequenceActions {
    std::optional<std::array<std::optional<double>, ChannelCount>> targets;
};
// Compatibility input for existing C++ callers and Python dictionaries.
struct SequencePoint {
    double timeSeconds = 0; // Dwell after measured arrival, never absolute time.
    std::array<std::optional<double>, ChannelCount> targets{};
};
using Sequence = std::vector<SequencePoint>;
struct SequenceRunConfig {
    Sequence sequence;
    SequenceTargetLimits limits;
    double updateRateHz = 20;
    double targetTolerance = 0.5;
    double stepTimeoutSeconds = 30;
    double telemetryTimeoutSeconds = 1;
    double settleSeconds = 0.2;
    bool requireConnected = true; // False is rejected; use a simulator transport.
    bool disableChannelsOnStop = false;
    bool disableChannelsOnFault = false;
};
inline bool SequenceActive(SequenceRunState state) noexcept {
    return state == SequenceRunState::Applying || state == SequenceRunState::Running ||
        state == SequenceRunState::Settling || state == SequenceRunState::Dwelling ||
        state == SequenceRunState::Stopping;
}
}
