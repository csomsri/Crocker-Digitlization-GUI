#include "Controls/Transport/ZMQReceiver.hpp"

#include <iostream>
#include <utility>

namespace Protocol = Crocker::Controls::Transport::ZMQProtocol;

ZMQReceiver::ZMQReceiver(std::string endpoint)
    : endpoint_(std::move(endpoint)),
      context_(1),
      socket_(context_, zmq::socket_type::rep)
{
    ConfigureSocket();
}

std::string ZMQReceiver::Bind()
{
    endpoint_ = BindWithFallBack(endpoint_);
    return endpoint_;
}

std::string ZMQReceiver::Bind(const std::string& preferredEndpoint)
{
    endpoint_ = BindWithFallBack(preferredEndpoint);
    return endpoint_;
}

zmq::message_t ZMQReceiver::ReceiveMessage()
{
    zmq::message_t message;
    const auto result = socket_.recv(message, zmq::recv_flags::none);
    if (!result.has_value()) {
        return {};
    }

    return message;
}

Protocol::Packet ZMQReceiver::ReceivePacket()
{
    const zmq::message_t message = ReceiveMessage();
    if (!Protocol::IsValidFrameSize(message.size())) {
        return {};
    }

    return Protocol::SliceBestEffort(Protocol::UnpackDoubles(message));
}

void ZMQReceiver::SendReply(const std::array<double, Protocol::N_TRIM>& targetValues, std::uint64_t bitmask)
{
    auto reply = Protocol::BuildReplyMessage(Protocol::BuildReplyTargets(targetValues, bitmask));
    socket_.send(reply, zmq::send_flags::none);
}

std::string ZMQReceiver::BindWithFallBack(const std::string& preferredEndpoint)
{
    try {
        socket_.bind(preferredEndpoint);
        std::cout << "REP server on " << preferredEndpoint << '\n';
        return preferredEndpoint;
    } catch (const zmq::error_t& error) {
        socket_.bind("tcp://127.0.0.1:*");
        const std::string fallbackEndpoint = socket_.get(zmq::sockopt::last_endpoint);

        std::cerr << preferredEndpoint << " busy; using " << fallbackEndpoint
                  << " [" << error.what() << "]\n";
        return fallbackEndpoint;
    }
}

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
