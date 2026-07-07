#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include <zmq.hpp>

namespace Crocker::Controls::Transport::ZMQProtocol {

// Protocol Sizes
inline constexpr std::size_t N_TRIM = 14;
inline constexpr std::size_t N_SRC_EX_12 = 12;
inline constexpr std::size_t N_SRC_EX_18 = 18;
inline constexpr std::size_t N_TRANS = 10;
inline constexpr std::size_t N_VAC_BM_7 = 7;
inline constexpr std::size_t REPLY_DOUBLES = N_TRIM + 1;
inline constexpr std::size_t CONTROL_DOUBLES = 1 + N_TRIM + 1;
inline constexpr std::size_t MIN_REQUEST_DOUBLES = 1 + N_TRIM + 1;
inline constexpr double EPOCH_OFFSET = 2082844800.0;

// Get Time Stamp
struct Timestamp {
    double unixSeconds = 0.0;
    std::string mode;
};

// Message Receive
struct Packet {
    double timestamp = 0.0;
    std::vector<double> channels;
    std::uint64_t bitmask = 0;
    std::vector<double> extraction;
    std::vector<double> extractionAngles;
    std::vector<double> source;
    std::vector<double> transport;
    std::vector<double> vacuum;
    std::optional<double> rfPowerKv;
    std::optional<double> beamCurrent;
    std::optional<int> beamRangeIndex;
    std::optional<double> latencyMs;
    std::string timestampMode;
};

using ReplyTargets = std::array<double, REPLY_DOUBLES>;
using ControlPacket = std::array<double, CONTROL_DOUBLES>;
using TargetValues = std::array<double, N_TRIM>;
using ChannelFlags = std::array<bool, N_TRIM>;

bool IsValidFrameSize(std::size_t byteCount);
std::vector<double> UnpackDoubles(const zmq::message_t& message);
Packet SliceBestEffort(const std::vector<double>& doubles);
Timestamp NormalizeTimestamp(double rawTimestamp);
int DecodeBeamIndexFromBitmask(std::uint64_t bitmask);
std::uint64_t BuildControlBitmask(const ChannelFlags& onOffFlags, const ChannelFlags& enableFlags);
ReplyTargets BuildReplyTargets(const TargetValues& targetValues, std::uint64_t bitmask);
zmq::message_t BuildReplyMessage(const ReplyTargets& replyTargets);
ControlPacket BuildControlPacket(const TargetValues& targetValues, std::uint64_t bitmask);
zmq::message_t BuildControlMessage(const ControlPacket& controlPacket);

}
