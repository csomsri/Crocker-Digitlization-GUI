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

/**
 * @brief Threaded ZMQ REP server for GUI/LabVIEW control exchange.
 *
 * This class owns the server lifecycle, keeps the latest reply state, receives
 * machine-state packets, and queues packets for the transport layer.
 */
class ZMQServer {
public:
    using Packet = Crocker::Controls::Network::ZMQProtocol::Packet;
    using TargetValues = std::array<double, Crocker::Controls::Network::ZMQProtocol::N_TRIM>;

    /**
     * @brief Creates a server for the given endpoint.
     *
     * @param endpoint ZMQ endpoint to bind.
     */
    explicit ZMQServer(std::string endpoint = "tcp://0.0.0.0:5555");

    /**
     * @brief Stops the server before destruction.
     */
    ~ZMQServer();

    ZMQServer(const ZMQServer&) = delete;
    ZMQServer& operator=(const ZMQServer&) = delete;

    /**
     * @brief Starts the server worker thread.
     */
    void Start();

    /**
     * @brief Stops the server worker thread.
     */
    void Stop();

    /**
     * @brief Checks whether the server is running.
     *
     * @return true if the server is running.
     */
    bool IsRunning() const;

    /**
     * @brief Sets target values for the next reply.
     *
     * @param targetValues Target values to send.
     */
    void SetTargets(const TargetValues& targetValues);

    /**
     * @brief Sets the bitmask for the next reply.
     *
     * @param bitmask Reply bitmask.
     */
    void SetBitmask(std::uint64_t bitmask);

    /**
     * @brief Sets target values and bitmask for the next reply.
     *
     * @param targetValues Target values to send.
     * @param bitmask Reply bitmask.
     */
    void SetReply(const TargetValues& targetValues, std::uint64_t bitmask);

    /**
     * @brief Sets a pending beam range index for reply bitmasks.
     *
     * @param beamRangeIndex Optional beam range index.
     */
    void SetBeamRangeIndex(std::optional<int> beamRangeIndex);

    /**
     * @brief Pops one received packet from the queue.
     *
     * @param packet Output packet.
     * @return true if a packet was popped.
     */
    bool TryPopPacket(Packet& packet);

    /**
     * @brief Gets the current received-packet queue size.
     *
     * @return Number of queued packets.
     */
    std::size_t PacketQueueSize() const;

    /**
     * @brief Gets the endpoint that the server actually bound.
     *
     * @return Bound endpoint string.
     */
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
