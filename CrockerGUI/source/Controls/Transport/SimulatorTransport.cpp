#include "Controls/Transport/SimulatorTransport.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>

namespace crocker::controls {
namespace {

double UnixSeconds()
{
    const auto now = std::chrono::system_clock::now();
    return std::chrono::duration<double>(now.time_since_epoch()).count();
}

ChannelStatus StatusForCommand(const ChannelCommand& command)
{
    if (!command.enabled) {
        return ChannelStatus::Disabled;
    }

    if (!command.on) {
        return ChannelStatus::Off;
    }

    return ChannelStatus::Ready;
}

} // namespace

SimulatorTransport::SimulatorTransport(double updateRateHz)
    : updateRateHz_(std::max(1.0, updateRateHz))
{
    const double now = UnixSeconds();
    snapshot_.timestampUnixSeconds = now;
    snapshot_.connection = ConnectionState::Disconnected;
    snapshot_.simulated = true;

    health_.connection = ConnectionState::Disconnected;
    health_.endpoint = "simulator://local";
    health_.lastPacketUnixSeconds = now;
    health_.updateRateHz = updateRateHz_;
    health_.simulated = true;
}

SimulatorTransport::~SimulatorTransport()
{
    Stop();
}

void SimulatorTransport::Start()
{
    bool expected = false;
    if (!running_.compare_exchange_strong(expected, true)) {
        return;
    }

    {
        std::lock_guard<std::mutex> lock(stateMutex_);
        snapshot_.connection = ConnectionState::Connected;
        snapshot_.simulated = true;
        health_.connection = ConnectionState::Connected;
        health_.lastError.clear();
    }

    worker_ = std::thread(&SimulatorTransport::Run, this);
}

void SimulatorTransport::Stop() noexcept
{
    const bool wasRunning = running_.exchange(false);
    if (worker_.joinable()) {
        worker_.join();
    }

    if (wasRunning) {
        std::lock_guard<std::mutex> lock(stateMutex_);
        snapshot_.connection = ConnectionState::Disconnected;
        health_.connection = ConnectionState::Disconnected;
    }
}

bool SimulatorTransport::IsRunning() const noexcept
{
    return running_.load();
}

bool SimulatorTransport::SendCommand(const ControlCommand& command)
{
    std::lock_guard<std::mutex> lock(stateMutex_);
    command_ = command;
    ++health_.sentPackets;
    return true;
}

TelemetrySnapshot SimulatorTransport::LatestSnapshot() const
{
    std::lock_guard<std::mutex> lock(stateMutex_);
    return snapshot_;
}

HealthStatus SimulatorTransport::Health() const
{
    std::lock_guard<std::mutex> lock(stateMutex_);
    HealthStatus health = health_;
    health.packetAgeMilliseconds = (UnixSeconds() - health.lastPacketUnixSeconds) * 1000.0;
    return health;
}

void SimulatorTransport::Run()
{
    using clock = std::chrono::steady_clock;
    const auto frameDuration = std::chrono::duration<double>(1.0 / updateRateHz_);
    auto previous = clock::now();
    auto nextFrame = previous;

    while (running_.load()) {
        const auto now = clock::now();
        const double deltaSeconds = std::chrono::duration<double>(now - previous).count();
        previous = now;

        Step(deltaSeconds);

        nextFrame += std::chrono::duration_cast<clock::duration>(frameDuration);
        std::this_thread::sleep_until(nextFrame);
    }
}

void SimulatorTransport::Step(double deltaSeconds)
{
    const double now = UnixSeconds();
    const double alpha = std::clamp(responseRatePerSecond_ * deltaSeconds, 0.0, 1.0);

    std::lock_guard<std::mutex> lock(stateMutex_);

    for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
        const ChannelCommand& command = command_[channel];
        const double target = command.enabled && command.on ? command.target : 0.0;
        ChannelTelemetry& telemetry = snapshot_.channels[channel];

        telemetry.actual += (target - telemetry.actual) * alpha;
        telemetry.raw = telemetry.actual;
        telemetry.on = command.on;
        telemetry.enabled = command.enabled;
        telemetry.interlocked = false;
        telemetry.status = StatusForCommand(command);
    }

    snapshot_.timestampUnixSeconds = now;
    snapshot_.latencyMilliseconds = 0.0;
    snapshot_.connection = ConnectionState::Connected;
    snapshot_.simulated = true;
    ++snapshot_.sequenceNumber;

    health_.connection = ConnectionState::Connected;
    health_.lastPacketUnixSeconds = now;
    health_.packetAgeMilliseconds = 0.0;
    health_.updateRateHz = updateRateHz_;
    ++health_.receivedPackets;
}

} // namespace crocker::controls
