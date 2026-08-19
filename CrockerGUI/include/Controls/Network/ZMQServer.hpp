#pragma once

#include "Controls/Network/ZMQProtocol.hpp"
#include "Controls/Network/ZMQReceiver.hpp"

#include <array>
#include <atomic>
#include <cstdint>
#include <cstddef>
#include <deque>
#include <mutex>
#include <optional>
#include <string>
#include <thread>

class ZMQServer {
public:
    using Packet = Crocker::Controls::Network::ZMQProtocol::Packet;
    using TargetValues = std::array<double, Crocker::Controls::Network::ZMQProtocol::N_TRIM>;

    explicit ZMQServer(std::string endpoint = "tcp://0.0.0.0:5555");
    ~ZMQServer();

    ZMQServer(const ZMQServer&) = delete;
    ZMQServer& operator=(const ZMQServer&) = delete;

    void Start();
    void Stop();
    bool IsRunning() const;

    void SetTargets(const TargetValues& targetValues);
    void SetBitmask(std::uint64_t bitmask);
    void SetReply(const TargetValues& targetValues, std::uint64_t bitmask);
    void SetBeamRangeIndex(std::optional<int> beamRangeIndex);

    bool TryPopPacket(Packet& packet);
    std::size_t PacketQueueSize() const;
    std::string BoundEndpoint() const;

private:
    void Run();
    void PushPacket(Packet packet);
    std::uint64_t ReplyBitmask() const;

    ZMQReceiver receiver_;
    mutable std::mutex lifecycleMutex_;
    std::thread worker_;
    std::atomic_bool running_{false};

    mutable std::mutex packetMutex_;
    std::deque<Packet> packetQueue_;
    std::size_t maxPacketQueueSize_ = 50000; // Can change?

    mutable std::mutex replyMutex_;
    TargetValues latestTargets_{};
    std::uint64_t latestBitmask_ = 0;
    bool hasOperatorReply_ = false;
    std::optional<int> pendingBeamRangeIndex_;

    mutable std::mutex endpointMutex_;
    std::string boundEndpoint_;
};
