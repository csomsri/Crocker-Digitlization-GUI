/**
 * @file SeverTranscport.cpp
 * 
 * @brief Imlementation of Transporting Data to REP Server
 * 
 * Responsible for keeping flags, statuses, and scaling
 * 
 * @authors Chotrawit Benko, Claudio Lopez
 * 
 * @date 2026-08-22
 */

#include "Controls/Transport/ServerTransport.hpp"

#include "Controls/Network/ZMQProtocol.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <thread>
#include <utility>

namespace crocker::controls {
namespace {

namespace Protocol = Crocker::Controls::Network::ZMQProtocol;

/**
 * @brief This function keeps in tract of the system clock (Unix)
 * 
 * @return double, time in seconds from now since epoch
 */
double UnixSeconds()
{
    const auto now = std::chrono::system_clock::now();
    return std::chrono::duration<double>(now.time_since_epoch()).count();
}

/**
 * @brief Check if current flags lets us make changes
 * 
 * @param on boolean, true if machine is on, false / off it is not
 * @param enabled boolean, true if GUI change is enabled, false if not
 * 
 * @return ChannelStatus Disabled if not enable
 * @return ChannelStatus Off if not On
 * @return ChannelStatus Ready if on and enabled
 */
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

/**
 * @brief build a mask based on command being built to send
 * 
 * @param command ControlCommand, a list containing which channels to change
 * 
 * @return uint64_t, stream of 64 bits as a bitmask to send to server
 */
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

/**
 * @brief Take raw values and convert to Engineering
 * 
 * @param raw default value taken straight for LabVIEW
 * @param scaling scaling factor
 * 
 * @return double, engineering values scaled from raw
 */
double RawToEngineering(double raw, const LinearChannelScaling& scaling)
{
    if (!scaling.enabled) {
        return raw;
    }

    if (scaling.rawToEngineeringUsesCurve) {
        const auto& curve = scaling.rawToEngineeringCurve;
        const auto upper = std::upper_bound(
            curve.begin(),
            curve.end(),
            raw,
            [](double value, const ScalingPoint& point) {
                return value < point.input;
            });
        if (upper == curve.begin()) {
            return curve.front().output;
        }
        if (upper == curve.end()) {
            return curve.back().output;
        }
        const ScalingPoint& high = *upper;
        const ScalingPoint& low = *(upper - 1);
        const double span = high.input - low.input;
        if (std::abs(span) <= 0.0) {
            return low.output;
        }
        const double fraction = (raw - low.input) / span;
        return low.output + fraction * (high.output - low.output);
    }

    return raw * scaling.rawToEngineeringGain + scaling.rawToEngineeringOffset;
}

/**
 * @brief Takes Engineering values from what we see to raw
 * 
 * @param engineering values from the machine in engineering values
 * @param scaling scaling factor
 * 
 * @return double value scaled from engineering to raw
 */
double EngineeringToRaw(double engineering, const LinearChannelScaling& scaling)
{
    if (!scaling.enabled) {
        return engineering;
    }

    if (scaling.engineeringToRawUsesCurve) {
        const auto& curve = scaling.engineeringToRawCurve;
        const auto upper = std::upper_bound(
            curve.begin(),
            curve.end(),
            engineering,
            [](double value, const ScalingPoint& point) {
                return value < point.input;
            });
        if (upper == curve.begin()) {
            return curve.front().output;
        }
        if (upper == curve.end()) {
            return curve.back().output;
        }
        const ScalingPoint& high = *upper;
        const ScalingPoint& low = *(upper - 1);
        const double span = high.input - low.input;
        if (std::abs(span) <= 0.0) {
            return low.output;
        }
        const double fraction = (engineering - low.input) / span;
        return low.output + fraction * (high.output - low.output);
    }

    return engineering * scaling.engineeringToRawGain + scaling.engineeringToRawOffset;
}

/**
 * @brief check if curve is valid
 * 
 * @return true, if curve if curve has 2 or more points
 * @return false, if curve has less than 2 points
 */
bool SanitizeCurve(std::vector<ScalingPoint>& curve)
{
    curve.erase(
        std::remove_if(
            curve.begin(),
            curve.end(),
            [](const ScalingPoint& point) {
                return !std::isfinite(point.input) || !std::isfinite(point.output);
            }),
        curve.end());
    std::sort(
        curve.begin(),
        curve.end(),
        [](const ScalingPoint& left, const ScalingPoint& right) {
            return left.input < right.input;
        });
    curve.erase(
        std::unique(
            curve.begin(),
            curve.end(),
            [](const ScalingPoint& left, const ScalingPoint& right) {
                return left.input == right.input;
            }),
        curve.end());
    return curve.size() >= 2;
}

/**
 * @brief Scaling is not just infinity and is some factor
 * 
 * @param scaling ControlScaling, array of scaling factors
 * 
 * @return scaling after checking if valid if not valid return empty
 * 
 */
ControlScaling SanitizeScaling(ControlScaling scaling)
{
    for (LinearChannelScaling& channel : scaling) {
        const bool finite = std::isfinite(channel.rawToEngineeringGain)
            && std::isfinite(channel.rawToEngineeringOffset)
            && std::isfinite(channel.engineeringToRawGain)
            && std::isfinite(channel.engineeringToRawOffset);
        if (!finite) {
            channel = {};
            continue;
        }
        if (channel.rawToEngineeringUsesCurve) {
            channel.rawToEngineeringUsesCurve = SanitizeCurve(channel.rawToEngineeringCurve);
        }
        if (channel.engineeringToRawUsesCurve) {
            channel.engineeringToRawUsesCurve = SanitizeCurve(channel.engineeringToRawCurve);
        }
    }
    return scaling;
}

/**
 * @brief build targets to the machine from the UI
 * 
 * @param command commands that the Operator Gave
 * @param scaling list of scaling factors
 * 
 * @return target values for the server
 */
ZMQServer::TargetValues BuildTargets(const ControlCommand& command, const ControlScaling& scaling)
{
    ZMQServer::TargetValues targets{};
    for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
        targets[channel] = EngineeringToRaw(command[channel].target, scaling[channel]);
    }

    return targets;
}

} // namespace

/**
 * @brief Set up the server communication 
 * 
 * @param endpoint location to bind to
 */
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

/**
 * @brief Set up server communication with scaling
 * 
 * @param endpoint location to bind to
 * @param scaling list of scaling factors
 */
ServerTransport::ServerTransport(std::string endpoint, ControlScaling scaling)
    : endpoint_(std::move(endpoint))
    , scaling_(SanitizeScaling(scaling))
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

/**
 * @brief Start server connection in a thread safe manner
 */
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

/**
 * @brief Stop server connection in a thread safe manner
 */
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

/**
 * @brief Check if server connection is running
 * 
 * @return true if both server and worker is running
 * @return false if worker thread or server is not running
 */
bool ServerTransport::IsRunning() const noexcept
{
    return running_.load() && server_.IsRunning();
}

/**
 * @brief send a command to the server
 * 
 * @param command list of command for trim coil values
 * 
 * @return true , if able to send
 * @return false , if server is not running
 */
bool ServerTransport::SendCommand(const ControlCommand& command)
{
    if (!running_.load()) {
        return false;
    }

    server_.SetReply(BuildTargets(command, ScalingSnapshot()), BuildBitmask(command));

    std::lock_guard<std::mutex> lock(stateMutex_);
    ++health_.sentPackets;
    return true;
}

/**
 * @brief Set scaling factors in a thread safe manner
 */
void ServerTransport::SetScaling(const ControlScaling& scaling)
{
    std::lock_guard<std::mutex> lock(scalingMutex_);
    scaling_ = SanitizeScaling(scaling);
}

/**
 * @brief Check for snapshot
 * 
 * @return snapshot
 */
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

/**
 * @brief Server transport main loop
 * 
 * While the server is running Aply packet and give to server
 * 
 */
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

/**
 * @brief Update relevent information sent by Operator
 */
void ServerTransport::ApplyPacket(const Packet& packet)
{
    const double now = UnixSeconds();
    const Protocol::Timestamp normalizedTimestamp = Protocol::NormalizeTimestamp(packet.timestamp);
    const ControlScaling scaling = ScalingSnapshot();

    std::lock_guard<std::mutex> lock(stateMutex_);

    for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
        ChannelTelemetry& telemetry = snapshot_.channels[channel];

        if (channel < packet.channels.size()) {
            telemetry.raw = packet.channels[channel];
            telemetry.actual = RawToEngineering(packet.channels[channel], scaling[channel]);
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

ControlScaling ServerTransport::ScalingSnapshot() const
{
    std::lock_guard<std::mutex> lock(scalingMutex_);
    return scaling_;
}

} // namespace crocker::controls
