#pragma once

#include "Controls/ControlTypes.hpp"
#include "Controls/Transport/ControlTransportBase.hpp"

#include <memory>
#include <mutex>
#include <string>

namespace crocker::controls {

class ControlService {
public:
    ControlService() = default;
    ~ControlService();

    ControlService(const ControlService&) = delete;
    ControlService& operator=(const ControlService&) = delete;
    ControlService(ControlService&&) = delete;
    ControlService& operator=(ControlService&&) = delete;

    void StartSimulator(double updateRateHz = 20.0);
    void StartServer(const std::string& endpoint = "tcp://0.0.0.0:5555");
    void Stop() noexcept;
    [[nodiscard]] bool IsRunning() const noexcept;

    void SetChannelTarget(ChannelId channel, double target);
    void SetChannelOn(ChannelId channel, bool on);
    void SetChannelEnabled(ChannelId channel, bool enabled);
    void SetChannelCommand(ChannelId channel, const ChannelCommand& command);
    void SetCommand(const ControlCommand& command);
    [[nodiscard]] ControlCommand PendingCommand() const;

    bool ApplyCommand();
    bool DisableAll();

    [[nodiscard]] TelemetrySnapshot LatestSnapshot() const;
    [[nodiscard]] HealthStatus Health() const;

private:
    static void ValidateChannel(ChannelId channel);
    static TelemetrySnapshot DisconnectedSnapshot();
    static HealthStatus DisconnectedHealth();

    mutable std::mutex mutex_;
    std::unique_ptr<ControlTransportBase> transport_;
    ControlCommand pendingCommand_{};
};

} // namespace crocker::controls
