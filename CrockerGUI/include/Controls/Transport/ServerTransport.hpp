#pragma once

#include "Controls/Network/ZMQServer.hpp"
#include "Controls/Transport/ControlTransportBase.hpp"

#include <atomic>
#include <mutex>
#include <string>
#include <thread>

namespace crocker::controls {

class ServerTransport final : public ControlTransportBase {
public:
    explicit ServerTransport(std::string endpoint = "tcp://0.0.0.0:5555");
    ~ServerTransport() override;

    void Start() override;
    void Stop() noexcept override;
    [[nodiscard]] bool IsRunning() const noexcept override;

    bool SendCommand(const ControlCommand& command) override;

    [[nodiscard]] TelemetrySnapshot LatestSnapshot() const override;
    [[nodiscard]] HealthStatus Health() const override;

private:
    using Packet = ZMQServer::Packet;

    void Run();
    void ApplyPacket(const Packet& packet);
    void UpdateHealthPacketAge();

    std::string endpoint_;
    ZMQServer server_;

    std::atomic_bool running_{false};
    std::thread worker_;

    mutable std::mutex stateMutex_;
    TelemetrySnapshot snapshot_{};
    HealthStatus health_{};
};

} // namespace crocker::controls
