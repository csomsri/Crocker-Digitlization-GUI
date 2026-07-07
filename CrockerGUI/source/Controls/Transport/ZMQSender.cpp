#include "Controls/Transport/ZMQSender.hpp"

#include <iostream>
#include <utility>

namespace Protocol = Crocker::Controls::Transport::ZMQProtocol;

ZMQSender::ZMQSender(std::string endpoint)
    : endpoint_(std::move(endpoint)),
      context_(1),
      socket_(context_, zmq::socket_type::push)
{
    ConfigureSocket();
}

std::string ZMQSender::Bind()
{
    socket_.bind(endpoint_);
    std::cout << "Field Controller ZMQ sender started at " << endpoint_ << '\n';
    return endpoint_;
}

std::string ZMQSender::Bind(const std::string& endpoint)
{
    endpoint_ = endpoint;
    return Bind();
}

void ZMQSender::SendControlPacket(
    const TargetValues& targets,
    const ChannelFlags& onOffFlags,
    const ChannelFlags& enableFlags)
{
    SendControlPacket(targets, Protocol::BuildControlBitmask(onOffFlags, enableFlags));
}

void ZMQSender::SendControlPacket(const TargetValues& targets, std::uint64_t bitmask)
{
    auto message = Protocol::BuildControlMessage(Protocol::BuildControlPacket(targets, bitmask));
    socket_.send(message, zmq::send_flags::none);
}

void ZMQSender::ConfigureSocket()
{
    socket_.set(zmq::sockopt::linger, 0);
    socket_.set(zmq::sockopt::sndtimeo, 1500);
    socket_.set(zmq::sockopt::sndhwm, 50000);
    socket_.set(zmq::sockopt::sndbuf, 4 * 1024 * 1024);
}
