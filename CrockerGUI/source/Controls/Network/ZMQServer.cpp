/**
 * @file ZMQServer.cpp
 * @brief Implements the ZeroMQ reply server used for GUI/LabVIEW control exchange.
 *
 * This file owns the server lifecycle, receiver binding, worker thread loop,
 * thread-safe reply state, received-packet queueing, and reply bitmask assembly.
 * 
 * @authors Chotrawit Benko, Claudio Lopez
 * @date 2026-08-21
 */
#include "Controls/Network/ZMQServer.hpp"

#include <algorithm>
#include <cerrno>
#include <iostream>
#include <utility>

namespace Protocol = Crocker::Controls::Network::ZMQProtocol;

/**
 * @brief Creates a REP server for the given endpoint.
 *
 * @param endpoint ZMQ endpoint to bind, for example "tcp://0.0.0.0:5555".
 */
ZMQServer::ZMQServer(std::string endpoint)
    : receiver_(std::move(endpoint))
{
}

ZMQServer::~ZMQServer()
{
    Stop();
}

/**
 * @brief Starts the server in a thread-safe manner.
 *
 * Creates the worker thread that runs the ZMQ receive/reply loop.
 */
void ZMQServer::Start()
{
    std::lock_guard<std::mutex> lifecycleLock(lifecycleMutex_);

    bool expected = false;
    if (!running_.compare_exchange_strong(expected, true)) {
        return;
    }

    worker_ = std::thread(&ZMQServer::Run, this);
}


/**
 * @brief Stops the server in a thread-safe manner.
 *
 * Clears the running flag and joins the worker thread.
 */
void ZMQServer::Stop()
{
    std::lock_guard<std::mutex> lifecycleLock(lifecycleMutex_);

    const bool wasRunning = running_.exchange(false);
    if (wasRunning && worker_.joinable()) {
        worker_.join();
    } else if (worker_.joinable()) {
        worker_.join();
    }
}

/** 
 * @brief Checks if the server is running.
 * 
 * @return true if the atomic running flag is set.
*/
bool ZMQServer::IsRunning() const
{
    return running_.load();
}


/**
 * @brief Sets target values for the next operator reply.
 *
 * Sets latestTargets_ and marks that an operator reply is ready.
 *
 * @param targetValues Target values to send back to LabVIEW.
 */
void ZMQServer::SetTargets(const TargetValues& targetValues)
{
    std::lock_guard<std::mutex> lock(replyMutex_);
    latestTargets_ = targetValues;
    hasOperatorReply_ = true;
}

/**
 * @brief Sets the bitmask for the next operator reply in a thread-safe manner.
 *
 * @param bitmask 64-bit value containing on/off, enable, and beam-range bits.
 */
void ZMQServer::SetBitmask(std::uint64_t bitmask)
{
    std::lock_guard<std::mutex> lock(replyMutex_);
    latestBitmask_ = bitmask;
    hasOperatorReply_ = true;
}

/**
 * @brief Sets target values and bitmask for the next operator reply.
 * 
 * @param targetValues Array of doubles for each trim coil.
 * @param bitmask 64-bit value containing on/off, enable, and beam-range bits.
 * 
 */
void ZMQServer::SetReply(const TargetValues& targetValues, std::uint64_t bitmask)
{
    std::lock_guard<std::mutex> lock(replyMutex_);
    latestTargets_ = targetValues;
    latestBitmask_ = bitmask;
    hasOperatorReply_ = true;
}

/**
 * @brief Sets the beam range index in a thread-safe manner.
 *
 * If a value is present, this clamps it to the valid range 0 through 9.
 * 
 * @param beamRangeIndex Optional integer representing the beam range index.
 *
 */
void ZMQServer::SetBeamRangeIndex(std::optional<int> beamRangeIndex)
{
    std::lock_guard<std::mutex> lock(replyMutex_);
    if (beamRangeIndex.has_value()) {
        pendingBeamRangeIndex_ = std::clamp(*beamRangeIndex, 0, 9);
    } else {
        pendingBeamRangeIndex_ = std::nullopt;
    }
}


/**
 * @brief Pops the front packet from the packet queue in a thread-safe manner.
 * 
 * @param packet Output packet filled with the oldest queued packet.
 * 
 * @return false if the queue is empty.
 * @return true if a packet was popped successfully.
 * 
 */
bool ZMQServer::TryPopPacket(Packet& packet)
{
    std::lock_guard<std::mutex> lock(packetMutex_);
    if (packetQueue_.empty()) {
        return false;
    }

    packet = std::move(packetQueue_.front());
    packetQueue_.pop_front();
    return true;
}

/**
 * @brief Checks the size of the packet queue in a thread-safe manner.
 * 
 * @return Number of queued packets.
 */
std::size_t ZMQServer::PacketQueueSize() const
{
    std::lock_guard<std::mutex> lock(packetMutex_);
    return packetQueue_.size();
}

/**
 * @brief Returns the bound server endpoint in a thread-safe manner.
 * 
 * @return Endpoint location string.
 */
std::string ZMQServer::BoundEndpoint() const
{
    std::lock_guard<std::mutex> lock(endpointMutex_);
    return boundEndpoint_;
}

/**
 * @brief Main loop of the ZMQ REP server.
 *
 * The loop receives a packet, chooses the safest available reply, sends the
 * reply, and queues received packets for other code to read.
 * 
 * @throws zmq::error_t if the socket cannot bind, receive, or reply.
 */
void ZMQServer::Run()
{
    try {
        {
            std::lock_guard<std::mutex> lock(endpointMutex_);
            if (boundEndpoint_.empty()) {
                boundEndpoint_ = receiver_.Bind();
            }
        }

        while (running_.load()) {
            try {
                Packet packet;
                if (!receiver_.TryReceivePacket(packet)) {
                    continue;
                }

                TargetValues targets{};
                std::uint64_t bitmask = 0;
                // Protect shared reply state while choosing the reply.
                {
                    std::lock_guard<std::mutex> lock(replyMutex_);
                    
                    if (hasOperatorReply_) {
                        targets = latestTargets_;
                        bitmask = ReplyBitmask();
                    } else if (packet.channels.size() >= Protocol::N_FIELD_TRIM) {
                        const std::size_t channelCount = std::min(packet.channels.size(), targets.size());
                        std::copy_n(packet.channels.begin(), channelCount, targets.begin());
                        bitmask = packet.bitmask;
                    } else {
                        targets = {};
                        bitmask = 0;
                    }
                }

                const std::size_t replyChannelCount =
                    packet.channels.size() >= Protocol::N_TRIM ? Protocol::N_TRIM : Protocol::N_FIELD_TRIM;

                receiver_.SendReply(targets, replyChannelCount, bitmask);

                if (!packet.channels.empty()) {
                    PushPacket(std::move(packet));
                }

            } catch (const zmq::error_t& error) {
                if (error.num() == EAGAIN) {
                    continue;
                }

                if (running_.load()) {
                    std::cerr << "ZMQ server error: " << error.what()
                              << " errno=" << error.num() << '\n';
                }
            }
        }
    } catch (const zmq::error_t& error) {
        std::cerr << "ZMQ server stopped after error: " << error.what()
                  << " errno=" << error.num() << '\n';
    }

    running_.store(false);
}

/**
 * @brief Pushes packets to the packet queue in a thread-safe manner.
 *
 * If the queue is full, this removes the oldest packet before adding the new one.
 *
 * @param packet Packet to add to the queue.
 */
void ZMQServer::PushPacket(Packet packet)
{
    std::lock_guard<std::mutex> lock(packetMutex_);
    if (packetQueue_.size() >= maxPacketQueueSize_) {
        packetQueue_.pop_front();
    }

    packetQueue_.push_back(std::move(packet));
}

/**
 * @brief Creates the bitmask used in replies.
 *
 * Starts with the latest bitmask and overlays the pending beam range index if one exists.
 * 
 * @return Set of bits for the reply.
 */
std::uint64_t ZMQServer::ReplyBitmask() const
{
    std::uint64_t replyBitmask = latestBitmask_;
    if (pendingBeamRangeIndex_.has_value()) {
        replyBitmask &= ~(0xFULL << 28);
        replyBitmask |= (static_cast<std::uint64_t>(*pendingBeamRangeIndex_) & 0xFULL) << 28;
    }

    return replyBitmask;
}
