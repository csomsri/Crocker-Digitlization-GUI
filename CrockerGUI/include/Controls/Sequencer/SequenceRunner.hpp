#pragma once
#include "Controls/Sequencer/Sequencer.hpp"
#include <condition_variable>
#include <functional>
#include <mutex>
#include <thread>

namespace crocker::controls {
class SequenceRunner {
public:
    using Read = std::function<SequenceInput()>;
    using Send = std::function<bool(const std::array<std::optional<double>, ChannelCount>&)>;
    using Finish = std::function<bool(StopPolicy)>;
    ~SequenceRunner();
    // Start and Stop are serialized by ControlService's operation mutex.
    void Start(const SequenceDefinition& definition, Read read, Send send, Finish finish);
    void Stop(bool disableChannels = false);
    SequenceRunStatus StatusSnapshot() const;
    std::vector<SequenceEvent> EventsSnapshot() const;
private:
    std::jthread worker_;
    mutable std::mutex mutex_;
    std::condition_variable_any wake_;
    SequenceRunStatus status_;
    std::vector<SequenceEvent> events_;
    bool disableOnStop_ = false;
};
}
