#include "Controls/Transport/ServerTransport.hpp"

#include "Controls/Network/ZMQProtocol.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <thread>
#include <utility>

namespace crocker::controls {
namespace {

namespace Protocol = Crocker::Controls::Network::ZMQProtocol;

double UnixSeconds()
{
    const auto now = std::chrono::system_clock::now();
    return std::chrono::duration<double>(now.time_since_epoch()).count();
}

ChannelStatus StatusFromFlags(bool on, bool enabled)
{
    if (!enabled) {
        return ChannelStatus::Disabled;
    }

    if (!on) {
        return ChannelStatus::Off;
    }

    return ChannelStatus::Ready;
}

std::uint64_t BuildBitmask(const ControlCommand& command)
{
    std::uint64_t bitmask = 0;
    for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
        if (command[channel].on) {
            bitmask |= 1ULL << channel;
        }
        if (command[channel].enabled) {
            bitmask |= 1ULL << (ChannelCount + channel);
        }
    }

    return bitmask;
}

ZMQServer::TargetValues BuildTargets(const ControlCommand& command)
{
    ZMQServer::TargetValues targets{};
    for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
        targets[channel] = command[channel].target;
    }

    return targets;
}

} // namespace

ServerTransport::ServerTransport(std::string endpoint)
    : endpoint_(std::move(endpoint))
    , server_(endpoint_)
{
    snapshot_.connection = ConnectionState::Disconnected;
    snapshot_.simulated = false;

    health_.connection = ConnectionState::Disconnected;
    health_.endpoint = endpoint_;
    health_.simulated = false;
}

ServerTransport::~ServerTransport()
{
    Stop();
}

void ServerTransport::Start()
{
    bool expected = false;
    if (!running_.compare_exchange_strong(expected, true)) {
        return;
    }

    {
        std::lock_guard<std::mutex> lock(stateMutex_);
        snapshot_.connection = ConnectionState::Connecting;
        health_.connection = ConnectionState::Connecting;
        health_.lastError.clear();
    }

    server_.Start();
    worker_ = std::thread(&ServerTransport::Run, this);
}

void ServerTransport::Stop() noexcept
{
    const bool wasRunning = running_.exchange(false);
    if (worker_.joinable()) {
        worker_.join();
    }

    server_.Stop();

    if (wasRunning) {
        std::lock_guard<std::mutex> lock(stateMutex_);
        snapshot_.connection = ConnectionState::Disconnected;
        health_.connection = ConnectionState::Disconnected;
    }
}

bool ServerTransport::IsRunning() const noexcept
{
    return running_.load() && server_.IsRunning();
}

bool ServerTransport::SendCommand(const ControlCommand& command)
{
    server_.SetTargets(BuildTargets(command));
    server_.SetBitmask(BuildBitmask(command));

    std::lock_guard<std::mutex> lock(stateMutex_);
    ++health_.sentPackets;
    return true;
}

TelemetrySnapshot ServerTransport::LatestSnapshot() const
{
    std::lock_guard<std::mutex> lock(stateMutex_);
    return snapshot_;
}

HealthStatus ServerTransport::Health() const
{
    std::lock_guard<std::mutex> lock(stateMutex_);
    HealthStatus health = health_;
    if (health.lastPacketUnixSeconds > 0.0) {
        health.packetAgeMilliseconds = (UnixSeconds() - health.lastPacketUnixSeconds) * 1000.0;
    }
    return health;
}

void ServerTransport::Run()
{
    while (running_.load()) {
        Packet packet;
        bool receivedAny = false;

        while (server_.TryPopPacket(packet)) {
            receivedAny = true;
            ApplyPacket(packet);
        }

        if (!receivedAny) {
            UpdateHealthPacketAge();
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
    }
}

void ServerTransport::ApplyPacket(const Packet& packet)
{
    const double now = UnixSeconds();
    const Protocol::Timestamp normalizedTimestamp = Protocol::NormalizeTimestamp(packet.timestamp);

    std::lock_guard<std::mutex> lock(stateMutex_);

    for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
        ChannelTelemetry& telemetry = snapshot_.channels[channel];

        if (channel < packet.channels.size()) {
            telemetry.actual = packet.channels[channel];
            telemetry.raw = packet.channels[channel];
        }

        const bool on = ((packet.bitmask >> channel) & 1ULL) != 0;
        const bool enabled = ((packet.bitmask >> (ChannelCount + channel)) & 1ULL) != 0;
        telemetry.on = on;
        telemetry.enabled = enabled;
        telemetry.interlocked = false;
        telemetry.status = StatusFromFlags(on, enabled);
    }

    snapshot_.timestampUnixSeconds = normalizedTimestamp.unixSeconds;
    snapshot_.latencyMilliseconds = packet.latencyMs.value_or((now - normalizedTimestamp.unixSeconds) * 1000.0);
    snapshot_.connection = ConnectionState::Connected;
    snapshot_.simulated = false;
    ++snapshot_.sequenceNumber;

    health_.connection = ConnectionState::Connected;
    health_.endpoint = server_.BoundEndpoint().empty() ? endpoint_ : server_.BoundEndpoint();
    health_.lastPacketUnixSeconds = now;
    health_.packetAgeMilliseconds = 0.0;
    ++health_.receivedPackets;
}

void ServerTransport::UpdateHealthPacketAge()
{
    std::lock_guard<std::mutex> lock(stateMutex_);
    if (health_.lastPacketUnixSeconds > 0.0) {
        health_.packetAgeMilliseconds = (UnixSeconds() - health_.lastPacketUnixSeconds) * 1000.0;
        if (health_.packetAgeMilliseconds > 2000.0) {
            health_.connection = ConnectionState::Degraded;
            snapshot_.connection = ConnectionState::Degraded;
        }
    }

    if (!server_.IsRunning() && running_.load()) {
        health_.connection = ConnectionState::Faulted;
        snapshot_.connection = ConnectionState::Faulted;
        health_.lastError = "ZMQ server stopped unexpectedly";
    }
}

} // namespace crocker::controls
