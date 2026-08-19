#pragma once

#include "Controls/ControlTypes.hpp"

namespace crocker::controls {

class ControlTransportBase {
public:
    virtual ~ControlTransportBase() = default;

    ControlTransportBase(const ControlTransportBase&) = delete;
    ControlTransportBase& operator=(const ControlTransportBase&) = delete;
    ControlTransportBase(ControlTransportBase&&) = delete;
    ControlTransportBase& operator=(ControlTransportBase&&) = delete;

    virtual void Start() = 0;
    virtual void Stop() noexcept = 0;
    [[nodiscard]] virtual bool IsRunning() const noexcept = 0;

    virtual bool SendCommand(const ControlCommand& command) = 0;
    virtual void SetScaling(const ControlScaling& scaling) { (void)scaling; }

    [[nodiscard]] virtual TelemetrySnapshot LatestSnapshot() const = 0;
    [[nodiscard]] virtual HealthStatus Health() const = 0;

protected:
    ControlTransportBase() = default;
};

} // namespace crocker::controls
