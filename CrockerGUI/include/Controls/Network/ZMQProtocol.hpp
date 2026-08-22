#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include <zmq.hpp>

/**
 * @brief Protocol constants and helpers for ZMQ messages.
 *
 * The network protocol sends arrays of doubles. These helpers define the expected
 * sizes, decode incoming packets, build outgoing packets, and pack/unpack ZMQ messages.
 */
namespace Crocker::Controls::Network::ZMQProtocol {

// Protocol sizes for LabVIEW and GUI ZMQ packets.
inline constexpr std::size_t N_TRIM = 14;
inline constexpr std::size_t N_FIELD_TRIM = 12;
inline constexpr std::size_t N_SRC_EX_12 = 12;
inline constexpr std::size_t N_SRC_EX_18 = 18;
inline constexpr std::size_t N_TRANS = 10;
inline constexpr std::size_t N_VAC_BM_7 = 7;
inline constexpr std::size_t REPLY_DOUBLES = N_TRIM + 1;
inline constexpr std::size_t CONTROL_DOUBLES = 1 + N_TRIM + 1;
inline constexpr std::size_t MIN_REQUEST_DOUBLES = 1 + N_TRIM + 1;
inline constexpr std::size_t MIN_FIELD_REQUEST_DOUBLES = 1 + N_FIELD_TRIM + 1;
inline constexpr double EPOCH_OFFSET = 2082844800.0;

// Normalized timestamp from LabVIEW, Unix time, or legacy packet formats.
struct Timestamp {
    double unixSeconds = 0.0;
    std::string mode;
};

// Decoded machine-state packet received from LabVIEW or the simulator.
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

// Check if a ZMQ frame has a valid byte size for this protocol.
bool IsValidFrameSize(std::size_t byteCount);

// Infer whether a packet contains 12 or 14 trim channels.
std::size_t InferChannelCount(std::size_t doubleCount);

// Copy raw ZMQ bytes into doubles.
std::vector<double> UnpackDoubles(const zmq::message_t& message);

// Decode a vector of doubles into the best packet layout available.
Packet SliceBestEffort(const std::vector<double>& doubles);

// Convert LabVIEW, Unix, or legacy timestamps into Unix seconds.
Timestamp NormalizeTimestamp(double rawTimestamp);

// Decode the beam range index stored in the reply bitmask.
int DecodeBeamIndexFromBitmask(std::uint64_t bitmask);

// Build the on/off and enable bits from channel flag arrays.
std::uint64_t BuildControlBitmask(const ChannelFlags& onOffFlags, const ChannelFlags& enableFlags);

// Build reply doubles from target values and a bitmask.
ReplyTargets BuildReplyTargets(const TargetValues& targetValues, std::uint64_t bitmask);

// Pack reply doubles into a ZMQ message.
zmq::message_t BuildReplyMessage(const ReplyTargets& replyTargets);

// Build a timestamped control packet from target values and a bitmask.
ControlPacket BuildControlPacket(const TargetValues& targetValues, std::uint64_t bitmask);

// Pack a control packet into a ZMQ message.
zmq::message_t BuildControlMessage(const ControlPacket& controlPacket);

}
