#pragma once
#include "Controls/ControlTypes.hpp"
#include <cstdint>

namespace crocker::controls {
enum class CommandOwner { Manual, Sequence, Pid };
// ControlService holds its command mutex for every gateway operation and send.
// The generation prevents a completed worker from releasing a newer owner's lease.
class CommandGateway {
public:
    std::uint64_t Acquire(CommandOwner owner);
    void Release(CommandOwner owner, std::uint64_t generation);
    void Require(CommandOwner owner) const;
    void Replace(CommandOwner owner, const ControlCommand& command);
    void MergeSequence(const std::array<std::optional<double>, ChannelCount>& targets,
                       const TelemetrySnapshot& telemetry, const SequenceTargetLimits& limits = {});
    void Disable(const std::array<bool, ChannelCount>& channels);
    void CheckInterlocks(const TelemetrySnapshot& telemetry) const;
    CommandOwner Owner() const noexcept { return owner_; }
    const ControlCommand& Command() const noexcept { return command_; }
private:
    CommandOwner owner_ = CommandOwner::Manual;
    std::uint64_t generation_ = 0;
    ControlCommand command_{};
};
}
