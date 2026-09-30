#include "Controls/Sequencer/SequenceRunner.hpp"
#include "Controls/Sequencer/SequenceValidator.hpp"
#include <exception>

namespace crocker::controls {
SequenceRunner::~SequenceRunner() { Stop(); }
void SequenceRunner::Stop(bool disableChannels) {
    {
        std::lock_guard lock(mutex_);
        disableOnStop_ = disableOnStop_ || disableChannels;
    }
    if (worker_.joinable()) {
        worker_.request_stop();
        wake_.notify_all();
        worker_.join();
    }
}
SequenceRunStatus SequenceRunner::StatusSnapshot() const { std::lock_guard lock(mutex_); return status_; }
std::vector<SequenceEvent> SequenceRunner::EventsSnapshot() const { std::lock_guard lock(mutex_); return events_; }
void SequenceRunner::Start(const SequenceDefinition& definition, Read read, Send send, Finish finish) {
    SequenceValidator::Validate(definition);
    Stop();
    Sequencer engine;
    engine.Start(definition, SequenceClock::now());
    {
        std::lock_guard lock(mutex_);
        disableOnStop_ = false;
        status_ = engine.Status();
        events_ = engine.Events();
    }
    worker_ = std::jthread([this, definition, read = std::move(read), send = std::move(send),
                           finish = std::move(finish), engine = std::move(engine)](std::stop_token token) mutable {
        const auto publish = [&] {
            std::lock_guard lock(mutex_);
            status_ = engine.Status();
            events_ = engine.Events();
        };
        try {
            while (!token.stop_requested() && SequenceActive(engine.Status().state)) {
                const auto action = engine.Tick(read(), SequenceClock::now());
                if (action.targets && !token.stop_requested())
                    engine.CommandStaged(send(*action.targets), SequenceClock::now());
                if (SequenceActive(engine.Status().state)) publish();
                if (!SequenceActive(engine.Status().state)) break;
                std::unique_lock lock(mutex_);
                wake_.wait_for(lock, token, SequenceDuration(1.0 / definition.updateRateHz), [] { return false; });
            }
            if (token.stop_requested()) engine.Stop();
        } catch (const std::exception& error) {
            engine.Fail("worker_failure", std::string("Sequence failed: ") + error.what());
        } catch (...) {
            engine.Fail("worker_failure", "Unexpected sequence failure.");
        }
        auto policy = StopPolicy::KeepTargets;
        if (engine.Status().state == SequenceRunState::Faulted) policy = definition.faultPolicy;
        if (engine.Status().state == SequenceRunState::Stopped) {
            std::lock_guard lock(mutex_);
            policy = disableOnStop_ ? StopPolicy::DisableChannels : definition.stopPolicy;
        }
        try {
            if (!finish(policy)) engine.Fail("disable_failed", "Could not send the disable command. Check machine state.");
        } catch (...) {
            engine.Fail("cleanup_failed", "Could not finish sequence cleanup. Check machine state.");
        }
        publish();
        {
            std::lock_guard lock(mutex_);
            if (status_.state == SequenceRunState::Stopped)
                status_.message = policy == StopPolicy::DisableChannels
                    ? "Stopped. Disable command sent for sequence channels; verify readbacks."
                    : "Stopped. Last targets remain applied; currents may still be moving.";
            else if (status_.state == SequenceRunState::Faulted && status_.fault &&
                     status_.fault->code != "disable_failed" && status_.fault->code != "cleanup_failed")
                status_.message += policy == StopPolicy::DisableChannels
                    ? " Disable command sent; verify readbacks." : " Last targets remain applied.";
        }
    });
}
}
