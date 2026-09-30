#include "Controls/Sequencer/Sequencer.hpp"
#include "Controls/Sequencer/SequenceValidator.hpp"
#include "Controls/Service/CommandGateway.hpp"
#include <limits>
#include <stdexcept>
#include <iostream>

using namespace crocker::controls;
void check(bool condition, const char* message) { if (!condition) throw std::runtime_error(message); }
template<class F> void rejects(F action) {
    bool rejected = false;
    try { action(); } catch (const std::exception&) { rejected = true; }
    check(rejected, "Expected rejection");
}
auto at(double seconds) { return SequenceClock::time_point{} + std::chrono::duration_cast<SequenceClock::duration>(SequenceDuration(seconds)); }
SequenceDefinition definition() {
    SequenceRunConfig config;
    SequencePoint point;
    point.targets[0] = 100;
    point.targets[1] = 80;
    point.timeSeconds = 5;
    config.sequence.push_back(point);
    return SequenceValidator::FromConfig(config);
}
SequenceInput feedback(double first = 100, double second = 80) {
    SequenceInput input;
    input.telemetry.connection = ConnectionState::Connected;
    input.health.receivedPackets = 1;
    for (auto& ch : input.telemetry.channels) { ch.status = ChannelStatus::Ready; ch.on = ch.enabled = true; }
    input.telemetry.channels[0].actual = first;
    input.telemetry.channels[1].actual = second;
    return input;
}
void dispatch(Sequencer& engine, const SequenceDefinition& plan) {
    engine.Start(plan, at(0));
    check(engine.Tick(feedback(0, 0), at(0)).targets.has_value(), "Initial targets missing");
    engine.CommandStaged(true, at(0));
}
int main() {
    try {
        rejects([] { SequenceValidator::Validate({}); });
        auto plan = definition();
        auto invalid = plan;
        invalid.steps[0].targets[0] = std::numeric_limits<double>::quiet_NaN();
        rejects([&] { SequenceValidator::Validate(invalid); });
        invalid = plan; invalid.telemetryTimeout = SequenceDuration(0);
        rejects([&] { SequenceValidator::Validate(invalid); });
        invalid = plan; invalid.steps[0].settle = invalid.steps[0].reachTimeout;
        rejects([&] { SequenceValidator::Validate(invalid); });
        invalid = plan; invalid.limits.maximum[0] = 50;
        rejects([&] { SequenceValidator::Validate(invalid); });

        Sequencer engine;
        dispatch(engine, plan);
        engine.Tick(feedback(100, 0), at(8));
        check(engine.Status().state == SequenceRunState::Running, "Must wait for every channel");
        engine.Tick(feedback(), at(9));
        check(engine.Status().state == SequenceRunState::Settling, "Arrival must settle first");
        engine.Tick(feedback(), at(9.25));
        check(engine.Status().state == SequenceRunState::Dwelling, "Hold should start after arrival");
        engine.Tick(feedback(), at(14));
        check(engine.Status().state == SequenceRunState::Dwelling, "Ramp time must not count toward hold");
        engine.Tick(feedback(), at(14.3));
        check(engine.Status().state == SequenceRunState::Completed, "Expected completion");
        check(!engine.Events().empty(), "Transitions must be recorded");

        dispatch(engine, plan);
        engine.Tick(feedback(), at(1)); engine.Tick(feedback(), at(1.25));
        engine.Tick(feedback(90), at(4));
        check(engine.Status().dwellRemainingSeconds == 5, "Departure must reset hold");
        engine.Tick(feedback(), at(5)); engine.Tick(feedback(), at(5.25));
        engine.Tick(feedback(), at(9));
        check(engine.Status().state == SequenceRunState::Dwelling, "Hold restarted too early");
        auto stale = feedback(); stale.health.packetAgeMilliseconds = 1001;
        engine.Tick(stale, at(9.5));
        check(engine.Status().fault->code == "stale_feedback", "Watchdog must run during hold");
        engine.Tick(feedback(), at(10));
        check(engine.Status().state == SequenceRunState::Faulted, "Fault must be sticky");

        dispatch(engine, plan);
        auto fault = feedback(); fault.telemetry.channels[0].interlocked = true;
        engine.Tick(fault, at(1));
        check(engine.Status().fault->channel == 0, "Fault must identify channel");
        check(engine.Status().state == SequenceRunState::Faulted, "Fault must not be overwritten");

        dispatch(engine, plan);
        engine.Tick(feedback(0, 0), at(30));
        check(engine.Status().fault->code == "arrival_timeout", "Arrival timeout missing");
        dispatch(engine, plan);
        engine.Tick(feedback(), at(1)); engine.Tick(feedback(), at(1.25));
        auto disconnected = feedback(); disconnected.telemetry.connection = ConnectionState::Disconnected;
        engine.Tick(disconnected, at(2));
        check(engine.Status().fault->code == "disconnected", "Disconnect during hold missing");

        auto second = plan.steps[0]; second.targets.fill(std::nullopt); second.targets[1] = 60;
        second.dwell = SequenceDuration(0); plan.steps[0].dwell = SequenceDuration(0);
        plan.steps.push_back(second);
        dispatch(engine, plan);
        engine.Tick(feedback(), at(1)); engine.Tick(feedback(), at(1.25));
        check(engine.Status().stepIndex == 1, "Next step missing");
        check(engine.Tick(feedback(), at(1.3)).targets->at(0) == std::nullopt, "Sparse command lost");
        engine.CommandStaged(true, at(1.3));
        fault = feedback(100, 60); fault.telemetry.channels[0].interlocked = true;
        engine.Tick(fault, at(2));
        check(engine.Status().state == SequenceRunState::Faulted, "Earlier channels must stay monitored");

        CommandGateway gateway;
        ControlCommand manual{}; manual[3] = {25, true, true};
        gateway.Replace(CommandOwner::Manual, manual);
        auto lease = gateway.Acquire(CommandOwner::Sequence);
        rejects([&] { gateway.Replace(CommandOwner::Manual, manual); });
        rejects([&] { gateway.Acquire(CommandOwner::Pid); });
        gateway.MergeSequence(plan.steps[0].targets, feedback().telemetry);
        check(gateway.Command()[3].target == 25, "Sparse merge changed another channel");
        gateway.Release(CommandOwner::Sequence, lease + 1);
        rejects([&] { gateway.Require(CommandOwner::Manual); });
        gateway.Release(CommandOwner::Sequence, lease);
        gateway.Require(CommandOwner::Manual);
        auto interlocked = feedback().telemetry; interlocked.channels[3].interlocked = true;
        rejects([&] { gateway.CheckInterlocks(interlocked); });
        std::cout << "Sequencer timing, validation, faults and ownership passed\n";
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
