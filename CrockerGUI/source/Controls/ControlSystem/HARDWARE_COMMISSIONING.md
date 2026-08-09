# BO PID hardware commissioning gates

The BO PID page is not authority to operate hardware. The C++ `ControlService`
owns the PID trial loop, command limits, slew limits, telemetry watchdog, and
failsafe shutdown. A non-dry-run hardware trial is rejected unless the caller
explicitly arms it and marks its allocation as calibrated.

## Allocation calibration

The frontend currently supplies a one-hot allocation only for simulation. Real
hardware must load a reviewed calibration that maps scalar field correction to
all relevant TC channels. Each allocated channel also requires an independently
reviewed bias, minimum command, maximum command, and maximum slew rate. Do not
set `allocation_calibrated=true` merely to bypass the gate.

Calibration provenance must include measurement date, machine configuration,
units, operator/reviewer, source dataset, uncertainty, and an expiration or
revalidation condition. The calibration loader and facility values are not part
of this repository yet.

## Required validation sequence

Each stage requires recorded evidence and approval before proceeding.

1. **Offline recorded data** — replay timestamped field and command data;
   verify units, score calculations, bounds, missing-data handling, and expected
   PID direction. No control transport is connected.
2. **Digital twin** — run the `SimulatorTransport` tests and BO frontend in
   simulation. Inject saturation, delayed telemetry, disconnects, interlocks,
   and command rejection.
3. **Hardware in the loop** — connect the ZMQ server to an HIL endpoint with
   real protocol timing but simulated actuators. Verify watchdog and independent
   emergency shutdown behavior.
4. **Output-disabled dry run** — connect to the facility readback path with
   `dry_run=true`. Confirm that proposed commands are observable in status/logs
   but no actuator command is transmitted.
5. **Low-current supervised trial** — use facility-approved bounds, calibrated
   allocation, independent current protection, an operator at the emergency
   stop, and a written rollback point.
6. **Controlled commissioning** — expand bounds only through the facility
   change-control process. Archive software version, configuration, calibration,
   complete telemetry, trial results, alarms, and operator approvals.

## Independent safety requirements

- Hardware/PLC interlocks and emergency stop must remain authoritative.
- Loss or staleness of telemetry must force a safe disabled command.
- GUI loss must not leave the PID loop dependent on GUI timing.
- A control-service crash must be handled by an external watchdog.
- Every command must be bounded and slew-limited below the optimization layer.
- Trials must start from a documented, repeatable machine condition.
- Best gains are staged for review; BO never installs them automatically.

The native simulator test is `ControlServicePidTrialTest`. It covers an active
bounded trial and verifies that dry-run mode does not move the simulated plant.
Facility HIL and physical commissioning tests must be supplied and executed by
the hardware team.
