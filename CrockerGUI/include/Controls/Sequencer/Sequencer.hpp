#pragma once
#include "Controls/ControlTypes.hpp"
#include "Controls/Sequencer/SequenceTypes.hpp"

namespace crocker::controls {
struct SequenceInput {
    TelemetrySnapshot telemetry;
    HealthStatus health;
};
class Sequencer {
public:
    void Start(const SequenceDefinition& definition, SequenceClock::time_point now);
    SequenceActions Tick(const SequenceInput& input, SequenceClock::time_point now);
    void CommandStaged(bool success, SequenceClock::time_point now);
    void Stop();
    void Fail(std::string code, std::string message, std::optional<ChannelId> channel = {});
    const SequenceRunStatus& Status() const noexcept { return status_; }
    const std::vector<SequenceEvent>& Events() const noexcept { return events_; }
private:
    void Transition(SequenceRunState state, std::string message);
    SequenceDefinition definition_;
    SequenceRunStatus status_;
    std::vector<SequenceEvent> events_;
    std::array<std::optional<double>, ChannelCount> activeTargets_{};
    SequenceClock::time_point started_{}, arrivalStarted_{}, phaseStarted_{}, stepStarted_{};
    bool dispatched_ = false;
};
}
