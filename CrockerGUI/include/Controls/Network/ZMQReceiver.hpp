#pragma once

#include "Controls/Network/ZMQProtocol.hpp"

#include <array>
#include <cstdint>
#include <string>

#include <zmq.hpp>

class ZMQReceiver {
public:
    explicit ZMQReceiver(std::string endpoint = "tcp://0.0.0.0:5555");

    std::string Bind();
    std::string Bind(const std::string& preferredEndpoint);
    zmq::message_t ReceiveMessage();
    Crocker::Controls::Network::ZMQProtocol::Packet ReceivePacket();
    bool TryReceivePacket(Crocker::Controls::Network::ZMQProtocol::Packet& packet);
    void SendReply(const std::array<double, Crocker::Controls::Network::ZMQProtocol::N_TRIM>& targetValues,
                   std::uint64_t bitmask);
    void SendReply(const std::array<double, Crocker::Controls::Network::ZMQProtocol::N_TRIM>& targetValues,
                   std::size_t channelCount,
                   std::uint64_t bitmask);

private:
    std::string BindWithFallBack(const std::string& preferredEndpoint);
    void ConfigureSocket();

    std::string endpoint_;
    zmq::context_t context_;
    zmq::socket_t socket_;
};
