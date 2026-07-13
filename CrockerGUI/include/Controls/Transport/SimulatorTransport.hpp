#pragma once

#include "Controls/Transport/ControlTransportBase.hpp"

#include <atomic>
#include <mutex>
#include <thread>

namespace crocker::controls {

class SimulatorTransport final : public ControlTransportBase {
public:
    explicit SimulatorTransport(double updateRateHz = 20.0);
    ~SimulatorTransport() override;

    void Start() override;
    void Stop() noexcept override;
    [[nodiscard]] bool IsRunning() const noexcept override;

    bool SendCommand(const ControlCommand& command) override;

    [[nodiscard]] TelemetrySnapshot LatestSnapshot() const override;
    [[nodiscard]] HealthStatus Health() const override;

private:
    void Run();
    void Step(double deltaSeconds);

    double updateRateHz_ = 20.0;
    double responseRatePerSecond_ = 4.0;

    std::atomic_bool running_{false};
    std::thread worker_;

    mutable std::mutex stateMutex_;
    ControlCommand command_{};
    TelemetrySnapshot snapshot_{};
    HealthStatus health_{};
};

} // namespace crocker::controls
