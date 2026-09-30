#include "Controls/Sequencer/SequenceValidator.hpp"
#include <cmath>
#include <stdexcept>

namespace crocker::controls {
SequenceDefinition SequenceValidator::FromConfig(const SequenceRunConfig& config) {
    if (!config.requireConnected)
        throw std::invalid_argument("Sequence requires live feedback. Use the simulator to practice.");
    SequenceDefinition result;
    result.limits = config.limits;
    result.updateRateHz = config.updateRateHz;
    result.telemetryTimeout = SequenceDuration(config.telemetryTimeoutSeconds);
    result.stopPolicy = config.disableChannelsOnStop ? StopPolicy::DisableChannels : StopPolicy::KeepTargets;
    result.faultPolicy = config.disableChannelsOnFault ? StopPolicy::DisableChannels : StopPolicy::KeepTargets;
    for (const auto& point : config.sequence) {
        SequenceStep step;
        step.targets = point.targets;
        step.dwell = SequenceDuration(point.timeSeconds);
        step.settle = SequenceDuration(config.settleSeconds);
        step.reachTimeout = SequenceDuration(config.stepTimeoutSeconds);
        step.tolerance.fill(config.targetTolerance);
        result.steps.push_back(step);
    }
    Validate(result);
    return result;
}
void SequenceValidator::Validate(const SequenceDefinition& definition) {
    const auto nonnegative = [](double value) { return std::isfinite(value) && value >= 0; };
    if (definition.steps.empty()) throw std::invalid_argument("Add at least one sequence step.");
    if (!std::isfinite(definition.updateRateHz) || definition.updateRateHz < 1 || definition.updateRateHz > 1000)
        throw std::invalid_argument("Sequence update rate must be between 1 and 1000 Hz.");
    if (!nonnegative(definition.telemetryTimeout.count()) || definition.telemetryTimeout.count() == 0)
        throw std::invalid_argument("Feedback timeout must be positive and finite.");
    for (ChannelId ch = 0; ch < ChannelCount; ++ch)
        if (!std::isfinite(definition.limits.minimum[ch]) || !std::isfinite(definition.limits.maximum[ch]) ||
            definition.limits.minimum[ch] > definition.limits.maximum[ch])
            throw std::invalid_argument("Channel target limits must be finite and ordered.");
    for (std::size_t i = 0; i < definition.steps.size(); ++i) {
        const auto& step = definition.steps[i];
        const auto prefix = "Step " + std::to_string(i + 1) + ": ";
        if (!nonnegative(step.dwell.count()) || !nonnegative(step.settle.count()) ||
            !nonnegative(step.reachTimeout.count()) || step.reachTimeout.count() <= step.settle.count())
            throw std::invalid_argument(prefix + "hold and settling times must be non-negative; arrival timeout must exceed settling time.");
        bool any = false;
        for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
            if (!nonnegative(step.tolerance[channel])) throw std::invalid_argument(prefix + "tolerance must be finite and non-negative.");
            if (step.targets[channel]) {
                any = true;
                if (!std::isfinite(*step.targets[channel])) throw std::invalid_argument(prefix + "targets must be finite.");
                if (*step.targets[channel] < definition.limits.minimum[channel] ||
                    *step.targets[channel] > definition.limits.maximum[channel])
                    throw std::invalid_argument(prefix + "channel " + std::to_string(channel + 1) + " target is outside its configured limits.");
            }
        }
        if (!any) throw std::invalid_argument(prefix + "choose at least one channel target.");
    }
}
}
