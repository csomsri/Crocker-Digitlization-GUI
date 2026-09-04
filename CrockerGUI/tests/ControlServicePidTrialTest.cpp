#include "Controls/Service/ControlService.hpp"

#include <cassert>
#include <chrono>
#include <thread>

using namespace crocker::controls;

namespace {
PidTrialConfig TrialConfig(bool dryRun)
{
    PidTrialConfig config;
    config.measurementChannel = 0;
    config.setpoint = 50.0;
    config.kp = 1.0;
    config.ki = 0.05;
    config.kd = 0.0;
    config.updateRateHz = 40.0;
    config.durationSeconds = 0.5;
    config.telemetryTimeoutSeconds = 0.25;
    config.allocation[0] = 1.0;
    config.minimumCommand[0] = 0.0;
    config.maximumCommand[0] = 100.0;
    config.maximumSlewPerSecond[0] = 500.0;
    config.hardwareArmed = !dryRun;
    config.dryRun = dryRun;
    return config;
}
}

int main()
{
    {
        ControlService service;
        service.StartSimulator(100.0);
        service.StartPidTrial(TrialConfig(false));
        std::this_thread::sleep_for(std::chrono::milliseconds(750));
        const PidTrialStatus status = service.PidTrialStatusSnapshot();
        assert(status.state == PidTrialState::Completed);
        assert(status.iterations > 0);
        assert(status.watchdogHealthy);
        assert(service.LatestSnapshot().channels[0].actual > 0.0);
        service.StopPidTrial();
    }

    {
        ControlService service;
        service.StartSimulator(100.0);
        service.StartPidTrial(TrialConfig(true));
        std::this_thread::sleep_for(std::chrono::milliseconds(750));
        const PidTrialStatus status = service.PidTrialStatusSnapshot();
        assert(status.state == PidTrialState::Completed);
        assert(service.LatestSnapshot().channels[0].actual == 0.0);
        service.StopPidTrial();
    }

    {
        ControlService service;
        service.StartSimulator(10.0);
        PidTrialConfig config = TrialConfig(false);
        config.telemetryTimeoutSeconds = 1.0e-9;
        service.StartPidTrial(config);
        std::this_thread::sleep_for(std::chrono::milliseconds(150));
        const PidTrialStatus status = service.PidTrialStatusSnapshot();
        assert(status.state == PidTrialState::Faulted);
        assert(!status.watchdogHealthy);
        const ControlCommand command = service.PendingCommand();
        for (const ChannelCommand& channel : command) {
            assert(!channel.on);
            assert(!channel.enabled);
        }
        service.StopPidTrial();
    }

    {
        ControlService service;
        service.StartSimulator(100.0);
        PidTrialConfig config = TrialConfig(false);
        config.maxAbsoluteError = 10.0;
        service.StartPidTrial(config);
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        const PidTrialStatus status = service.PidTrialStatusSnapshot();
        assert(status.state == PidTrialState::Faulted);
        assert(status.message == "Absolute error abort limit exceeded");
        const ControlCommand command = service.PendingCommand();
        for (const ChannelCommand& channel : command) {
            assert(!channel.on);
            assert(!channel.enabled);
        }
        service.StopPidTrial();
    }
}
