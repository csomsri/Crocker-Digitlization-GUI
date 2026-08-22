/**
 * @file ControlService.cpp
 * 
 * @brief Implementation of Control Service, handling 
 *        communication of REP Server and Frontend
 * 
 * Ownership of transport of data
 * 
 * @authors Chotrawit Benko, Claudio Lopez
 * 
 * @date 2026-08-21
 * 
 */
#include "Controls/Service/ControlService.hpp"

#include "Controls/Transport/ServerTransport.hpp"
#include "Controls/Transport/SimulatorTransport.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <stdexcept>
#include <thread>
#include <utility>

namespace crocker::controls {

ControlService::~ControlService()
{
    StopPidTrial();
    Stop();
}

/**
 * @brief Start Simulator Server and make data 
 *        transport to simulator in thread-safe manner
 * 
 *  Connects transport a shared pointer that send commands
 *  to the simulator
 * 
 */
void ControlService::StartSimulator(double updateRateHz)
{
    StopPidTrial();
    std::lock_guard<std::mutex> lifecycleLock(lifecycleMutex_);
    StopUnlocked();

    auto transport = std::make_shared<SimulatorTransport>(updateRateHz);
    transport->Start();

    std::lock_guard<std::mutex> lock(mutex_);
    transport_ = std::move(transport);
}

/**
 * @brief Start REP server given an endpoint and some scaling value
 *        that was configured beforehand
 * 
 * @param endpoint string containing the endpoint to bind to
 */
void ControlService::StartServer(const std::string& endpoint)
{
    ControlScaling scaling{};
    StartServer(endpoint, scaling);
}

/**
 * @brief Start REP server given an endpoint and some scaling value
 *        that was configured beforehand
 * 
 * @param endpoint string containing the endpoint to bind to
 * @param scaling array of scaling factors
 */
void ControlService::StartServer(const std::string& endpoint, const ControlScaling& scaling)
{
    StopPidTrial();
    std::lock_guard<std::mutex> lifecycleLock(lifecycleMutex_);
    StopUnlocked();

    auto transport = std::make_shared<ServerTransport>(endpoint, scaling);
    transport->Start();

    std::lock_guard<std::mutex> lock(mutex_);
    transport_ = std::move(transport);
}

/**
 * @brief Stop the Control Service in a thread-safe manner
 */
void ControlService::Stop() noexcept
{
    StopPidTrial();
    std::lock_guard<std::mutex> lifecycleLock(lifecycleMutex_);
    StopUnlocked();
}

/**
 * @brief Stops the Control Service in memory
 */
void ControlService::StopUnlocked() noexcept
{
    std::shared_ptr<ControlTransportBase> transport;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        transport = std::move(transport_);
    } // Unlock before waiting for the transport's worker thread to stop.

    if (transport) {
        transport->Stop();
    }
}

/**
 * @brief Check if the Control Service is running
 * 
 * @return true if it is running and not a nullptr
 * @return false if it is a nullptr or is not running
 */
bool ControlService::IsRunning() const noexcept
{
    std::shared_ptr<ControlTransportBase> transport;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        transport = transport_;
    }

    return transport != nullptr && transport->IsRunning();
}

/**
 * @brief Set the current channel to target in a threadsafe manner
 */
void ControlService::SetChannelTarget(ChannelId channel, double target)
{
    ValidateChannel(channel);

    std::lock_guard<std::mutex> lock(mutex_);
    pendingCommand_[channel].target = target;
}

/**
 * @brief Set Channel to be On (this is based on Trim Coil being on)
 * 
 * @param channel size_t, indicates which channel we are setting on
 * @param on boolean for setting the channel on or off
 */
void ControlService::SetChannelOn(ChannelId channel, bool on)
{
    ValidateChannel(channel);

    std::lock_guard<std::mutex> lock(mutex_);
    pendingCommand_[channel].on = on;
}

/**
 * @brief Given a channel, set it as enabled, allowing Changes through GUI
 * 
 * @param channel size_t, indicates which channel we are enabling
 * @param enabled boolean, indicates whether if we enabling or denabling
 */
void ControlService::SetChannelEnabled(ChannelId channel, bool enabled)
{
    ValidateChannel(channel);

    std::lock_guard<std::mutex> lock(mutex_);
    pendingCommand_[channel].enabled = enabled;
}

/**
 * @brief Set all channel states given a channel number
 * 
 * @param channel size_t, indicates which channel we are enabling
 * @param commmand struct, containing target value, enable, on
 */
void ControlService::SetChannelCommand(ChannelId channel, const ChannelCommand& command)
{
    ValidateChannel(channel);

    std::lock_guard<std::mutex> lock(mutex_);
    pendingCommand_[channel] = command;
}

/**
 * @brief Set command of the pending command 
 * 
 * @param command struct, containing target value, enable, on
 */
void ControlService::SetCommand(const ControlCommand& command)
{
    std::lock_guard<std::mutex> lock(mutex_);
    pendingCommand_ = command;
}

/**
 * @brief Set scaling factor based on the scaling we have done in Config
 * 
 * @param scaling mapping of scaling to channel
 */
void ControlService::SetScaling(const ControlScaling& scaling)
{
    std::shared_ptr<ControlTransportBase> transport;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        transport = transport_;
    }

    if (transport) {
        transport->SetScaling(scaling);
    }
}

/**
 * @brief Get the latest command to be processed in a thread-safe manner
 * 
 * @return pendingCommand_ (current Command)
 */
ControlCommand ControlService::PendingCommand() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return pendingCommand_;
}

/**
 * @brief Apply the commands that had been set
 * 
 * @return true if succesfully send command to transport
 * @return false if there is no transport to send to
 */
bool ControlService::ApplyCommand()
{
    std::shared_ptr<ControlTransportBase> transport;
    ControlCommand command;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!transport_) {
            return false;
        }

        transport = transport_;
        command = pendingCommand_;
    }

    return transport->SendCommand(command);
}

/**
 * @brief Disable all channels, not allowing transport
 * 
 * @return true if able to update and send to transport
 * @return false if unable to access transport
 */
bool ControlService::DisableAll()
{
    std::shared_ptr<ControlTransportBase> transport;
    ControlCommand command;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        for (ChannelCommand& channel : pendingCommand_) {
            channel.on = false;
            channel.enabled = false;
        }

        if (!transport_) {
            return false;
        }

        transport = transport_;
        command = pendingCommand_;
    }

    return transport->SendCommand(command);
}

// REVIEW THIS BEHAVIOR 
TelemetrySnapshot ControlService::LatestSnapshot() const
{
    std::shared_ptr<ControlTransportBase> transport;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        transport = transport_;
    }

    if (!transport) {
        return DisconnectedSnapshot();
    }

    return transport->LatestSnapshot();
}

// REVIEW THIS BEHAVIOR
HealthStatus ControlService::Health() const
{
    std::shared_ptr<ControlTransportBase> transport;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        transport = transport_;
    }

    if (!transport) {
        return DisconnectedHealth();
    }

    return transport->Health();
}

// ============================================================= START OF PID SECTION ============================================================= 

void ControlService::StartPidTrial(const PidTrialConfig& config)
{
    ValidatePidTrialConfig(config);
    StopPidTrial(false);

    const TelemetrySnapshot snapshot = LatestSnapshot();
    if (snapshot.connection != ConnectionState::Connected) {
        throw std::runtime_error("PID trial requires a connected control transport");
    }
    if (!snapshot.simulated && !config.dryRun && !config.allocationCalibrated) {
        throw std::invalid_argument("hardware PID trial requires a calibrated allocation");
    }
    if (!config.dryRun && !config.hardwareArmed) {
        throw std::invalid_argument("non-dry-run PID trial requires explicit hardware arming");
    }

    {
        std::lock_guard<std::mutex> lock(pidTrialMutex_);
        pidTrialStatus_ = {};
        pidTrialStatus_.state = PidTrialState::Running;
        pidTrialStatus_.message = config.dryRun ? "Dry-run PID trial running" : "PID trial running";
        pidAllocatedChannels_.fill(false);
        for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
            pidAllocatedChannels_[channel] = std::abs(config.allocation[channel]) > 0.0;
        }
    }
    pidTrialRunning_.store(true);
    pidTrialWorker_ = std::thread(&ControlService::RunPidTrial, this, config);
}

void ControlService::StopPidTrial(bool disableAllocatedChannels) noexcept
{
    pidTrialRunning_.store(false);
    if (pidTrialWorker_.joinable() && pidTrialWorker_.get_id() != std::this_thread::get_id()) {
        pidTrialWorker_.join();
    }

    std::array<bool, ChannelCount> allocated{};
    {
        std::lock_guard<std::mutex> lock(pidTrialMutex_);
        allocated = pidAllocatedChannels_;
        if (pidTrialStatus_.state == PidTrialState::Running) {
            pidTrialStatus_.state = PidTrialState::Stopped;
            pidTrialStatus_.message = "PID trial stopped";
        }
    }
    if (!disableAllocatedChannels) {
        return;
    }

    std::lock_guard<std::mutex> lock(mutex_);
    for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
        if (allocated[channel]) {
            pendingCommand_[channel].on = false;
            pendingCommand_[channel].enabled = false;
        }
    }
    if (transport_) {
        transport_->SendCommand(pendingCommand_);
    }
}

PidTrialStatus ControlService::PidTrialStatusSnapshot() const
{
    std::lock_guard<std::mutex> lock(pidTrialMutex_);
    return pidTrialStatus_;
}

void ControlService::RunPidTrial(PidTrialConfig config) noexcept
{
    using clock = std::chrono::steady_clock;
    const auto period = std::chrono::duration<double>(1.0 / config.updateRateHz);
    const auto started = clock::now();
    auto previous = started;
    auto nextTick = started;
    double integral = 0.0;
    double previousError = 0.0;
    bool hasPreviousError = false;
    ControlCommand lastCommand = PendingCommand();

    while (pidTrialRunning_.load()) {
        const auto now = clock::now();
        const double elapsed = std::chrono::duration<double>(now - started).count();
        const double dt = std::max(1.0e-6, std::chrono::duration<double>(now - previous).count());
        previous = now;
        if (elapsed >= config.durationSeconds) {
            std::lock_guard<std::mutex> lock(pidTrialMutex_);
            pidTrialStatus_.state = PidTrialState::Completed;
            pidTrialStatus_.message = "PID trial completed";
            pidTrialStatus_.elapsedSeconds = elapsed;
            pidTrialRunning_.store(false);
            break;
        }

        const TelemetrySnapshot snapshot = LatestSnapshot();
        const HealthStatus health = Health();
        const ChannelTelemetry& measurement = snapshot.channels[config.measurementChannel];
        const bool telemetryFresh = health.packetAgeMilliseconds <= config.telemetryTimeoutSeconds * 1000.0;
        const bool connectionHealthy = snapshot.connection == ConnectionState::Connected;
        const bool channelHealthy = !measurement.interlocked
            && measurement.status != ChannelStatus::Fault
            && measurement.status != ChannelStatus::Interlocked;
        if (!telemetryFresh || !connectionHealthy || !channelHealthy) {
            SetPidTrialFault(!telemetryFresh ? "Telemetry watchdog expired"
                : !connectionHealthy ? "Control transport disconnected"
                : "Measurement channel fault or interlock");
            DisableAll();
            pidTrialRunning_.store(false);
            break;
        }

        const double error = config.setpoint - measurement.actual;
        const double derivative = hasPreviousError ? (error - previousError) / dt : 0.0;
        const double candidateIntegral = integral + error * dt;
        double output = config.kp * error + config.ki * candidateIntegral + config.kd * derivative;
        bool saturated = false;
        bool rateLimited = false;
        ControlCommand command = lastCommand;

        for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
            if (std::abs(config.allocation[channel]) <= 0.0) {
                continue;
            }
            const double requested = config.commandBias[channel] + config.allocation[channel] * output;
            const double bounded = std::clamp(requested, config.minimumCommand[channel], config.maximumCommand[channel]);
            saturated = saturated || bounded != requested;
            const double maximumDelta = config.maximumSlewPerSecond[channel] * dt;
            const double slewed = std::clamp(
                bounded,
                lastCommand[channel].target - maximumDelta,
                lastCommand[channel].target + maximumDelta);
            rateLimited = rateLimited || slewed != bounded;
            command[channel] = ChannelCommand{slewed, true, true};
        }

        // Freeze integration whenever any allocated actuator saturates. This
        // conservative rule is valid even when allocation coefficients have
        // different signs.
        if (!saturated) {
            integral = candidateIntegral;
            output = config.kp * error + config.ki * integral + config.kd * derivative;
        }
        previousError = error;
        hasPreviousError = true;

        bool sent = true;
        if (!config.dryRun) {
            SetCommand(command);
            sent = ApplyCommand();
            lastCommand = command;
        }
        if (!sent) {
            SetPidTrialFault("Control command was not acknowledged");
            DisableAll();
            pidTrialRunning_.store(false);
            break;
        }

        {
            std::lock_guard<std::mutex> lock(pidTrialMutex_);
            pidTrialStatus_.elapsedSeconds = elapsed;
            pidTrialStatus_.measuredField = measurement.actual;
            pidTrialStatus_.error = error;
            pidTrialStatus_.controlOutput = output;
            ++pidTrialStatus_.iterations;
            pidTrialStatus_.saturated = saturated;
            pidTrialStatus_.rateLimited = rateLimited;
            pidTrialStatus_.watchdogHealthy = true;
        }

        nextTick += std::chrono::duration_cast<clock::duration>(period);
        std::this_thread::sleep_until(nextTick);
    }
}

void ControlService::SetPidTrialFault(const std::string& message) noexcept
{
    std::lock_guard<std::mutex> lock(pidTrialMutex_);
    pidTrialStatus_.state = PidTrialState::Faulted;
    pidTrialStatus_.message = message;
    pidTrialStatus_.watchdogHealthy = false;
}

void ControlService::ValidatePidTrialConfig(const PidTrialConfig& config)
{
    ValidateChannel(config.measurementChannel);
    const double scalars[] = {
        config.setpoint, config.kp, config.ki, config.kd, config.updateRateHz,
        config.durationSeconds, config.telemetryTimeoutSeconds,
    };
    for (double value : scalars) {
        if (!std::isfinite(value)) {
            throw std::invalid_argument("PID trial values must be finite");
        }
    }
    if (config.kp < 0.0 || config.ki < 0.0 || config.kd < 0.0) {
        throw std::invalid_argument("PID gains must be non-negative");
    }
    if (config.updateRateHz <= 0.0 || config.durationSeconds <= 0.0
        || config.telemetryTimeoutSeconds <= 0.0) {
        throw std::invalid_argument("PID timing values must be positive");
    }
    bool hasAllocation = false;
    for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
        const double allocation = config.allocation[channel];
        if (!std::isfinite(allocation) || !std::isfinite(config.commandBias[channel])
            || !std::isfinite(config.minimumCommand[channel])
            || !std::isfinite(config.maximumCommand[channel])
            || !std::isfinite(config.maximumSlewPerSecond[channel])) {
            throw std::invalid_argument("PID allocation and safety values must be finite");
        }
        if (std::abs(allocation) <= 0.0) {
            continue;
        }
        hasAllocation = true;
        if (config.minimumCommand[channel] >= config.maximumCommand[channel]
            || config.maximumSlewPerSecond[channel] <= 0.0) {
            throw std::invalid_argument("allocated channels require ordered limits and positive slew rates");
        }
    }
    if (!hasAllocation) {
        throw std::invalid_argument("PID trial requires at least one allocated channel");
    }
}

// ============================================================= END OF PID SECTION ============================================================= 

/**
 * @brief Checks whether the channel being accessed is valid
 * 
 * @param channel size_t, indicating channel index
 * 
 * @throw std::out_of_range if given channel is not valid
 */
void ControlService::ValidateChannel(ChannelId channel)
{
    if (!IsValidChannel(channel)) {
        throw std::out_of_range("control channel index is out of range");
    }
}

/**
 * @brief Disconnect Snapshot
 * 
 * @return snapshot
 */
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
