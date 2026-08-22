/**
 * @file ZMQSender.cpp
 * @brief Implements the ZeroMQ PUSH sender used to publish field-controller packets.
 *
 * This file owns the socket setup, endpoint binding, and thread-safe packet sending
 * for field-controller control messages.
 * 
 * @authors Chotrawit Benko, Claudio Lopez
 * @date 2026-08-21
 */
#include "Controls/Network/ZMQSender.hpp"

#include <iostream>
#include <utility>

namespace Protocol = Crocker::Controls::Network::ZMQProtocol;

/**
 * @brief Creates a ZMQ sender for the given endpoint.
 *
 * The socket is configured as a PUSH socket and socket options are applied during
 * construction.
 *
 * @param endpoint ZMQ endpoint string, for example "tcp://*:5555".
 */
ZMQSender::ZMQSender(std::string endpoint)
    : endpoint_(std::move(endpoint)),
      context_(1),
      socket_(context_, zmq::socket_type::push)
{
    ConfigureSocket();
}

/**
 * @brief Binds the sender socket to the configured endpoint.
 *
 * This method is thread-safe with respect to other socket operations.
 *
 * @return The endpoint that was bound.
 *
 * @throws zmq::error_t if the bind operation fails.
 */
std::string ZMQSender::Bind()
{
    std::lock_guard<std::mutex> lock(socketMutex_);

    socket_.bind(endpoint_);
    std::cout << "Field Controller ZMQ sender started at " << endpoint_ << '\n';
    return endpoint_;
}

/**
 * @brief Updates the endpoint and binds the sender socket to it.
 *
 * @param endpoint New ZMQ endpoint to bind.
 * @return The endpoint that was bound.
 *
 * @throws zmq::error_t if the bind operation fails.
 */
std::string ZMQSender::Bind(const std::string& endpoint)
{
    std::lock_guard<std::mutex> lock(socketMutex_);

    endpoint_ = endpoint;
    socket_.bind(endpoint_);
    std::cout << "Field Controller ZMQ sender started at " << endpoint_ << '\n';
    return endpoint_;
}

/**
 * @brief Sends a control packet using separate on/off and enable flags.
 * 
 * @param targets Target values, one double for each trim coil.
 * @param onOffFlags Flags showing whether each trim coil is on.
 * @param enableFlags Flags showing whether each trim coil is enabled.
 * 
 * @throws zmq::error_t if the message cannot be sent.
 */
void ZMQSender::SendControlPacket(
    const TargetValues& targets,
    const ChannelFlags& onOffFlags,
    const ChannelFlags& enableFlags)
{
    SendControlPacket(targets, Protocol::BuildControlBitmask(onOffFlags, enableFlags));
}

/**
 * @brief Sends target values with a prebuilt bitmask.
 * 
 * @param targets Target values, one double for each trim coil.
 * @param bitmask 64-bit unsigned integer used as the control bitmask.
 * 
 * @throws zmq::error_t if the message cannot be sent.
 */
void ZMQSender::SendControlPacket(const TargetValues& targets, std::uint64_t bitmask)
{
    auto message = Protocol::BuildControlMessage(Protocol::BuildControlPacket(targets, bitmask));
    std::lock_guard<std::mutex> lock(socketMutex_);
    socket_.send(message, zmq::send_flags::none);
}

/**
 * @brief Configures sender socket options.
 */
void ZMQSender::ConfigureSocket()
{
    socket_.set(zmq::sockopt::linger, 0);
    socket_.set(zmq::sockopt::sndtimeo, 1500);
    socket_.set(zmq::sockopt::sndhwm, 50000);
    socket_.set(zmq::sockopt::sndbuf, 4 * 1024 * 1024);
}
