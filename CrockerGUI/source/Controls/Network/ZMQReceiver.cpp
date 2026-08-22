/**
 * @file ZMQReceiver.cpp
 * 
 * @brief Implementation of receiver functions for the ZMQ REP server.
 * 
 * This file owns the REP socket context, endpoint binding, packet receiving,
 * and reply sending used by ZMQServer.
 * 
 * @authors Chotrawit Benko, Claudio Lopez
 * @date 2026-08-21 
 */

#include "Controls/Network/ZMQReceiver.hpp"

#include <algorithm>
#include <cstring>
#include <iostream>
#include <utility>

namespace Protocol = Crocker::Controls::Network::ZMQProtocol;

/**
 * @brief Constructs a ZMQReceiver with an endpoint, context, and REP socket.
 * 
 * @param endpoint ZMQ endpoint to bind, for example "tcp://0.0.0.0:5555".
 */
ZMQReceiver::ZMQReceiver(std::string endpoint)
    : endpoint_(std::move(endpoint)),
      context_(1),
      socket_(context_, zmq::socket_type::rep)
{
    ConfigureSocket();
}

/**
 * @brief Binds to the endpoint given in the constructor.
 * 
 * Falls back to a random local port if the preferred endpoint is busy.
 * 
 * @throws zmq::error_t if both the preferred and fallback binds fail.
 *
 * @return The endpoint that was successfully bound.
 */
std::string ZMQReceiver::Bind()
{
    endpoint_ = BindWithFallBack(endpoint_);
    return endpoint_;
}

/**
 * @brief Binds to a given endpoint.
 * 
 * Falls back to a random local port if the preferred endpoint is busy.
 * 
 * @param preferredEndpoint Preferred endpoint if different from the constructor endpoint.
 * 
 * @throws zmq::error_t if both the preferred and fallback binds fail.
 *
 * @return The endpoint that was successfully bound.
 */
std::string ZMQReceiver::Bind(const std::string& preferredEndpoint)
{
    endpoint_ = BindWithFallBack(preferredEndpoint);
    return endpoint_;
}

/**
 * @brief Checks the socket for a raw ZMQ message.
 * 
 * @throws zmq::error_t if recv fails.
 * 
 * @return The received message, or an empty message if no value was received.
 */
zmq::message_t ZMQReceiver::ReceiveMessage()
{
    zmq::message_t message;
    const auto result = socket_.recv(message, zmq::recv_flags::none);
    if (!result.has_value()) {
        return {};
    }

    return message;
}

/**
 * @brief Receives and decodes one packet.
 * 
 * @throws zmq::error_t if recv fails.
 * 
 * @return The decoded packet, or an empty packet if receive/decode did not succeed.
 */
Protocol::Packet ZMQReceiver::ReceivePacket()
{
    Protocol::Packet packet;
    TryReceivePacket(packet);
    return packet;
}


/**
 * @brief Calls socket.recv and attempts to decode a packet from the socket.
 * 
 * @param packet Output packet containing values with machine state.
 * 
 * @throws zmq::error_t if recv fails.
 * 
 * @return true if a ZMQ message was received.
 * @return false if no message was received before the timeout.
 */
bool ZMQReceiver::TryReceivePacket(Protocol::Packet& packet)
{
    packet = {};
    zmq::message_t message;
    const auto result = socket_.recv(message, zmq::recv_flags::none);
    if (!result.has_value()) {
        return false;
    }

    if (!Protocol::IsValidFrameSize(message.size())) {
        return true;
    }

    packet = Protocol::SliceBestEffort(Protocol::UnpackDoubles(message));
    return true;
}

/**
 * @brief Sends a full 14-channel reply.
 * 
 * Calls the overloaded SendReply function with the full trim channel count.
 * 
 * @param targetValues Array of doubles containing target values of trim coils.
 * @param bitmask Unsigned 64-bit value containing on/off, enable, and beam-range bits.
 * 
 * @throws zmq::error_t if the reply cannot be sent.
 */
void ZMQReceiver::SendReply(const std::array<double, Protocol::N_TRIM>& targetValues, std::uint64_t bitmask)
{
    SendReply(targetValues, Protocol::N_TRIM, bitmask);
}


/**
 * @brief Sends a reply with a clamped channel count.
 * 
 * This function takes in target values, clamps the channel count to the protocol
 * limits, and sends those values plus the bitmask.
 * 
 * @param targetValues Array of doubles containing trim coil values.
 * @param channelCount Number of channel values to send.
 * @param bitmask Unsigned 64-bit value containing on/off, enable, and beam-range bits.
 * 
 * @throws zmq::error_t if the reply cannot be sent.
 */
void ZMQReceiver::SendReply(
    const std::array<double, Protocol::N_TRIM>& targetValues,
    std::size_t channelCount,
    std::uint64_t bitmask)
{
    const std::size_t safeCount = std::clamp(channelCount, Protocol::N_FIELD_TRIM, Protocol::N_TRIM);
    std::vector<double> replyValues(safeCount + 1);
    std::copy_n(targetValues.begin(), safeCount, replyValues.begin());
    replyValues.back() = static_cast<double>(bitmask);

    zmq::message_t reply(replyValues.size() * sizeof(double));
    std::memcpy(reply.data(), replyValues.data(), reply.size());
    socket_.send(reply, zmq::send_flags::none);
}


/**
 * @brief Tries to bind to the preferred endpoint, then falls back to an available port.
 * 
 * The preferred endpoint is usually tcp://0.0.0.0:5555. If that endpoint is busy,
 * this binds to a random localhost port instead.
 * 
 * @param preferredEndpoint Endpoint to try first.
 * 
 * @throws zmq::error_t if both bind attempts fail.
 * 
 * @return The endpoint that was successfully bound.
 */
std::string ZMQReceiver::BindWithFallBack(const std::string& preferredEndpoint)
{   
    try {
        socket_.bind(preferredEndpoint);
        const std::string boundEndpoint = socket_.get(zmq::sockopt::last_endpoint);
        std::cout << "REP server on " << boundEndpoint << '\n';
        return boundEndpoint;
    } catch (const zmq::error_t& error) {
        socket_.bind("tcp://127.0.0.1:*");
        const std::string fallbackEndpoint = socket_.get(zmq::sockopt::last_endpoint);

        std::cerr << preferredEndpoint << " busy; using " << fallbackEndpoint
                  << " [" << error.what() << "]\n";
        return fallbackEndpoint;
    }
}


/**
 * @brief Applies socket options used by the receiver.
 */
void ZMQReceiver::ConfigureSocket()
{
    socket_.set(zmq::sockopt::linger, 0);
    socket_.set(zmq::sockopt::rcvtimeo, 1500);
    socket_.set(zmq::sockopt::sndtimeo, 1500);
    socket_.set(zmq::sockopt::tcp_keepalive, 1);
    socket_.set(zmq::sockopt::tcp_keepalive_idle, 30);
    socket_.set(zmq::sockopt::tcp_keepalive_cnt, 5);
    socket_.set(zmq::sockopt::tcp_keepalive_intvl, 30);
    socket_.set(zmq::sockopt::rcvhwm, 50000);
    socket_.set(zmq::sockopt::sndhwm, 50000);
    socket_.set(zmq::sockopt::rcvbuf, 4 * 1024 * 1024);
    socket_.set(zmq::sockopt::sndbuf, 4 * 1024 * 1024);
}
