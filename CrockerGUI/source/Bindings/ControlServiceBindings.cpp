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

const char* ToString(Controls::SequenceRunState state)
{
    switch (state) {
    case Controls::SequenceRunState::Idle: return "Idle";
    case Controls::SequenceRunState::Running: return "Running";
    case Controls::SequenceRunState::Dwelling: return "Dwelling";
    case Controls::SequenceRunState::Completed: return "Completed";
    case Controls::SequenceRunState::Stopped: return "Stopped";
    case Controls::SequenceRunState::Faulted: return "Faulted";
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

void ReadOptionalDoubleArray(const py::dict& source, const char* key, auto setter)
{
    if (!source.contains(key)) {
        return;
    }
    const py::sequence values = source[key].cast<py::sequence>();
    if (values.size() != static_cast<py::ssize_t>(Controls::ChannelCount)) {
        throw py::value_error(std::string(key) + " must contain one value per control channel");
    }
    for (std::size_t index = 0; index < Controls::ChannelCount; ++index) {
        setter(index, py::cast<double>(values[index]));
    }
}

std::vector<Controls::ScalingPoint> PointsFromObject(const py::object& source, bool rawToEngineering)
{
    std::vector<Controls::ScalingPoint> points;
    if (source.is_none()) {
        return points;
    }
    const py::sequence values = source.cast<py::sequence>();
    for (const py::handle item : values) {
        if (py::isinstance<py::dict>(item)) {
            const py::dict point = py::reinterpret_borrow<py::dict>(item);
            py::object input = py::none();
            py::object output = py::none();
            if (point.contains("input")) {
                input = point["input"];
            } else if (point.contains("x")) {
                input = point["x"];
            }
            if (point.contains("output")) {
                output = point["output"];
            } else if (point.contains("y")) {
                output = point["y"];
            }
            if (input.is_none() && output.is_none() && point.contains("raw") && point.contains("eng")) {
                input = rawToEngineering ? point["raw"] : point["eng"];
                output = rawToEngineering ? point["eng"] : point["raw"];
            }
            if (!input.is_none() && !output.is_none()) {
                points.push_back({py::cast<double>(input), py::cast<double>(output)});
            }
            continue;
        }

        const py::sequence pair = py::reinterpret_borrow<py::object>(item).cast<py::sequence>();
        if (pair.size() >= 2) {
            points.push_back({py::cast<double>(pair[0]), py::cast<double>(pair[1])});
        }
    }
    return points;
}

void ApplyTransformDict(
    const py::dict& source,
    double& gain,
    double& offset,
    bool& usesCurve,
    std::vector<Controls::ScalingPoint>& curve,
    bool rawToEngineering)
{
    if (source.contains("gain")) {
        gain = py::cast<double>(source["gain"]);
    }
    if (source.contains("offset")) {
        offset = py::cast<double>(source["offset"]);
    }
    const std::string type = source.contains("type") ? py::cast<std::string>(source["type"]) : "linear";
    py::object points = py::none();
    if (source.contains("points")) {
        points = source["points"];
    } else if (source.contains("curve")) {
        points = source["curve"];
    }
    if (type == "curve" || !points.is_none()) {
        curve = PointsFromObject(points, rawToEngineering);
        usesCurve = curve.size() >= 2;
    }
}

void ApplyLegacyChannelScaling(Controls::LinearChannelScaling& scaling, const py::dict& entry)
{
    scaling.enabled = entry.contains("enabled") ? py::cast<bool>(entry["enabled"]) : true;

    if (entry.contains("raw_to_eng") && py::isinstance<py::dict>(entry["raw_to_eng"])) {
        ApplyTransformDict(
            py::reinterpret_borrow<py::dict>(entry["raw_to_eng"]),
            scaling.rawToEngineeringGain,
            scaling.rawToEngineeringOffset,
            scaling.rawToEngineeringUsesCurve,
            scaling.rawToEngineeringCurve,
            true);
    }

    if (entry.contains("eng_to_raw") && py::isinstance<py::dict>(entry["eng_to_raw"])) {
        ApplyTransformDict(
            py::reinterpret_borrow<py::dict>(entry["eng_to_raw"]),
            scaling.engineeringToRawGain,
            scaling.engineeringToRawOffset,
            scaling.engineeringToRawUsesCurve,
            scaling.engineeringToRawCurve,
            false);
    }
}

Controls::ControlScaling ScalingFromDict(const py::dict& source)
{
    Controls::ControlScaling scaling{};
    ReadOptionalDoubleArray(source, "raw_to_eng_gain", [&](std::size_t index, double value) {
        scaling[index].rawToEngineeringGain = value;
    });
    ReadOptionalDoubleArray(source, "raw_to_eng_offset", [&](std::size_t index, double value) {
        scaling[index].rawToEngineeringOffset = value;
    });
    ReadOptionalDoubleArray(source, "eng_to_raw_gain", [&](std::size_t index, double value) {
        scaling[index].engineeringToRawGain = value;
    });
    ReadOptionalDoubleArray(source, "eng_to_raw_offset", [&](std::size_t index, double value) {
        scaling[index].engineeringToRawOffset = value;
    });

    if (source.contains("enabled")) {
        const py::sequence values = source["enabled"].cast<py::sequence>();
        if (values.size() != static_cast<py::ssize_t>(Controls::ChannelCount)) {
            throw py::value_error("enabled must contain one value per control channel");
        }
        for (std::size_t index = 0; index < Controls::ChannelCount; ++index) {
            scaling[index].enabled = py::cast<bool>(values[index]);
        }
    }

    const std::array<std::string, Controls::ChannelCount> channelKeys = {
        "ch1", "ch2", "ch3", "ch4", "ch5", "ch6", "ch7",
        "ch8", "ch9", "ch10", "ch11", "ch12", "main_magnet", "centering_beam",
    };
    for (std::size_t index = 0; index < channelKeys.size(); ++index) {
        const std::string& key = channelKeys[index];
        if (source.contains(key.c_str()) && py::isinstance<py::dict>(source[key.c_str()])) {
            ApplyLegacyChannelScaling(scaling[index], py::reinterpret_borrow<py::dict>(source[key.c_str()]));
        }
    }

    return scaling;
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
    if (source.contains("max_absolute_error")) config.maxAbsoluteError = source["max_absolute_error"].cast<double>();
    if (source.contains("max_overshoot")) config.maxOvershoot = source["max_overshoot"].cast<double>();
    if (source.contains("max_control_output")) config.maxControlOutput = source["max_control_output"].cast<double>();
    if (source.contains("max_saturation_seconds")) config.maxSaturationSeconds = source["max_saturation_seconds"].cast<double>();
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

Controls::SequenceRunConfig SequenceRunConfigFromDict(const py::dict& source)
{
    Controls::SequenceRunConfig config;
    if (source.contains("update_rate_hz")) {
        config.updateRateHz = source["update_rate_hz"].cast<double>();
    }
    if (source.contains("target_tolerance")) {
        config.targetTolerance = source["target_tolerance"].cast<double>();
    }
    if (source.contains("step_timeout_seconds")) {
        config.stepTimeoutSeconds = source["step_timeout_seconds"].cast<double>();
    }
    if (source.contains("require_connected")) {
        config.requireConnected = source["require_connected"].cast<bool>();
    }
    if (source.contains("disable_channels_on_stop")) {
        config.disableChannelsOnStop = source["disable_channels_on_stop"].cast<bool>();
    }

    const py::sequence steps = source["steps"].cast<py::sequence>();
    config.sequence.reserve(static_cast<std::size_t>(steps.size()));
    for (const py::handle item : steps) {
        const py::dict step = py::reinterpret_borrow<py::dict>(item);
        Controls::SequencePoint point;
        point.timeSeconds = step.contains("dwell_seconds")
            ? step["dwell_seconds"].cast<double>()
            : step["time_seconds"].cast<double>();

        if (step.contains("targets")) {
            const py::dict targets = py::reinterpret_borrow<py::dict>(step["targets"]);
            for (const auto& [key, value] : targets) {
                const std::size_t channel = py::cast<std::size_t>(key);
                if (channel >= Controls::ChannelCount) {
                    throw py::value_error("sequence target channel index is out of range");
                }
                point.targets[channel] = py::cast<double>(value);
            }
        } else {
            const std::size_t channel = step["channel"].cast<std::size_t>();
            if (channel >= Controls::ChannelCount) {
                throw py::value_error("sequence channel index is out of range");
            }
            point.targets[channel] = step["target"].cast<double>();
        }

        config.sequence.push_back(point);
    }
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

py::dict SequenceStatusToDict(const Controls::SequenceRunStatus& status)
{
    py::dict out;
    out["state"] = ToString(status.state);
    out["message"] = status.message;
    out["step_index"] = status.stepIndex;
    out["step_count"] = status.stepCount;
    out["elapsed_seconds"] = status.elapsedSeconds;
    out["dwell_remaining_seconds"] = status.dwellRemainingSeconds;
    out["target_reached"] = status.targetReached;
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
            [](Controls::ControlService& service, const std::string& endpoint, py::object scaling) {
                if (scaling.is_none()) {
                    service.StartServer(endpoint);
                    return;
                }
                service.StartServer(endpoint, ScalingFromDict(scaling.cast<py::dict>()));
            },
            py::arg("endpoint") = "tcp://0.0.0.0:5555",
            py::arg("scaling") = py::none())
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
        .def("SetScaling", [](Controls::ControlService& service, const py::dict& scaling) {
            service.SetScaling(ScalingFromDict(scaling));
        }, py::arg("scaling"))
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
        })
        .def("StartSequence", [](Controls::ControlService& service, const py::dict& config) {
            service.StartSequence(SequenceRunConfigFromDict(config));
        }, py::arg("config"))
        .def("StopSequence", &Controls::ControlService::StopSequence,
            py::arg("disable_channels") = false)
        .def("SequenceStatus", [](const Controls::ControlService& service) {
            return SequenceStatusToDict(service.SequenceStatusSnapshot());
        });
}
