#include "Controls/Network/ZMQServer.hpp"

#include <algorithm>
#include <cerrno>
#include <iostream>
#include <utility>

namespace Protocol = Crocker::Controls::Network::ZMQProtocol;

ZMQServer::ZMQServer(std::string endpoint)
    : receiver_(std::move(endpoint))
{
    latestTargets_.fill(100.0);
}

ZMQServer::~ZMQServer()
{
    Stop();
}

void ZMQServer::Start()
{
    std::lock_guard<std::mutex> lifecycleLock(lifecycleMutex_);

    bool expected = false;
    if (!running_.compare_exchange_strong(expected, true)) {
        return;
    }

    worker_ = std::thread(&ZMQServer::Run, this);
}

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

bool ZMQServer::IsRunning() const
{
    return running_.load();
}

void ZMQServer::SetTargets(const TargetValues& targetValues)
{
    std::lock_guard<std::mutex> lock(replyMutex_);
    latestTargets_ = targetValues;
    hasOperatorReply_ = true;
}

void ZMQServer::SetBitmask(std::uint64_t bitmask)
{
    std::lock_guard<std::mutex> lock(replyMutex_);
    latestBitmask_ = bitmask;
    hasOperatorReply_ = true;
}

void ZMQServer::SetReply(const TargetValues& targetValues, std::uint64_t bitmask)
{
    std::lock_guard<std::mutex> lock(replyMutex_);
    latestTargets_ = targetValues;
    latestBitmask_ = bitmask;
    hasOperatorReply_ = true;
}

void ZMQServer::SetBeamRangeIndex(std::optional<int> beamRangeIndex)
{
    std::lock_guard<std::mutex> lock(replyMutex_);
    if (beamRangeIndex.has_value()) {
        pendingBeamRangeIndex_ = std::clamp(*beamRangeIndex, 0, 9);
    } else {
        pendingBeamRangeIndex_ = std::nullopt;
    }
}

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

std::size_t ZMQServer::PacketQueueSize() const
{
    std::lock_guard<std::mutex> lock(packetMutex_);
    return packetQueue_.size();
}

std::string ZMQServer::BoundEndpoint() const
{
    std::lock_guard<std::mutex> lock(endpointMutex_);
    return boundEndpoint_;
}

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
                {
                    std::lock_guard<std::mutex> lock(replyMutex_);
                    if (hasOperatorReply_) {
                        targets = latestTargets_;
                        bitmask = ReplyBitmask();
                    } else if (packet.channels.size() >= Protocol::N_FIELD_TRIM) {
                        std::copy_n(packet.channels.begin(), packet.channels.size(), targets.begin());
                        bitmask = packet.bitmask;
                    } else {
                        targets = latestTargets_;
                        bitmask = ReplyBitmask();
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

void ZMQServer::PushPacket(Packet packet)
{
    std::lock_guard<std::mutex> lock(packetMutex_);
    if (packetQueue_.size() >= maxPacketQueueSize_) {
        packetQueue_.pop_front();
    }

    packetQueue_.push_back(std::move(packet));
}

std::uint64_t ZMQServer::ReplyBitmask() const
{
    std::uint64_t replyBitmask = latestBitmask_;
    if (pendingBeamRangeIndex_.has_value()) {
        replyBitmask &= ~(0xFULL << 28);
        replyBitmask |= (static_cast<std::uint64_t>(*pendingBeamRangeIndex_) & 0xFULL) << 28;
    }

    return replyBitmask;
}
