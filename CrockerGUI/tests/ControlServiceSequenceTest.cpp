#include "Controls/Service/ControlService.hpp"

#include <cassert>
#include <chrono>
#include <stdexcept>
#include <thread>

using namespace crocker::controls;

namespace {
SequenceRunConfig SingleChannelSequence()
{
    SequenceRunConfig config;
    config.updateRateHz = 40.0;
    config.targetTolerance = 1.0;
    config.stepTimeoutSeconds = 3.0;

    SequencePoint first;
    first.timeSeconds = 0.05;
    first.targets[0] = 60.0;
    config.sequence.push_back(first);

    SequencePoint second;
    second.timeSeconds = 0.05;
    second.targets[0] = 20.0;
    config.sequence.push_back(second);
    return config;
}
}

int main()
{
    {
        ControlService service;
        service.StartSimulator(120.0);
        service.StartSequence(SingleChannelSequence());

        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(6);
        SequenceRunStatus status;
        do {
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
            status = service.SequenceStatusSnapshot();
        } while (status.state != SequenceRunState::Completed && std::chrono::steady_clock::now() < deadline);

        assert(status.state == SequenceRunState::Completed);
        assert(status.stepCount == 2);
        assert(status.targetReached);
        assert(status.watchdogHealthy);
        const double actual = service.LatestSnapshot().channels[0].actual;
        assert(actual > 15.0);
        assert(actual < 65.0);
        service.StopSequence();
    }

    {
        ControlService service;
        service.StartSimulator(60.0);
        bool rejected = false;
        try {
            SequenceRunConfig config;
            service.StartSequence(config);
        } catch (const std::invalid_argument&) {
            rejected = true;
        }
        assert(rejected);
        service.StopSequence();
    }
}
