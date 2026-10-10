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

#include "Controls/ControlSystem/NLAPID.hpp"
#include "Controls/Sequencer/SequenceValidator.hpp"
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
    std::lock_guard operationLock(operationMutex_);
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
    std::lock_guard operationLock(operationMutex_);
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
    std::lock_guard operationLock(operationMutex_);
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
    auto next = commandGateway_.Command();
    next[channel].target = target;
    commandGateway_.Replace(CommandOwner::Manual, next);
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
    auto next = commandGateway_.Command();
    next[channel].on = on;
    commandGateway_.Replace(CommandOwner::Manual, next);
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
    auto next = commandGateway_.Command();
    next[channel].enabled = enabled;
    commandGateway_.Replace(CommandOwner::Manual, next);
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
    auto next = commandGateway_.Command();
    next[channel] = command;
    commandGateway_.Replace(CommandOwner::Manual, next);
}

/**
 * @brief Set command of the pending command 
 * 
 * @param command struct, containing target value, enable, on
 */
void ControlService::SetCommand(const ControlCommand& command)
{
    std::lock_guard<std::mutex> lock(mutex_);
    commandGateway_.Replace(CommandOwner::Manual, command);
}

/**
 * @brief Set scaling factor based on the scaling we have done in Config
 * 
 * @param scaling mapping of scaling to channel
 */
void ControlService::SetScaling(const ControlScaling& scaling)
{
    std::lock_guard<std::mutex> lock(mutex_);
    commandGateway_.Require(CommandOwner::Manual);
    if (transport_) transport_->SetScaling(scaling);
}

/**
 * @brief Get the latest command to be processed in a thread-safe manner
 * 
 * @return pendingCommand_ (current Command)
 */
ControlCommand ControlService::PendingCommand() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return commandGateway_.Command();
}

/**
 * @brief Apply the commands that had been set
 * 
 * @return true if succesfully send command to transport
 * @return false if there is no transport to send to
 */
bool ControlService::ApplyCommand()
{
    std::lock_guard lock(mutex_);
    commandGateway_.Require(CommandOwner::Manual);
    if (transport_) commandGateway_.CheckInterlocks(transport_->LatestSnapshot());
    return transport_ && transport_->SendCommand(commandGateway_.Command());
}

/**
 * @brief Disable all channels, not allowing transport
 * 
 * @return true if able to update and send to transport
 * @return false if unable to access transport
 */
bool ControlService::DisableAll()
{
    std::lock_guard operationLock(operationMutex_);
    StopSequence();
    StopPidTrial(false);
    return DisableAllFromWorker();
}

bool ControlService::DisableAllFromWorker() noexcept
{
    try {
        std::lock_guard lock(mutex_);
        std::array<bool, ChannelCount> channels;
        channels.fill(true);
        commandGateway_.Disable(channels);
        return transport_ && transport_->SendCommand(commandGateway_.Command());
    } catch (...) { return false; }
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
    std::lock_guard operationLock(operationMutex_);
    ValidatePidTrialConfig(config);
    {
        std::lock_guard lock(mutex_);
        commandGateway_.Require(CommandOwner::Manual);
    }
    StopPidTrial(false);

    const TelemetrySnapshot snapshot = LatestSnapshot();
    if (snapshot.connection != ConnectionState::Connected) {
        throw std::runtime_error("PID trial requires a connected control transport");
    }
    if (!snapshot.simulated && !config.dryRun && !config.allocationCalibrated) {
        // Direct trim-coil current control uses the transport's existing engineering
        // scaling; it does not need a separate field-allocation calibration.
        bool directTrimCoil = (!config.externalBeamMeasurement || config.nlaSettings.directionEachUpdate)
            && config.measurementChannel < 12;
        for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
            directTrimCoil = directTrimCoil && config.allocation[channel] == (channel == config.measurementChannel ? 1.0 : 0.0);
        }
        if (!directTrimCoil) {
            throw std::invalid_argument("unprofiled hardware PID trials require direct TC1-TC12 current control");
        }
    }
    if (!config.dryRun && !config.hardwareArmed) {
        throw std::invalid_argument("non-dry-run PID trial requires explicit hardware arming");
    }

    {
        std::lock_guard<std::mutex> lock(pidTrialMutex_);
        pidTrialStatus_ = {};
        pidTrialDryRun_ = config.dryRun;
        pidTrialStatus_.controllerKind = config.controllerKind;
        pidTrialStatus_.state = PidTrialState::Running;
        pidTrialStatus_.message = config.dryRun ? "Dry-run PID trial running" : "PID trial running";
        pidAllocatedChannels_.fill(false);
        for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
            pidAllocatedChannels_[channel] = std::abs(config.allocation[channel]) > 0.0;
        }
    }
    {
        std::lock_guard lock(mutex_);
        pidLease_ = commandGateway_.Acquire(CommandOwner::Pid);
    }
    pidTrialRunning_.store(true);
    try { pidTrialWorker_ = std::thread(&ControlService::RunPidTrial, this, config); }
    catch (...) {
        pidTrialRunning_.store(false);
        std::lock_guard lock(mutex_);
        commandGateway_.Release(CommandOwner::Pid, pidLease_);
        throw;
    }
}

void ControlService::StopPidTrial(bool disableAllocatedChannels) noexcept
{
    std::lock_guard operationLock(operationMutex_);
    pidTrialRunning_.store(false);
    if (pidTrialWorker_.joinable() && pidTrialWorker_.get_id() != std::this_thread::get_id()) {
        pidTrialWorker_.join();
    }

    std::array<bool, ChannelCount> allocated{};
    bool dryRun = true;
    {
        std::lock_guard<std::mutex> lock(pidTrialMutex_);
        allocated = pidAllocatedChannels_;
        dryRun = pidTrialDryRun_;
        if (pidTrialStatus_.state == PidTrialState::Running) {
            pidTrialStatus_.state = PidTrialState::Stopped;
            pidTrialStatus_.message = "PID trial stopped";
        }
    }
    if (!disableAllocatedChannels || dryRun) {
        return;
    }

    std::lock_guard<std::mutex> lock(mutex_);
    if (commandGateway_.Owner() == CommandOwner::Sequence) return;
    commandGateway_.Disable(allocated);
    if (transport_) transport_->SendCommand(commandGateway_.Command());
}

void ControlService::SetPidBeamMeasurement(double nanoamps, double timestampUnixSeconds, bool valid)
{
    std::lock_guard<std::mutex> lock(pidTrialMutex_);
    pidBeamNanoamps_ = nanoamps;
    pidBeamTimestamp_ = timestampUnixSeconds;
    pidBeamValid_ = valid && std::isfinite(nanoamps) && std::isfinite(timestampUnixSeconds);
}

PidTrialStatus ControlService::PidTrialStatusSnapshot() const
{
    std::lock_guard<std::mutex> lock(pidTrialMutex_);
    return pidTrialStatus_;
}

void ControlService::RunPidTrial(PidTrialConfig config) noexcept
{
    try {
        using clock = std::chrono::steady_clock;
        const auto period = std::chrono::duration<double>(1.0 / config.updateRateHz);
        const auto started = clock::now();
        auto previous = started;
        auto nextTick = started;
        NLAPID nla({config.kp, config.ki, config.kd}, config.nlaLimits, config.nlaSettings);
        std::optional<double> lastSampleTime;
        double averageSum = 0.0;
        std::size_t averageCount = 0;
        std::optional<double> averageStart, lastDecisionTime;
        bool holdIntegral = false;
        double saturationSeconds = 0.0;
        ControlCommand lastCommand = PendingCommand();

        while (pidTrialRunning_.load()) {
            const auto now = clock::now();
            const double elapsed = std::chrono::duration<double>(now - started).count();
            double dt = std::max(1.0e-6, std::chrono::duration<double>(now - previous).count());
            previous = now;
            if (!config.continuous && elapsed >= config.durationSeconds) {
                std::lock_guard<std::mutex> lock(pidTrialMutex_);
                pidTrialStatus_.state = PidTrialState::Completed;
                pidTrialStatus_.message = "PID trial completed";
                pidTrialStatus_.elapsedSeconds = elapsed;
                pidTrialRunning_.store(false);
                break;
            }

            const TelemetrySnapshot snapshot = LatestSnapshot();
            const HealthStatus health = Health();
            ChannelTelemetry measurement = snapshot.channels[config.measurementChannel];
            double sampleTimestamp = snapshot.timestampUnixSeconds;
            if (config.externalBeamMeasurement) {
                std::lock_guard<std::mutex> lock(pidTrialMutex_);
                const double epochNow = std::chrono::duration<double>(
                    std::chrono::system_clock::now().time_since_epoch()).count();
                const double age = epochNow - pidBeamTimestamp_;
                if (!pidBeamValid_ || age < 0.0 || age > config.telemetryTimeoutSeconds) {
                    throw std::runtime_error("No fresh calibrated beam measurement");
                }
                measurement.actual = pidBeamNanoamps_;
                sampleTimestamp = pidBeamTimestamp_;
            }
            const bool telemetryFresh = health.packetAgeMilliseconds <= config.telemetryTimeoutSeconds * 1000.0;
            const bool connectionHealthy = snapshot.connection == ConnectionState::Connected;
            const bool channelHealthy = !measurement.interlocked
                && measurement.status != ChannelStatus::Fault
                && measurement.status != ChannelStatus::Interlocked;
            if (!telemetryFresh || !connectionHealthy || !channelHealthy) {
                SetPidTrialFault(!telemetryFresh ? "Telemetry watchdog expired"
                    : !connectionHealthy ? "Control transport disconnected"
                    : "Measurement channel fault or interlock");
                if (!config.dryRun) DisableAllFromWorker();
                pidTrialRunning_.store(false);
                break;
            }

            // The adaptive reference consumes each fresh measurement once. Watchdogs
            // above continue to run even while a held snapshot is skipped.
            {
                const double stamp = sampleTimestamp;
                if (!std::isfinite(stamp) || (lastSampleTime && stamp < *lastSampleTime)) {
                    throw std::runtime_error("Invalid or out-of-order NLA telemetry timestamp");
                }
                if (!lastSampleTime) {
                    nla.reset(config.setpoint, measurement.actual);
                    averageStart = lastDecisionTime = stamp;
                    averageSum = measurement.actual; averageCount = 1;
                    lastSampleTime = stamp;
                    nextTick += std::chrono::duration_cast<clock::duration>(period);
                    std::this_thread::sleep_until(nextTick);
                    continue;
                }
                if (stamp == *lastSampleTime) {
                    nextTick += std::chrono::duration_cast<clock::duration>(period);
                    std::this_thread::sleep_until(nextTick);
                    continue;
                }
                dt = stamp - *lastSampleTime;
                lastSampleTime = stamp;
            }
            double error = config.setpoint - measurement.actual;
            if (!config.nlaSettings.directionEachUpdate && std::abs(error) > config.maxAbsoluteError) {
                SetPidTrialFault("Absolute error abort limit exceeded");
                if (!config.dryRun) DisableAllFromWorker();
                pidTrialRunning_.store(false);
                break;
            }
            if (!config.nlaSettings.directionEachUpdate && measurement.actual - config.setpoint > config.maxOvershoot) {
                SetPidTrialFault("Overshoot abort limit exceeded");
                if (!config.dryRun) DisableAllFromWorker();
                pidTrialRunning_.store(false);
                break;
            }
            if (config.feedbackAverageSeconds > 0.0) {
                averageSum += measurement.actual;
                ++averageCount;
                if (sampleTimestamp - *averageStart < config.feedbackAverageSeconds) {
                    nextTick += std::chrono::duration_cast<clock::duration>(period);
                    std::this_thread::sleep_until(nextTick);
                    continue;
                }
                measurement.actual = averageSum / averageCount;
                error = config.setpoint - measurement.actual;
                dt = sampleTimestamp - *lastDecisionTime;
                averageStart = lastDecisionTime = sampleTimestamp;
                averageSum = 0.0; averageCount = 0;
            }
            const auto calculationStarted = clock::now();
            const NLAPIDResult nlaResult = nla.update(config.setpoint, measurement.actual, dt, holdIntegral);
            const double output = nlaResult.output;
            const double calculationMicroseconds =
                std::chrono::duration<double, std::micro>(clock::now() - calculationStarted).count();
            if (!std::isfinite(output)) throw std::runtime_error("Nonfinite PID output");
            if (!config.nlaSettings.directionEachUpdate && std::abs(output) > config.maxControlOutput) {
                SetPidTrialFault("Control-output abort limit exceeded");
                if (!config.dryRun) DisableAllFromWorker();
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
                const double base = lastCommand[channel].target;
                const double requested = base + config.allocation[channel] * output;
                const double bounded = std::clamp(requested, config.minimumCommand[channel], config.maximumCommand[channel]);
                saturated = saturated || bounded != requested;
                const double maximumDelta = config.maximumSlewPerSecond[channel] * dt;
                // Zero delegates physical ramping to LabVIEW; absolute bounds remain active.
                const double slewed = (config.nlaSettings.directionEachUpdate || config.maximumSlewPerSecond[channel] == 0.0) ? bounded : std::clamp(
                    bounded,
                    lastCommand[channel].target - maximumDelta,
                    lastCommand[channel].target + maximumDelta);
                rateLimited = rateLimited || slewed != bounded;
                if (slewed < config.minimumCommand[channel] || slewed > config.maximumCommand[channel]) {
                    throw std::runtime_error("Current target lies outside configured PID command limits");
                }
                command[channel] = ChannelCommand{slewed, true, true};
            }

            // External actuator constraints are separate from the NLA engine limits.
            // Age its integral on the next update when the actuator cannot follow.
            holdIntegral = !config.nlaSettings.directionEachUpdate && (saturated || rateLimited);
            saturationSeconds = saturated ? saturationSeconds + dt : 0.0;
            if (!config.nlaSettings.directionEachUpdate && saturationSeconds > config.maxSaturationSeconds) {
                SetPidTrialFault("Command saturation persisted beyond abort limit");
                if (!config.dryRun) DisableAllFromWorker();
                pidTrialRunning_.store(false);
                break;
            }

            const double target = command[config.measurementChannel].target;
            const double commandDelta = target - lastCommand[config.measurementChannel].target;
            bool sent = true;
            if (!config.dryRun) {
                std::lock_guard lock(mutex_);
                commandGateway_.Replace(CommandOwner::Pid, command);
                if (transport_) commandGateway_.CheckInterlocks(transport_->LatestSnapshot());
                sent = transport_ && transport_->SendCommand(commandGateway_.Command());
            }
            if (!sent) {
                SetPidTrialFault("Control command was not acknowledged");
                if (!config.dryRun) DisableAllFromWorker();
                pidTrialRunning_.store(false);
                break;
            }

            // Advance virtual targets in dry run too, without sending any command.
            lastCommand = command;
            {
                std::lock_guard<std::mutex> lock(pidTrialMutex_);
                pidTrialStatus_.nla = nlaResult;
                pidTrialStatus_.commandTarget = target;
                pidTrialStatus_.commandDelta = commandDelta;
                pidTrialStatus_.controlRate = output / std::min(dt, std::max(1.0e-4, config.nlaSettings.maxControlDt));
                pidTrialStatus_.calculationMicroseconds = calculationMicroseconds;
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
    } catch (const std::exception& error) {
        SetPidTrialFault(error.what());
        if (!config.dryRun) DisableAllFromWorker();
        pidTrialRunning_.store(false);
    } catch (...) {
        SetPidTrialFault("Unknown PID worker failure");
        if (!config.dryRun) DisableAllFromWorker();
        pidTrialRunning_.store(false);
    }
    {
        std::lock_guard lock(mutex_);
        commandGateway_.Release(CommandOwner::Pid, pidLease_);
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
    if (!std::isfinite(config.feedbackAverageSeconds) || config.feedbackAverageSeconds < 0.0)
        throw std::invalid_argument("Feedback averaging time must be finite and nonnegative");
    if (config.updateRateHz <= 0.0 || config.durationSeconds <= 0.0
        || config.telemetryTimeoutSeconds <= 0.0 || config.maxAbsoluteError <= 0.0
        || config.maxOvershoot <= 0.0 || config.maxControlOutput <= 0.0
        || config.maxSaturationSeconds <= 0.0) {
        throw std::invalid_argument("PID timing values must be positive");
    }
    {
        // Validate before starting the noexcept worker and limit NLA to the
        // direct-channel mapping used by the Python reference page.
        NLAPID check({config.kp, config.ki, config.kd}, config.nlaLimits, config.nlaSettings);
        for (ChannelId channel = 0; channel < ChannelCount; ++channel) {
            if (config.allocation[channel] != (channel == config.measurementChannel ? 1.0 : 0.0)) {
                throw std::invalid_argument("NLA requires direct single-channel allocation");
            }
        }
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
            || config.maximumSlewPerSecond[channel] < 0.0) {
            throw std::invalid_argument("allocated channels require ordered limits and nonnegative slew rates (zero uses external ramping)");
        }
    }
    if (!hasAllocation) {
        throw std::invalid_argument("PID trial requires at least one allocated channel");
    }
}

// ============================================================= END OF PID SECTION ============================================================= 

void ControlService::StartSequence(const SequenceRunConfig& config)
{
    const auto definition = SequenceValidator::FromConfig(config);
    std::lock_guard operationLock(operationMutex_);
    std::uint64_t lease;
    {
        std::lock_guard lock(mutex_);
        lease = commandGateway_.Acquire(CommandOwner::Sequence);
    }
    std::array<bool, ChannelCount> touched{};
    for (const auto& step : definition.steps)
        for (ChannelId ch = 0; ch < ChannelCount; ++ch)
            touched[ch] = touched[ch] || step.targets[ch].has_value();
    try {
        if (LatestSnapshot().connection != ConnectionState::Connected)
            throw std::runtime_error("Connect to the machine or start the simulator before running a sequence.");
        sequenceRunner_.Start(definition,
            [this] { return SequenceInput{LatestSnapshot(), Health()}; },
            [this, limits = definition.limits](const auto& targets) {
                std::lock_guard lock(mutex_);
                if (!transport_) return false;
                commandGateway_.MergeSequence(targets, transport_->LatestSnapshot(), limits);
                commandGateway_.CheckInterlocks(transport_->LatestSnapshot());
                return transport_->SendCommand(commandGateway_.Command());
            },
            [this, lease, touched](StopPolicy policy) {
                std::lock_guard lock(mutex_);
                bool sent = true;
                try {
                    if (policy == StopPolicy::DisableChannels) {
                        commandGateway_.Disable(touched);
                        sent = transport_ && transport_->SendCommand(commandGateway_.Command());
                    }
                } catch (...) {
                    commandGateway_.Release(CommandOwner::Sequence, lease);
                    throw;
                }
                commandGateway_.Release(CommandOwner::Sequence, lease);
                return sent;
            });
    } catch (...) {
        std::lock_guard lock(mutex_);
        commandGateway_.Release(CommandOwner::Sequence, lease);
        throw;
    }
}

void ControlService::StopSequence(bool disableChannels) noexcept
{
    std::lock_guard operationLock(operationMutex_);
    sequenceRunner_.Stop(disableChannels);
}

SequenceRunStatus ControlService::SequenceStatusSnapshot() const
{
    return sequenceRunner_.StatusSnapshot();
}

std::vector<SequenceEvent> ControlService::SequenceEventsSnapshot() const
{
    return sequenceRunner_.EventsSnapshot();
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
