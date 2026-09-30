#pragma once

#include "Controls/ControlTypes.hpp"
#include "Controls/Sequencer/SequenceRunner.hpp"
#include "Controls/Service/CommandGateway.hpp"
#include "Controls/Transport/ControlTransportBase.hpp"

#include <memory>
#include <mutex>
#include <string>
#include <atomic>
#include <thread>

namespace crocker::controls {

class ControlService {
public:
    ControlService() = default;
    ~ControlService();

    ControlService(const ControlService&) = delete;
    ControlService& operator=(const ControlService&) = delete;
    ControlService(ControlService&&) = delete;
    ControlService& operator=(ControlService&&) = delete;

    void StartSimulator(double updateRateHz = 60.0);
    void StartServer(const std::string& endpoint = "tcp://0.0.0.0:5555");
    void StartServer(const std::string& endpoint, const ControlScaling& scaling);
    void Stop() noexcept;
    [[nodiscard]] bool IsRunning() const noexcept;

    void SetChannelTarget(ChannelId channel, double target);
    void SetChannelOn(ChannelId channel, bool on);
    void SetChannelEnabled(ChannelId channel, bool enabled);
    void SetChannelCommand(ChannelId channel, const ChannelCommand& command);
    void SetCommand(const ControlCommand& command);
    void SetScaling(const ControlScaling& scaling);
    [[nodiscard]] ControlCommand PendingCommand() const;

    bool ApplyCommand();
    bool DisableAll();

    [[nodiscard]] TelemetrySnapshot LatestSnapshot() const;
    [[nodiscard]] HealthStatus Health() const;

    void StartPidTrial(const PidTrialConfig& config);
    void SetPidBeamMeasurement(double nanoamps, double timestampUnixSeconds, bool valid);
    void StopPidTrial(bool disableAllocatedChannels = true) noexcept;
    [[nodiscard]] PidTrialStatus PidTrialStatusSnapshot() const;

    void StartSequence(const SequenceRunConfig& config);
    void StopSequence(bool disableChannels = false) noexcept;
    [[nodiscard]] SequenceRunStatus SequenceStatusSnapshot() const;
    [[nodiscard]] std::vector<SequenceEvent> SequenceEventsSnapshot() const;

private:
    double pidBeamNanoamps_ = 0.0;
    double pidBeamTimestamp_ = 0.0;
    bool pidBeamValid_ = false;
    void StopUnlocked() noexcept;
    void RunPidTrial(PidTrialConfig config) noexcept;
    void SetPidTrialFault(const std::string& message) noexcept;
    static void ValidatePidTrialConfig(const PidTrialConfig& config);
    bool DisableAllFromWorker() noexcept;

    static void ValidateChannel(ChannelId channel);
    static TelemetrySnapshot DisconnectedSnapshot();
    static HealthStatus DisconnectedHealth();

    // Serializes transport startup, replacement, and shutdown.
    std::mutex lifecycleMutex_;
    mutable std::mutex mutex_;
    std::shared_ptr<ControlTransportBase> transport_;
    CommandGateway commandGateway_;
    std::recursive_mutex operationMutex_;
    std::uint64_t pidLease_ = 0;

    mutable std::mutex pidTrialMutex_;
    std::thread pidTrialWorker_;
    std::atomic_bool pidTrialRunning_{false};
    PidTrialStatus pidTrialStatus_{};
    bool pidTrialDryRun_ = true; // Protected by pidTrialMutex_.
    std::array<bool, ChannelCount> pidAllocatedChannels_{};

    SequenceRunner sequenceRunner_;

};

} // namespace crocker::controls
