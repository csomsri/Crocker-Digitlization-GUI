#include "Bindings/Bindings.hpp"

#include <pybind11/stl.h>

#include "Controls/Transport/ZMQProtocol.hpp"
#include "Controls/Transport/ZMQSender.hpp"
#include "Controls/Transport/ZMQServer.hpp"

#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>

namespace py = pybind11;
namespace Protocol = Crocker::Controls::Transport::ZMQProtocol;

namespace {

ZMQSender::TargetValues ToTargetValues(const py::sequence& values)
{
    if (values.size() != Protocol::N_TRIM) {
        throw std::invalid_argument("expected 14 target values");
    }

    ZMQSender::TargetValues targets{};
    for (std::size_t i = 0; i < Protocol::N_TRIM; ++i) {
        targets[i] = py::cast<double>(values[i]);
    }

    return targets;
}

ZMQSender::ChannelFlags ToChannelFlags(const py::sequence& values, const char* name)
{
    if (values.size() != Protocol::N_TRIM) {
        throw std::invalid_argument(std::string("expected 14 ") + name + " flags");
    }

    ZMQSender::ChannelFlags flags{};
    for (std::size_t i = 0; i < Protocol::N_TRIM; ++i) {
        flags[i] = py::cast<bool>(values[i]);
    }

    return flags;
}

py::object OptionalDoubleToPython(const std::optional<double>& value)
{
    if (!value.has_value()) {
        return py::none();
    }

    return py::float_(*value);
}

py::object OptionalIntToPython(const std::optional<int>& value)
{
    if (!value.has_value()) {
        return py::none();
    }

    return py::int_(*value);
}

py::dict PacketToDict(const Protocol::Packet& packet)
{
    py::dict out;
    out["timestamp"] = packet.timestamp;
    out["channels"] = packet.channels;
    out["bitmask"] = packet.bitmask;
    out["extraction"] = packet.extraction;
    out["extraction_angles"] = packet.extractionAngles;
    out["source"] = packet.source;
    out["transport"] = packet.transport;
    out["vacuum"] = packet.vacuum;
    out["rf_power_kv"] = OptionalDoubleToPython(packet.rfPowerKv);
    out["beam_current"] = OptionalDoubleToPython(packet.beamCurrent);
    out["beam_range_idx"] = OptionalIntToPython(packet.beamRangeIndex);
    out["latency"] = OptionalDoubleToPython(packet.latencyMs);
    out["ts_mode"] = packet.timestampMode;
    return out;
}

} // namespace

void BindTransport(py::module_& module)
{
    py::class_<ZMQServer>(module, "ZMQServer")
        .def(py::init<std::string>(), py::arg("endpoint") = "tcp://0.0.0.0:5555")
        .def("Start", &ZMQServer::Start)
        .def("Stop", &ZMQServer::Stop)
        .def("IsRunning", &ZMQServer::IsRunning)
        .def("BoundEndpoint", &ZMQServer::BoundEndpoint)
        .def("PacketQueueSize", &ZMQServer::PacketQueueSize)
        .def(
            "SetTargets",
            [](ZMQServer& server, const py::sequence& targets) {
                server.SetTargets(ToTargetValues(targets));
            },
            py::arg("targets"))
        .def("SetBitmask", &ZMQServer::SetBitmask, py::arg("bitmask"))
        .def(
            "SetBeamRangeIndex",
            [](ZMQServer& server, py::object beamRangeIndex) {
                if (beamRangeIndex.is_none()) {
                    server.SetBeamRangeIndex(std::nullopt);
                    return;
                }

                server.SetBeamRangeIndex(py::cast<int>(beamRangeIndex));
            },
            py::arg("beam_range_idx"))
        .def("TryPopPacket", [](ZMQServer& server) -> py::object {
            ZMQServer::Packet packet;
            if (!server.TryPopPacket(packet)) {
                return py::none();
            }

            return PacketToDict(packet);
        });

    py::class_<ZMQSender>(module, "ZMQSender")
        .def(py::init<std::string>(), py::arg("endpoint") = "tcp://*:5566")
        .def("Bind", py::overload_cast<>(&ZMQSender::Bind))
        .def("Bind", py::overload_cast<const std::string&>(&ZMQSender::Bind), py::arg("endpoint"))
        .def(
            "SendControlPacket",
            [](ZMQSender& sender,
               const py::sequence& targets,
               const py::sequence& onOffFlags,
               const py::sequence& enableFlags) {
                sender.SendControlPacket(
                    ToTargetValues(targets),
                    ToChannelFlags(onOffFlags, "on/off"),
                    ToChannelFlags(enableFlags, "enable"));
            },
            py::arg("targets"),
            py::arg("on_off"),
            py::arg("enable"))
        .def(
            "SendControlPacket",
            [](ZMQSender& sender, const py::sequence& targets, std::uint64_t bitmask) {
                sender.SendControlPacket(ToTargetValues(targets), bitmask);
            },
            py::arg("targets"),
            py::arg("bitmask"));
}
