#include "Controls/Sequencer/Sequencer.hpp"
#include "Controls/Sequencer/SequenceValidator.hpp"
#include <algorithm>
#include <cmath>

namespace crocker::controls {
void Sequencer::Transition(SequenceRunState state, std::string message) {
    status_.state = state;
    status_.message = std::move(message);
    events_.push_back({state, status_.stepIndex, status_.elapsedSeconds, status_.message});
}
void Sequencer::Start(const SequenceDefinition& definition, SequenceClock::time_point now) {
    SequenceValidator::Validate(definition);
    definition_ = definition;
    status_ = {};
    status_.stepCount = definition.steps.size();
    events_.clear();
    activeTargets_.fill(std::nullopt);
    started_ = arrivalStarted_ = phaseStarted_ = stepStarted_ = now;
    dispatched_ = false;
    Transition(SequenceRunState::Applying, "Sending step targets");
}
void Sequencer::Fail(std::string code, std::string message, std::optional<ChannelId> channel) {
    status_.fault = SequenceFault{std::move(code), message, channel};
    status_.watchdogHealthy = false;
    status_.targetReached = false;
    Transition(SequenceRunState::Faulted, std::move(message));
}
void Sequencer::Stop() {
    if (SequenceActive(status_.state)) {
        status_.targetReached = false;
        Transition(SequenceRunState::Stopped, "Sequence stopped");
    }
}
void Sequencer::CommandStaged(bool success, SequenceClock::time_point now) {
    if (status_.state != SequenceRunState::Applying) return;
    if (!success) { Fail("command_failed", "Could not send step targets to the control transport."); return; }
    arrivalStarted_ = now;
    Transition(SequenceRunState::Running, "Waiting for measured currents to reach their targets");
}
SequenceActions Sequencer::Tick(const SequenceInput& input, SequenceClock::time_point now) {
    if (!SequenceActive(status_.state)) return {};
    status_.elapsedSeconds = SequenceDuration(now - started_).count();
    const auto& step = definition_.steps[status_.stepIndex];
    // A newly started simulator may not have produced its first packet yet.
    // Never send a target until feedback exists; bound this initial wait.
    if (input.health.receivedPackets == 0 && now - started_ < definition_.telemetryTimeout)
        return {};
    if (input.telemetry.connection != ConnectionState::Connected) {
        Fail("disconnected", "Control connection lost. Sequence stopped."); return {};
    }
    if (!std::isfinite(input.health.packetAgeMilliseconds) || input.health.packetAgeMilliseconds < 0 ||
        input.health.receivedPackets == 0 || input.health.packetAgeMilliseconds > definition_.telemetryTimeout.count() * 1000) {
        Fail("stale_feedback", "Machine feedback is stale. Sequence stopped."); return {};
    }
    bool reached = true;
    for (ChannelId ch = 0; ch < ChannelCount; ++ch) {
        // Preflight new targets before sending; keep monitoring earlier channels.
        if (!activeTargets_[ch] && !step.targets[ch]) continue;
        const auto& measured = input.telemetry.channels[ch];
        if (measured.interlocked || measured.status == ChannelStatus::Fault || measured.status == ChannelStatus::Interlocked) {
            Fail("channel_fault", "Channel " + std::to_string(ch + 1) + " reports a fault or interlock.", ch); return {};
        }
        if (!std::isfinite(measured.actual) || measured.status == ChannelStatus::Unknown) {
            Fail("invalid_feedback", "Channel " + std::to_string(ch + 1) + " has no valid current readback.", ch); return {};
        }
        const auto target = step.targets[ch] ? step.targets[ch] : activeTargets_[ch];
        reached = reached && measured.on && measured.enabled && std::abs(measured.actual - *target) <= step.tolerance[ch];
    }
    status_.watchdogHealthy = true;
    // Repeated departures during a hold cannot keep a step alive indefinitely.
    if (now - stepStarted_ > step.reachTimeout + step.dwell) {
        Fail("step_timeout", "Step exceeded its arrival and hold time budget."); return {};
    }
    if (status_.state == SequenceRunState::Applying) {
        if (dispatched_) return {};
        for (ChannelId ch = 0; ch < ChannelCount; ++ch)
            if (step.targets[ch]) activeTargets_[ch] = step.targets[ch];
        dispatched_ = true;
        status_.dwellRemainingSeconds = step.dwell.count();
        return {step.targets};
    }
    status_.targetReached = reached;
    if (!reached) {
        if (status_.state == SequenceRunState::Dwelling) arrivalStarted_ = now;
        if (status_.state != SequenceRunState::Running)
            Transition(SequenceRunState::Running, "Outside target tolerance; waiting again, then restarting the hold");
        status_.dwellRemainingSeconds = step.dwell.count();
    } else if (status_.state == SequenceRunState::Running) {
        phaseStarted_ = now;
        Transition(SequenceRunState::Settling, "At target; checking that measured currents stay steady");
    }
    if ((status_.state == SequenceRunState::Running || status_.state == SequenceRunState::Settling) &&
        now - arrivalStarted_ >= step.reachTimeout) {
        Fail("arrival_timeout", "Step " + std::to_string(status_.stepIndex + 1) + " did not reach and settle at its targets in time."); return {};
    }
    if (status_.state == SequenceRunState::Settling && now - phaseStarted_ >= step.settle) {
        phaseStarted_ = now;
        Transition(SequenceRunState::Dwelling, "Holding at the measured targets");
    }
    if (status_.state == SequenceRunState::Dwelling) {
        status_.dwellRemainingSeconds = std::max(0.0, step.dwell.count() - SequenceDuration(now - phaseStarted_).count());
        if (status_.dwellRemainingSeconds == 0) {
            if (status_.stepIndex + 1 == definition_.steps.size()) {
                Transition(SequenceRunState::Completed, "Sequence complete. Final targets remain applied.");
            } else {
                ++status_.stepIndex;
                stepStarted_ = now;
                dispatched_ = false;
                status_.targetReached = false;
                Transition(SequenceRunState::Applying, "Sending next step targets");
            }
        }
    }
    return {};
}
}
