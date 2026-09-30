#include "Controls/Sequencer/SequenceRunner.hpp"
#include "Controls/Sequencer/SequenceValidator.hpp"
#include <atomic>
#include <iostream>
#include <stdexcept>
using namespace crocker::controls;
int main() {
    SequenceRunConfig config;
    SequencePoint point; point.targets[0] = 100; point.timeSeconds = 5;
    config.sequence.push_back(point);
    config.updateRateHz = 1; // Cancellation must interrupt the one-second wait.
    config.disableChannelsOnStop = true;
    SequenceRunner runner;
    std::atomic_int sent{0}, finished{0};
    std::atomic_bool disabled{false};
    const auto read = [] {
        SequenceInput input;
        input.telemetry.connection = ConnectionState::Connected;
        input.telemetry.channels[0].status = ChannelStatus::Ready;
        input.health.receivedPackets = 1;
        return input;
    };
    auto finish = [&](StopPolicy policy) { disabled = policy == StopPolicy::DisableChannels; ++finished; return true; };
    runner.Start(SequenceValidator::FromConfig(config), read, [&](const auto&) { ++sent; return true; }, finish);
    const auto deadline = SequenceClock::now() + std::chrono::seconds(2);
    while (sent == 0 && SequenceClock::now() < deadline) std::this_thread::yield();
    const auto start = SequenceClock::now();
    runner.Stop();
    if (sent != 1 || finished != 1 || !disabled ||
        runner.StatusSnapshot().state != SequenceRunState::Stopped ||
        SequenceClock::now() - start > std::chrono::milliseconds(500)) return 1;
    runner.Stop();
    if (finished != 1) return 2;
    config.disableChannelsOnFault = true;
    runner.Start(SequenceValidator::FromConfig(config), read,
        [](const auto&) -> bool { throw std::runtime_error("Injected transport failure"); }, finish);
    while (SequenceActive(runner.StatusSnapshot().state) && SequenceClock::now() < deadline) std::this_thread::yield();
    runner.Stop();
    if (runner.StatusSnapshot().state != SequenceRunState::Faulted || !disabled || finished != 2) return 3;
    std::cout << "Runner cancellation and exception cleanup passed\n";
}
