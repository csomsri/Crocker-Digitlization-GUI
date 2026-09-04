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
    StopSequence();
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
    StopSequence();
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
    StopSequence();
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
    StopSequence();
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
    double saturationSeconds = 0.0;
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
        if (std::abs(error) > config.maxAbsoluteError) {
            SetPidTrialFault("Absolute error abort limit exceeded");
            DisableAll();
            pidTrialRunning_.store(false);
            break;
        }
        if (measurement.actual - config.setpoint > config.maxOvershoot) {
            SetPidTrialFault("Overshoot abort limit exceeded");
            DisableAll();
            pidTrialRunning_.store(false);
            break;
        }
        const double derivative = hasPreviousError ? (error - previousError) / dt : 0.0;
        const double candidateIntegral = integral + error * dt;
        double output = config.kp * error + config.ki * candidateIntegral + config.kd * derivative;
        if (std::abs(output) > config.maxControlOutput) {
            SetPidTrialFault("Control-output abort limit exceeded");
            DisableAll();
            pidTrialRunning_.store(false);
            break;
        }
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
        saturationSeconds = saturated ? saturationSeconds + dt : 0.0;
        if (saturationSeconds > config.maxSaturationSeconds) {
            SetPidTrialFault("Command saturation persisted beyond abort limit");
            DisableAll();
            pidTrialRunning_.store(false);
            break;
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
        config.maxAbsoluteError, config.maxOvershoot, config.maxControlOutput,
        config.maxSaturationSeconds,
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
        || config.telemetryTimeoutSeconds <= 0.0 || config.maxAbsoluteError <= 0.0
        || config.maxOvershoot <= 0.0 || config.maxControlOutput <= 0.0
        || config.maxSaturationSeconds <= 0.0) {
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

void ControlService::StartSequence(const SequenceRunConfig& config)
{
    ValidateSequenceRunConfig(config);
    StopPidTrial();
    StopSequence(false);

    const TelemetrySnapshot snapshot = LatestSnapshot();
    if (config.requireConnected && snapshot.connection != ConnectionState::Connected) {
        throw std::runtime_error("sequence requires a connected control transport");
    }

    {
        std::lock_guard<std::mutex> lock(sequenceMutex_);
        sequenceStatus_ = {};
        sequenceStatus_.state = SequenceRunState::Running;
        sequenceStatus_.message = "Sequence running";
        sequenceStatus_.stepCount = config.sequence.size();
        sequenceTouchedChannels_.fill(false);
        for (const SequencePoint& point : config.sequence) {
            for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
                sequenceTouchedChannels_[channel] = sequenceTouchedChannels_[channel] || point.targets[channel].has_value();
            }
        }
    }

    sequenceRunning_.store(true);
    sequenceWorker_ = std::thread(&ControlService::RunSequence, this, config);
}

void ControlService::StopSequence(bool disableChannels) noexcept
{
    sequenceRunning_.store(false);
    if (sequenceWorker_.joinable() && sequenceWorker_.get_id() != std::this_thread::get_id()) {
        sequenceWorker_.join();
    }

    std::array<bool, ChannelCount> touched{};
    {
        std::lock_guard<std::mutex> lock(sequenceMutex_);
        touched = sequenceTouchedChannels_;
        if (sequenceStatus_.state == SequenceRunState::Running || sequenceStatus_.state == SequenceRunState::Dwelling) {
            sequenceStatus_.state = SequenceRunState::Stopped;
            sequenceStatus_.message = "Sequence stopped";
        }
    }

    if (!disableChannels) {
        return;
    }

    std::lock_guard<std::mutex> lock(mutex_);
    for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
        if (touched[channel]) {
            pendingCommand_[channel].on = false;
            pendingCommand_[channel].enabled = false;
        }
    }
    if (transport_) {
        transport_->SendCommand(pendingCommand_);
    }
}

SequenceRunStatus ControlService::SequenceStatusSnapshot() const
{
    std::lock_guard<std::mutex> lock(sequenceMutex_);
    return sequenceStatus_;
}

void ControlService::RunSequence(SequenceRunConfig config) noexcept
{
    using clock = std::chrono::steady_clock;
    const auto period = std::chrono::duration<double>(1.0 / config.updateRateHz);
    const auto started = clock::now();
    ControlCommand command = PendingCommand();

    for (std::size_t stepIndex = 0; stepIndex < config.sequence.size() && sequenceRunning_.load(); ++stepIndex) {
        const SequencePoint& point = config.sequence[stepIndex];
        for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
            if (point.targets[channel].has_value()) {
                command[channel] = ChannelCommand{*point.targets[channel], true, true};
            }
        }

        {
            std::lock_guard<std::mutex> lock(mutex_);
            pendingCommand_ = command;
        }
        if (!ApplyCommand()) {
            SetSequenceFault("Sequence command was not acknowledged");
            sequenceRunning_.store(false);
            break;
        }

        const auto stepStarted = clock::now();
        auto nextTick = stepStarted;
        bool reached = false;
        while (sequenceRunning_.load()) {
            const TelemetrySnapshot snapshot = LatestSnapshot();
            const HealthStatus health = Health();
            const double elapsed = std::chrono::duration<double>(clock::now() - started).count();
            const double stepElapsed = std::chrono::duration<double>(clock::now() - stepStarted).count();
            const bool connectionHealthy = snapshot.connection == ConnectionState::Connected;
            const bool telemetryFresh = health.packetAgeMilliseconds <= config.stepTimeoutSeconds * 1000.0;
            if (config.requireConnected && (!connectionHealthy || !telemetryFresh)) {
                SetSequenceFault(!connectionHealthy ? "Control transport disconnected" : "Sequence telemetry watchdog expired");
                sequenceRunning_.store(false);
                break;
            }

            reached = true;
            for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
                if (!point.targets[channel].has_value()) {
                    continue;
                }
                const ChannelTelemetry& telemetry = snapshot.channels[channel];
                if (telemetry.interlocked || telemetry.status == ChannelStatus::Fault || telemetry.status == ChannelStatus::Interlocked) {
                    SetSequenceFault("Sequence channel fault or interlock");
                    sequenceRunning_.store(false);
                    reached = false;
                    break;
                }
                reached = reached && std::abs(telemetry.actual - *point.targets[channel]) <= config.targetTolerance;
            }

            {
                std::lock_guard<std::mutex> lock(sequenceMutex_);
                sequenceStatus_.state = SequenceRunState::Running;
                sequenceStatus_.message = "Ramping to sequence target";
                sequenceStatus_.stepIndex = stepIndex;
                sequenceStatus_.stepCount = config.sequence.size();
                sequenceStatus_.elapsedSeconds = elapsed;
                sequenceStatus_.dwellRemainingSeconds = point.timeSeconds;
                sequenceStatus_.targetReached = reached;
                sequenceStatus_.watchdogHealthy = true;
            }

            if (!sequenceRunning_.load() || reached) {
                break;
            }
            if (stepElapsed >= config.stepTimeoutSeconds) {
                SetSequenceFault("Sequence step timed out before reaching target");
                sequenceRunning_.store(false);
                break;
            }

            nextTick += std::chrono::duration_cast<clock::duration>(period);
            std::this_thread::sleep_until(nextTick);
        }

        if (!sequenceRunning_.load()) {
            break;
        }

        const auto dwellStarted = clock::now();
        auto dwellNextTick = dwellStarted;
        while (sequenceRunning_.load()) {
            const double dwellElapsed = std::chrono::duration<double>(clock::now() - dwellStarted).count();
            const double remaining = std::max(0.0, point.timeSeconds - dwellElapsed);
            {
                std::lock_guard<std::mutex> lock(sequenceMutex_);
                sequenceStatus_.state = SequenceRunState::Dwelling;
                sequenceStatus_.message = "Dwelling at sequence target";
                sequenceStatus_.stepIndex = stepIndex;
                sequenceStatus_.stepCount = config.sequence.size();
                sequenceStatus_.elapsedSeconds = std::chrono::duration<double>(clock::now() - started).count();
                sequenceStatus_.dwellRemainingSeconds = remaining;
                sequenceStatus_.targetReached = true;
                sequenceStatus_.watchdogHealthy = true;
            }
            if (dwellElapsed >= point.timeSeconds) {
                break;
            }
            dwellNextTick += std::chrono::duration_cast<clock::duration>(period);
            std::this_thread::sleep_until(dwellNextTick);
        }
    }

    if (sequenceRunning_.load()) {
        std::lock_guard<std::mutex> lock(sequenceMutex_);
        sequenceStatus_.state = SequenceRunState::Completed;
        sequenceStatus_.message = "Sequence completed";
        sequenceStatus_.stepIndex = config.sequence.empty() ? 0 : config.sequence.size() - 1;
        sequenceStatus_.stepCount = config.sequence.size();
        sequenceStatus_.dwellRemainingSeconds = 0.0;
        sequenceStatus_.targetReached = true;
        sequenceStatus_.watchdogHealthy = true;
    }
    sequenceRunning_.store(false);
}

void ControlService::SetSequenceFault(const std::string& message) noexcept
{
    std::lock_guard<std::mutex> lock(sequenceMutex_);
    sequenceStatus_.state = SequenceRunState::Faulted;
    sequenceStatus_.message = message;
    sequenceStatus_.watchdogHealthy = false;
}

void ControlService::ValidateSequenceRunConfig(const SequenceRunConfig& config)
{
    const double scalars[] = {config.updateRateHz, config.targetTolerance, config.stepTimeoutSeconds};
    for (double value : scalars) {
        if (!std::isfinite(value)) {
            throw std::invalid_argument("sequence timing and tolerance values must be finite");
        }
    }
    if (config.sequence.empty()) {
        throw std::invalid_argument("sequence requires at least one step");
    }
    if (config.updateRateHz <= 0.0 || config.targetTolerance < 0.0 || config.stepTimeoutSeconds <= 0.0) {
        throw std::invalid_argument("sequence timing values must be positive and tolerance must be non-negative");
    }
    for (const SequencePoint& point : config.sequence) {
        if (!std::isfinite(point.timeSeconds) || point.timeSeconds < 0.0) {
            throw std::invalid_argument("sequence dwell times must be finite and non-negative");
        }
        bool hasTarget = false;
        for (const std::optional<double>& target : point.targets) {
            if (!target.has_value()) {
                continue;
            }
            hasTarget = true;
            if (!std::isfinite(*target)) {
                throw std::invalid_argument("sequence targets must be finite");
            }
        }
        if (!hasTarget) {
            throw std::invalid_argument("each sequence step requires at least one target");
        }
    }
}

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
