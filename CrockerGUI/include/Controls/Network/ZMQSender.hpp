#pragma once

#include "Controls/Network/ZMQProtocol.hpp"

#include <cstdint>
#include <mutex>
#include <string>

#include <zmq.hpp>

/**
 * @brief Low-level ZMQ PUSH sender for field-controller control packets.
 *
 * This class owns the PUSH socket and sends timestamped control packets built
 * by ZMQProtocol.
 */
class ZMQSender {
public:
    using TargetValues = Crocker::Controls::Network::ZMQProtocol::TargetValues;
    using ChannelFlags = Crocker::Controls::Network::ZMQProtocol::ChannelFlags;

    /**
     * @brief Creates a sender for the given endpoint.
     *
     * @param endpoint ZMQ endpoint to bind.
     */
    explicit ZMQSender(std::string endpoint = "tcp://*:5566");

    /**
     * @brief Binds to the configured endpoint.
     *
     * @return Endpoint that was bound.
     */
    std::string Bind();

    /**
     * @brief Updates the endpoint and binds to it.
     *
     * @param endpoint New endpoint to bind.
     * @return Endpoint that was bound.
     */
    std::string Bind(const std::string& endpoint);

    /**
     * @brief Sends targets using separate on/off and enable flags.
     *
     * @param targets Target values to send.
     * @param onOffFlags On/off flags for each channel.
     * @param enableFlags Enable flags for each channel.
     */
    void SendControlPacket(const TargetValues& targets,
                           const ChannelFlags& onOffFlags,
                           const ChannelFlags& enableFlags);

    /**
     * @brief Sends targets using a prebuilt bitmask.
     *
     * @param targets Target values to send.
     * @param bitmask Control bitmask.
     */
    void SendControlPacket(const TargetValues& targets, std::uint64_t bitmask);

private:
    void ConfigureSocket();

    std::string endpoint_;
    mutable std::mutex socketMutex_;
    zmq::context_t context_;
    zmq::socket_t socket_;
};
