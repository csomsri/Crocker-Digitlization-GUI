#pragma once

#include "Controls/Network/ZMQProtocol.hpp"

#include <array>
#include <cstdint>
#include <string>

#include <zmq.hpp>

/**
 * @brief Low-level ZMQ REP receiver used by ZMQServer.
 *
 * This class owns the REP socket, receives raw LabVIEW/simulator packets,
 * decodes them through ZMQProtocol, and sends reply packets back.
 */
class ZMQReceiver {
public:
    /**
     * @brief Creates a receiver for the given endpoint.
     *
     * @param endpoint ZMQ endpoint to bind.
     */
    explicit ZMQReceiver(std::string endpoint = "tcp://0.0.0.0:5555");

    /**
     * @brief Binds to the configured endpoint.
     *
     * @return Endpoint that was successfully bound.
     */
    std::string Bind();

    /**
     * @brief Binds to a new preferred endpoint.
     *
     * @param preferredEndpoint Endpoint to try first.
     * @return Endpoint that was successfully bound.
     */
    std::string Bind(const std::string& preferredEndpoint);

    /**
     * @brief Receives one raw ZMQ message.
     *
     * @return Received message, or an empty message on timeout.
     */
    zmq::message_t ReceiveMessage();

    /**
     * @brief Receives and decodes one packet.
     *
     * @return Decoded packet, or an empty packet if no valid packet was received.
     */
    Crocker::Controls::Network::ZMQProtocol::Packet ReceivePacket();

    /**
     * @brief Attempts to receive and decode one packet.
     *
     * @param packet Output packet.
     * @return true if a ZMQ message was received.
     * @return false if no message was received before timeout.
     */
    bool TryReceivePacket(Crocker::Controls::Network::ZMQProtocol::Packet& packet);

    /**
     * @brief Sends a full trim-channel reply.
     *
     * @param targetValues Target values to send.
     * @param bitmask Reply bitmask.
     */
    void SendReply(const std::array<double, Crocker::Controls::Network::ZMQProtocol::N_TRIM>& targetValues,
                   std::uint64_t bitmask);

    /**
     * @brief Sends a reply with a specific channel count.
     *
     * @param targetValues Target values to send.
     * @param channelCount Number of target values to include.
     * @param bitmask Reply bitmask.
     */
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
