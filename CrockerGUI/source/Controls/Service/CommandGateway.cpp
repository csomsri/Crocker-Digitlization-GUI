#include "Controls/Service/CommandGateway.hpp"
#include <cmath>
#include <stdexcept>

namespace crocker::controls {
std::uint64_t CommandGateway::Acquire(CommandOwner owner) {
    Require(CommandOwner::Manual);
    owner_ = owner;
    return ++generation_;
}
void CommandGateway::Release(CommandOwner owner, std::uint64_t generation) {
    if (owner_ == owner && generation_ == generation) owner_ = CommandOwner::Manual;
}
void CommandGateway::Require(CommandOwner owner) const {
    if (owner_ != owner) throw std::runtime_error("Automatic control owns the targets. Stop it before applying manual changes or starting another run.");
}
void CommandGateway::Replace(CommandOwner owner, const ControlCommand& command) {
    Require(owner);
    for (const auto& channel : command)
        if (!std::isfinite(channel.target)) throw std::invalid_argument("Channel targets must be finite.");
    command_ = command;
}
void CommandGateway::MergeSequence(const std::array<std::optional<double>, ChannelCount>& targets,
                                   const TelemetrySnapshot& telemetry, const SequenceTargetLimits& limits) {
    Require(CommandOwner::Sequence);
    auto next = command_;
    for (ChannelId ch = 0; ch < ChannelCount; ++ch) {
        if (!targets[ch]) continue;
        if (!std::isfinite(*targets[ch]) || *targets[ch] < limits.minimum[ch] || *targets[ch] > limits.maximum[ch])
            throw std::runtime_error("Sequence target is outside configured channel limits.");
        const auto& measured = telemetry.channels[ch];
        if (measured.interlocked || measured.status == ChannelStatus::Fault || measured.status == ChannelStatus::Interlocked)
            throw std::runtime_error("Cannot apply sequence target: channel fault or interlock.");
        next[ch] = {*targets[ch], true, true};
    }
    Replace(CommandOwner::Sequence, next);
}
void CommandGateway::Disable(const std::array<bool, ChannelCount>& channels) {
    for (ChannelId ch = 0; ch < ChannelCount; ++ch)
        if (channels[ch]) { command_[ch].on = false; command_[ch].enabled = false; }
}
void CommandGateway::CheckInterlocks(const TelemetrySnapshot& telemetry) const {
    for (ChannelId ch = 0; ch < ChannelCount; ++ch) {
        const auto& measured = telemetry.channels[ch];
        if ((command_[ch].on || command_[ch].enabled) &&
            (measured.interlocked || measured.status == ChannelStatus::Fault || measured.status == ChannelStatus::Interlocked))
            throw std::runtime_error("Cannot send an enabled command to a faulted or interlocked channel.");
    }
}
}
