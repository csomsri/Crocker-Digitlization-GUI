#pragma once

#include "Controls/Network/ZMQProtocol.hpp"

#include <cstdint>
#include <mutex>
#include <string>

#include <zmq.hpp>

class ZMQSender {
public:
    using TargetValues = Crocker::Controls::Network::ZMQProtocol::TargetValues;
    using ChannelFlags = Crocker::Controls::Network::ZMQProtocol::ChannelFlags;

    explicit ZMQSender(std::string endpoint = "tcp://*:5566");

    std::string Bind();
    std::string Bind(const std::string& endpoint);
    void SendControlPacket(const TargetValues& targets,
                           const ChannelFlags& onOffFlags,
                           const ChannelFlags& enableFlags);
    void SendControlPacket(const TargetValues& targets, std::uint64_t bitmask);

private:
    void ConfigureSocket();

    std::string endpoint_;
    mutable std::mutex socketMutex_;
    zmq::context_t context_;
    zmq::socket_t socket_;
};
