#include "Controls/Network/ZMQProtocol.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <stdexcept>

namespace Crocker::Controls::Network::ZMQProtocol {
namespace {

std::vector<double> Slice(const std::vector<double>& values, std::size_t first, std::size_t last)
{
    first = std::min(first, values.size());
    last = std::min(last, values.size());
    if (last < first) {
        last = first;
    }

    return {values.begin() + static_cast<std::ptrdiff_t>(first),
            values.begin() + static_cast<std::ptrdiff_t>(last)};
}

void TryTransportVacuumLayout(
    const std::vector<double>& middle,
    std::size_t start,
    bool transportFirst,
    std::vector<double>& transport,
    std::vector<double>& vacuumBeam,
    std::optional<int>& vacuumIndex,
    std::size_t& outOffset)
{
    std::size_t offset = start;
    std::optional<std::size_t> transStart;
    std::optional<std::size_t> vacStart;
    std::optional<int> vacIdx;

    auto left = [&]() { return middle.size() - offset; };

    if (transportFirst) {
        if (left() >= N_TRANS) {
            transStart = offset;
            offset += N_TRANS;

            if (left() == N_VAC_BM_7) {
                vacStart = offset;
                offset += N_VAC_BM_7;
            } else if (left() == N_VAC_BM_7 + 1) {
                vacStart = offset;
                offset += N_VAC_BM_7;
                vacIdx = static_cast<int>(std::llround(middle[offset]));
                ++offset;
            }
        }
    } else if (left() >= N_VAC_BM_7) {
        vacStart = offset;
        offset += N_VAC_BM_7;

        if (left() >= N_TRANS + 1) {
            vacIdx = static_cast<int>(std::llround(middle[offset]));
            ++offset;
        }

        if (left() == N_TRANS) {
            transStart = offset;
            offset += N_TRANS;
        }
    }

    if (transStart.has_value()) {
        transport = Slice(middle, *transStart, *transStart + N_TRANS);
    }

    if (vacStart.has_value()) {
        vacuumBeam = Slice(middle, *vacStart, *vacStart + N_VAC_BM_7);
    }

    vacuumIndex = vacIdx;
    outOffset = offset;
}

} // namespace

bool IsValidFrameSize(std::size_t byteCount)
{
    return byteCount % sizeof(double) == 0 && byteCount >= MIN_REQUEST_DOUBLES * sizeof(double);
}

std::vector<double> UnpackDoubles(const zmq::message_t& message)
{
    if (message.size() % sizeof(double) != 0) {
        throw std::invalid_argument("ZMQ frame size is not a multiple of double size");
    }

    std::vector<double> values(message.size() / sizeof(double));
    std::memcpy(values.data(), message.data(), message.size());
    return values;
}

Packet SliceBestEffort(const std::vector<double>& doubles)
{
    Packet packet;
    if (doubles.size() < MIN_REQUEST_DOUBLES) {
        return packet;
    }

    std::size_t offset = 0;
    packet.timestamp = doubles[offset++];
    packet.channels = Slice(doubles, offset, offset + N_TRIM);
    offset += N_TRIM;

    const auto middleEnd = doubles.size() - 1;
    const std::vector<double> middle = Slice(doubles, offset, middleEnd);
    packet.bitmask = static_cast<std::uint64_t>(std::llround(doubles.back()));

    std::size_t middleOffset = 0;
    if (middle.size() >= N_SRC_EX_18) {
        packet.extraction = Slice(middle, middleOffset, middleOffset + 6);
        packet.extractionAngles = Slice(middle, middleOffset + 6, middleOffset + 12);
        packet.source = Slice(middle, middleOffset + 12, middleOffset + N_SRC_EX_18);
        middleOffset += N_SRC_EX_18;
    } else if (middle.size() >= N_SRC_EX_12) {
        packet.extraction = Slice(middle, middleOffset, middleOffset + 6);
        packet.source = Slice(middle, middleOffset + 6, middleOffset + N_SRC_EX_12);
        middleOffset += N_SRC_EX_12;
    }

    std::vector<double> transFirstTransport;
    std::vector<double> transFirstVacuumBeam;
    std::optional<int> transFirstIndex;
    std::size_t transFirstOffset = middleOffset;
    TryTransportVacuumLayout(
        middle,
        middleOffset,
        true,
        transFirstTransport,
        transFirstVacuumBeam,
        transFirstIndex,
        transFirstOffset);

    if (!transFirstTransport.empty() && !transFirstVacuumBeam.empty() && transFirstOffset == middle.size()) {
        packet.transport = std::move(transFirstTransport);
        packet.beamRangeIndex = transFirstIndex;
        const auto vacuumBeam = std::move(transFirstVacuumBeam);
        packet.vacuum = Slice(vacuumBeam, 0, 5);
        if (vacuumBeam.size() >= 6) {
            packet.rfPowerKv = vacuumBeam[5];
        }
        if (vacuumBeam.size() >= 7) {
            packet.beamCurrent = vacuumBeam[6];
        }
    } else {
        std::vector<double> vacFirstTransport;
        std::vector<double> vacFirstVacuumBeam;
        std::optional<int> vacFirstIndex;
        std::size_t vacFirstOffset = middleOffset;
        TryTransportVacuumLayout(
            middle,
            middleOffset,
            false,
            vacFirstTransport,
            vacFirstVacuumBeam,
            vacFirstIndex,
            vacFirstOffset);

        if (!vacFirstTransport.empty() && !vacFirstVacuumBeam.empty() && vacFirstOffset == middle.size()) {
            packet.transport = std::move(vacFirstTransport);
            packet.beamRangeIndex = vacFirstIndex;
            const auto vacuumBeam = std::move(vacFirstVacuumBeam);
            packet.vacuum = Slice(vacuumBeam, 0, 5);
            if (vacuumBeam.size() >= 6) {
                packet.rfPowerKv = vacuumBeam[5];
            }
            if (vacuumBeam.size() >= 7) {
                packet.beamCurrent = vacuumBeam[6];
            }
        } else {
            if (middle.size() - middleOffset >= N_TRANS) {
                packet.transport = Slice(middle, middleOffset, middleOffset + N_TRANS);
                middleOffset += N_TRANS;
            }
            if (middle.size() - middleOffset >= N_VAC_BM_7) {
                const auto vacuumBeam = Slice(middle, middleOffset, middleOffset + N_VAC_BM_7);
                packet.vacuum = Slice(vacuumBeam, 0, 5);
                packet.rfPowerKv = vacuumBeam[5];
                packet.beamCurrent = vacuumBeam[6];
            }
        }
    }

    if (!packet.beamRangeIndex.has_value()) {
        const int decodedIndex = DecodeBeamIndexFromBitmask(packet.bitmask);
        if (decodedIndex >= 0) {
            packet.beamRangeIndex = decodedIndex;
        }
    }

    const Timestamp timestamp = NormalizeTimestamp(packet.timestamp);
    packet.timestampMode = timestamp.mode;

    const auto now = std::chrono::system_clock::now();
    const auto nowSeconds = std::chrono::duration<double>(now.time_since_epoch()).count();
    packet.latencyMs = (nowSeconds - timestamp.unixSeconds) * 1000.0;

    return packet;
}

Timestamp NormalizeTimestamp(double rawTimestamp)
{
    double timestamp = rawTimestamp;
    std::string mode = "s";

    if (timestamp > 1e14) {
        timestamp /= 1e9;
        mode = "ns";
    } else if (timestamp > 1e12) {
        timestamp /= 1e6;
        mode = "us";
    } else if (timestamp > 1e10) {
        timestamp /= 1e3;
        mode = "ms";
    }

    if (timestamp > 3.0e9) {
        return {timestamp - EPOCH_OFFSET, "labview_" + mode};
    }

    if (timestamp > 1.0e9) {
        return {timestamp, "unix_" + mode};
    }

    return {timestamp, "small/legacy"};
}

int DecodeBeamIndexFromBitmask(std::uint64_t bitmask)
{
    const std::uint64_t bits = (bitmask >> 28) & 0x3FFULL;
    for (int i = 9; i >= 0; --i) {
        if (((bits >> i) & 1ULL) != 0) {
            return i;
        }
    }

    return -1;
}

ReplyTargets BuildReplyTargets(const std::array<double, N_TRIM>& targetValues, std::uint64_t bitmask)
{
    ReplyTargets reply{};
    std::copy(targetValues.begin(), targetValues.end(), reply.begin());
    reply.back() = static_cast<double>(bitmask);
    return reply;
}

std::uint64_t BuildControlBitmask(const ChannelFlags& onOffFlags, const ChannelFlags& enableFlags)
{
    std::uint64_t bitmask = 0;
    for (std::size_t i = 0; i < N_TRIM; ++i) {
        if (onOffFlags[i]) {
            bitmask |= 1ULL << i;
        }
        if (enableFlags[i]) {
            bitmask |= 1ULL << (N_TRIM + i);
        }
    }

    return bitmask;
}

zmq::message_t BuildReplyMessage(const ReplyTargets& replyTargets)
{
    zmq::message_t message(replyTargets.size() * sizeof(double));
    std::memcpy(message.data(), replyTargets.data(), message.size());
    return message;
}

ControlPacket BuildControlPacket(const TargetValues& targetValues, std::uint64_t bitmask)
{
    ControlPacket controlPacket{};
    const auto now = std::chrono::system_clock::now();
    const auto unixSeconds = std::chrono::duration<double>(now.time_since_epoch()).count();

    controlPacket[0] = unixSeconds + EPOCH_OFFSET;
    std::copy(targetValues.begin(), targetValues.end(), controlPacket.begin() + 1);
    controlPacket.back() = static_cast<double>(bitmask);
    return controlPacket;
}

zmq::message_t BuildControlMessage(const ControlPacket& controlPacket)
{
    zmq::message_t message(controlPacket.size() * sizeof(double));
    std::memcpy(message.data(), controlPacket.data(), message.size());
    return message;
}

} // namespace Crocker::Controls::Network::ZMQProtocol
