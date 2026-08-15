#include "Bindings.hpp"

#include "Controls/ControlTypes.hpp"
#include "Controls/Service/ControlService.hpp"

#include <pybind11/stl.h>

#include <string>

namespace py = pybind11;
namespace Controls = crocker::controls;

namespace {

const char* ToString(Controls::ChannelStatus status)
{
    switch (status) {
    case Controls::ChannelStatus::Unknown:
        return "Unknown";
    case Controls::ChannelStatus::Disabled:
        return "Disabled";
    case Controls::ChannelStatus::Off:
        return "Off";
    case Controls::ChannelStatus::Ready:
        return "Ready";
    case Controls::ChannelStatus::Warning:
        return "Warning";
    case Controls::ChannelStatus::Fault:
        return "Fault";
    case Controls::ChannelStatus::Interlocked:
        return "Interlocked";
    }

    return "Unknown";
}

const char* ToString(Controls::ConnectionState state)
{
    switch (state) {
    case Controls::ConnectionState::Disconnected:
        return "Disconnected";
    case Controls::ConnectionState::Connecting:
        return "Connecting";
    case Controls::ConnectionState::Connected:
        return "Connected";
    case Controls::ConnectionState::Degraded:
        return "Degraded";
    case Controls::ConnectionState::Faulted:
        return "Faulted";
    }

    return "Disconnected";
}

const char* ToString(Controls::AlarmSeverity severity)
{
    switch (severity) {
    case Controls::AlarmSeverity::Info:
        return "Info";
    case Controls::AlarmSeverity::Warning:
        return "Warning";
    case Controls::AlarmSeverity::Error:
        return "Error";
    case Controls::AlarmSeverity::Critical:
        return "Critical";
    }

    return "Info";
}

const char* ToString(Controls::PidTrialState state)
{
    switch (state) {
    case Controls::PidTrialState::Idle: return "Idle";
    case Controls::PidTrialState::Running: return "Running";
    case Controls::PidTrialState::Completed: return "Completed";
    case Controls::PidTrialState::Stopped: return "Stopped";
    case Controls::PidTrialState::Faulted: return "Faulted";
    }
    return "Idle";
}

template <typename Array>
void ReadDoubleArray(const py::dict& source, const char* key, Array& destination)
{
    const py::sequence values = source[key].cast<py::sequence>();
    if (values.size() != static_cast<py::ssize_t>(Controls::ChannelCount)) {
        throw py::value_error(std::string(key) + " must contain one value per control channel");
    }
    for (std::size_t index = 0; index < Controls::ChannelCount; ++index) {
        destination[index] = py::cast<double>(values[index]);
    }
}

Controls::PidTrialConfig PidTrialConfigFromDict(const py::dict& source)
{
    Controls::PidTrialConfig config;
    config.measurementChannel = source["measurement_channel"].cast<Controls::ChannelId>();
    config.setpoint = source["setpoint"].cast<double>();
    config.kp = source["kp"].cast<double>();
    config.ki = source["ki"].cast<double>();
    config.kd = source["kd"].cast<double>();
    config.updateRateHz = source["update_rate_hz"].cast<double>();
    config.durationSeconds = source["duration_seconds"].cast<double>();
    config.telemetryTimeoutSeconds = source["telemetry_timeout_seconds"].cast<double>();
    ReadDoubleArray(source, "allocation", config.allocation);
    ReadDoubleArray(source, "command_bias", config.commandBias);
    ReadDoubleArray(source, "minimum_command", config.minimumCommand);
    ReadDoubleArray(source, "maximum_command", config.maximumCommand);
    ReadDoubleArray(source, "maximum_slew_per_second", config.maximumSlewPerSecond);
    config.allocationCalibrated = source["allocation_calibrated"].cast<bool>();
    config.hardwareArmed = source["hardware_armed"].cast<bool>();
    config.dryRun = source["dry_run"].cast<bool>();
    return config;
}

py::dict PidTrialStatusToDict(const Controls::PidTrialStatus& status)
{
    py::dict out;
    out["state"] = ToString(status.state);
    out["message"] = status.message;
    out["elapsed_seconds"] = status.elapsedSeconds;
    out["measured_field"] = status.measuredField;
    out["error"] = status.error;
    out["control_output"] = status.controlOutput;
    out["iterations"] = status.iterations;
    out["saturated"] = status.saturated;
    out["rate_limited"] = status.rateLimited;
    out["watchdog_healthy"] = status.watchdogHealthy;
    return out;
}

py::dict ChannelTelemetryToDict(const Controls::ChannelTelemetry& telemetry)
{
    py::dict out;
    out["actual"] = telemetry.actual;
    out["raw"] = telemetry.raw;
    out["status"] = ToString(telemetry.status);
    out["on"] = telemetry.on;
    out["enabled"] = telemetry.enabled;
    out["interlocked"] = telemetry.interlocked;
    return out;
}

py::dict ChannelCommandToDict(const Controls::ChannelCommand& command)
{
    py::dict out;
    out["target"] = command.target;
    out["on"] = command.on;
    out["enabled"] = command.enabled;
    return out;
}

py::dict AlarmToDict(const Controls::Alarm& alarm)
{
    py::dict out;
    out["id"] = alarm.id;
    out["timestamp"] = alarm.timestampUnixSeconds;
    out["severity"] = ToString(alarm.severity);
    out["channel"] = alarm.channel.has_value() ? py::cast(*alarm.channel) : py::none();
    out["code"] = alarm.code;
    out["message"] = alarm.message;
    out["acknowledged"] = alarm.acknowledged;
    return out;
}

py::dict SnapshotToDict(const Controls::TelemetrySnapshot& snapshot)
{
    py::list channels;
    for (const Controls::ChannelTelemetry& channel : snapshot.channels) {
        channels.append(ChannelTelemetryToDict(channel));
    }

    py::list alarms;
    for (const Controls::Alarm& alarm : snapshot.activeAlarms) {
        alarms.append(AlarmToDict(alarm));
    }

    py::dict out;
    out["channels"] = channels;
    out["active_alarms"] = alarms;
    out["timestamp"] = snapshot.timestampUnixSeconds;
    out["latency_ms"] = snapshot.latencyMilliseconds;
    out["sequence_number"] = snapshot.sequenceNumber;
    out["connection"] = ToString(snapshot.connection);
    out["simulated"] = snapshot.simulated;
    return out;
}

py::dict HealthToDict(const Controls::HealthStatus& health)
{
    py::dict out;
    out["connection"] = ToString(health.connection);
    out["endpoint"] = health.endpoint;
    out["last_error"] = health.lastError;
    out["last_packet_timestamp"] = health.lastPacketUnixSeconds;
    out["packet_age_ms"] = health.packetAgeMilliseconds;
    out["update_rate_hz"] = health.updateRateHz;
    out["received_packets"] = health.receivedPackets;
    out["sent_packets"] = health.sentPackets;
    out["dropped_packets"] = health.droppedPackets;
    out["decode_errors"] = health.decodeErrors;
    out["simulated"] = health.simulated;
    return out;
}

py::list CommandToList(const Controls::ControlCommand& command)
{
    py::list out;
    for (const Controls::ChannelCommand& channel : command) {
        out.append(ChannelCommandToDict(channel));
    }
    return out;
}

} // namespace

void BindControlService(py::module_& module)
{
    py::class_<Controls::ControlService>(module, "ControlService")
        .def(py::init<>())
        .def("StartSimulator", &Controls::ControlService::StartSimulator, py::arg("update_rate_hz") = 60.0)
        .def(
            "StartServer",
            &Controls::ControlService::StartServer,
            py::arg("endpoint") = "tcp://0.0.0.0:5555")
        .def("Stop", &Controls::ControlService::Stop)
        .def("IsRunning", &Controls::ControlService::IsRunning)
        .def("SetChannelTarget", &Controls::ControlService::SetChannelTarget, py::arg("channel"), py::arg("target"))
        .def("SetChannelOn", &Controls::ControlService::SetChannelOn, py::arg("channel"), py::arg("on"))
        .def(
            "SetChannelEnabled",
            &Controls::ControlService::SetChannelEnabled,
            py::arg("channel"),
            py::arg("enabled"))
        .def(
            "SetChannelCommand",
            [](Controls::ControlService& service, Controls::ChannelId channel, double target, bool on, bool enabled) {
                service.SetChannelCommand(channel, Controls::ChannelCommand{target, on, enabled});
            },
            py::arg("channel"),
            py::arg("target"),
            py::arg("on"),
            py::arg("enabled"))
        .def("ApplyCommand", &Controls::ControlService::ApplyCommand)
        .def("DisableAll", &Controls::ControlService::DisableAll)
        .def("PendingCommand", [](const Controls::ControlService& service) {
            return CommandToList(service.PendingCommand());
        })
        .def("LatestSnapshot", [](const Controls::ControlService& service) {
            return SnapshotToDict(service.LatestSnapshot());
        })
        .def("Health", [](const Controls::ControlService& service) {
            return HealthToDict(service.Health());
        })
        .def("StartPidTrial", [](Controls::ControlService& service, const py::dict& config) {
            service.StartPidTrial(PidTrialConfigFromDict(config));
        }, py::arg("config"))
        .def("StopPidTrial", &Controls::ControlService::StopPidTrial,
            py::arg("disable_allocated_channels") = true)
        .def("PidTrialStatus", [](const Controls::ControlService& service) {
            return PidTrialStatusToDict(service.PidTrialStatusSnapshot());
        });
}
