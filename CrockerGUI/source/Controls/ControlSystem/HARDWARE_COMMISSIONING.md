# BO PID hardware commissioning gates

## Direct trim-coil BO

The PID tuner now supports TC1–TC12 current control, one coil per trial, without
`pid_hardware_profile.json`. It uses identity allocation to the selected coil and
the existing control transport scaling. The PID page's Min Cmd, Max Cmd and Max
Step settings remain active, along with explicit arming, dry run and telemetry
checks. Scaling is a unit conversion, not proof of safe operating limits.
The beam-feedback PID/BO page requires a reviewed profile, including when
connected to hardware with dry run enabled. Simulation does not load a profile.
The shared trial-start path also applies the profile to hybrid BO and continuous
PID. It reloads `config/pid_hardware_profile.json` before each trial, so a changed
or expired profile cannot silently reuse a previous approval.

The BO PID page is not authority to operate hardware. The C++ `ControlService`
owns the PID trial loop, command limits, slew limits, telemetry watchdog, and
failsafe shutdown. A non-dry-run hardware trial is rejected unless the caller
explicitly arms it and marks its allocation as calibrated, except for the
direct coil-current feedback path described above.

## Allocation calibration

For direct single-TC beam control with LabVIEW ramping, explicit operator approval
of numerical limits may be recorded separately from calibration provenance using
`approval_basis: "operator_limits"`. This records the approver, statement, time,
and a digest of all approved per-coil settings. Changed settings require renewed
approval. This is not a calibration certificate and does not permit custom or
multi-coil allocation. The existing calibration-provenance workflow remains
available for profiles that do not use operator-limits approval.

Use **PID page → Edit Hardware Profile** to edit coil limits, abort thresholds,
and provenance. Saves default to draft; approval requires explicitly confirming
independent review and completing provenance. Editing a value clears that
confirmation. Saving is blocked during PID/optimization sessions and if the
file changed since opening the editor. Changes take effect at the next trial.
The bundled TC10 draft contains illustrative values, not approved machine limits.

The local legacy reference `ExperimentFiles/pid_ga_control_tab.py` defaults to
0–800 A for ordinary PID and delegates physical ramping to LabVIEW. Automatic
GA additionally limits excursions to ±0.5 A from a captured baseline, rate to
1 A/s, absolute beam error to 3 nA, and continuous saturation to 5 seconds.
These are historical software defaults, not facility approval. There is no
separate legacy overshoot abort or narrow per-update PID-output abort; its
numerical output guard is the configured TC span. Do not treat these differing
controls as interchangeable profile fields.

The beam-feedback frontend loads `config/pid_hardware_profile.json` and selects
the entry keyed by the actuator TC under `measurement_channels` (a legacy key
name; feedback remains beam current). The current NLA worker requires identity
allocation: `1.0` for the selected TC and zero for every other channel. Custom
field or multi-channel mappings are not supported by this worker.
The main profile form requires minimum and maximum current. Abort thresholds
are under Advanced limits; calibration review is on its own tab. There is no
manual baseline: the worker starts from the live pending command, and GA/hybrid
continue capturing their recovery baseline automatically.
Profiles saved by the editor use `ramp_control: "labview"`, omit `command_bias`
and `maximum_slew_per_second`, and send zero slew limits to the rebuilt backend
to disable app-side command ramping. Absolute current and abort limits remain
active. Older profiles without this mode retain their explicit slew limits.
The frontend intersects profile command bounds with UI/hybrid bounds and rejects
non-overlapping bounds. Saves validate and atomically replace the JSON in a
background worker; closing the editor does not cancel an in-progress save.
Beam error and overshoot limits are in nA, command limits in A, slew in A/s,
and saturation duration in seconds. Do not
set `allocation_calibrated=true` merely to bypass the gate.

Calibration provenance must include measurement date, machine configuration,
units, operator/reviewer, source dataset, uncertainty, and an expiration or
revalidation condition. Copy `config/pid_hardware_profile.example.json`, replace
every placeholder with measured facility values, set `approval_status` to
`approved` only after independent review, and save it without the `.example`
suffix. Invalid, draft, incomplete, or expired profiles fail closed.

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
