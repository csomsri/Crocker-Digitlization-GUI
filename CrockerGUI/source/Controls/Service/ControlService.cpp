#include "Controls/Service/ControlService.hpp"

#include "Controls/Transport/ServerTransport.hpp"
#include "Controls/Transport/SimulatorTransport.hpp"

#include <stdexcept>
#include <utility>

namespace crocker::controls {

ControlService::~ControlService()
{
    Stop();
}

void ControlService::StartSimulator(double updateRateHz)
{
    Stop();

    auto transport = std::make_unique<SimulatorTransport>(updateRateHz);
    transport->Start();

    std::lock_guard<std::mutex> lock(mutex_);
    transport_ = std::move(transport);
}

void ControlService::StartServer(const std::string& endpoint)
{
    Stop();

    auto transport = std::make_unique<ServerTransport>(endpoint);
    transport->Start();

    std::lock_guard<std::mutex> lock(mutex_);
    transport_ = std::move(transport);
}

void ControlService::Stop() noexcept
{
    std::unique_ptr<ControlTransportBase> transport;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        transport = std::move(transport_);
    }

    if (transport) {
        transport->Stop();
    }
}

bool ControlService::IsRunning() const noexcept
{
    std::lock_guard<std::mutex> lock(mutex_);
    return transport_ != nullptr && transport_->IsRunning();
}

void ControlService::SetChannelTarget(ChannelId channel, double target)
{
    ValidateChannel(channel);

    std::lock_guard<std::mutex> lock(mutex_);
    pendingCommand_[channel].target = target;
}

void ControlService::SetChannelOn(ChannelId channel, bool on)
{
    ValidateChannel(channel);

    std::lock_guard<std::mutex> lock(mutex_);
    pendingCommand_[channel].on = on;
}

void ControlService::SetChannelEnabled(ChannelId channel, bool enabled)
{
    ValidateChannel(channel);

    std::lock_guard<std::mutex> lock(mutex_);
    pendingCommand_[channel].enabled = enabled;
}

void ControlService::SetChannelCommand(ChannelId channel, const ChannelCommand& command)
{
    ValidateChannel(channel);

    std::lock_guard<std::mutex> lock(mutex_);
    pendingCommand_[channel] = command;
}

void ControlService::SetCommand(const ControlCommand& command)
{
    std::lock_guard<std::mutex> lock(mutex_);
    pendingCommand_ = command;
}

ControlCommand ControlService::PendingCommand() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return pendingCommand_;
}

bool ControlService::ApplyCommand()
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (!transport_) {
        return false;
    }

    return transport_->SendCommand(pendingCommand_);
}

bool ControlService::DisableAll()
{
    std::lock_guard<std::mutex> lock(mutex_);
    for (ChannelCommand& command : pendingCommand_) {
        command.on = false;
        command.enabled = false;
    }

    if (!transport_) {
        return false;
    }

    return transport_->SendCommand(pendingCommand_);
}

TelemetrySnapshot ControlService::LatestSnapshot() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (!transport_) {
        return DisconnectedSnapshot();
    }

    return transport_->LatestSnapshot();
}

HealthStatus ControlService::Health() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (!transport_) {
        return DisconnectedHealth();
    }

    return transport_->Health();
}

void ControlService::ValidateChannel(ChannelId channel)
{
    if (!IsValidChannel(channel)) {
        throw std::out_of_range("control channel index is out of range");
    }
}

TelemetrySnapshot ControlService::DisconnectedSnapshot()
{
    TelemetrySnapshot snapshot;
    snapshot.connection = ConnectionState::Disconnected;
    snapshot.simulated = false;
    return snapshot;
}

HealthStatus ControlService::DisconnectedHealth()
{
    HealthStatus health;
    health.connection = ConnectionState::Disconnected;
    health.endpoint = "";
    health.lastError = "No control transport is active";
    health.simulated = false;
    return health;
}

} // namespace crocker::controls
