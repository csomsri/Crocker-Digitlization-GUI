# C++ NLAPID control and Bayesian tuning

`NLAPID.hpp` / `NLAPID.cpp` implement the Python adaptive-direction algorithm
as a standalone C++ class. The engine owns its integral history, derivative
filter, direction windows, and reset state. `ControlService` owns scheduling,
telemetry, actuator bounds/slew, transport, and run lifecycle. There are no
inline P/I/D equations in the service trial runner. Conventional trials call
`PID::propose()` and commit integral state through `PID::acceptIntegral()`.

## Use in the application

1. Rebuild the CycloViz extension and restart the application.
2. Open Automation > PID Control and select **C++ NLAPID** in Controller.
3. Configure the setpoint, gains, limits, and NLA settings. The channel actual
   value in amperes is the feedback; this is not beam-current regulation yet.
4. Arm and enable PID. The C++ service runs continuously on its worker thread;
   the GUI polls status. Dry Run advances virtual targets without sending them.
5. Stop/disarm holds the last command. Service faults use the existing fault
   shutdown path; dry-run faults do not send shutdown commands.

For Bayesian tuning, select the controller before opening Optimized Tuner.
The session freezes controller settings and searches Kp/Ki/Kd using the existing
Sobol / Gaussian-process / qLogEI workflow. Seven safe trials are needed to
execute a first model-guided candidate with the default six-trial seed budget.
The service calls the selected C++ class for every trial. History identifies
the controller kind; the optimizer rejects mixed-kind observations. Applying
reviewed gains restores the tested controller kind and NLA settings, leaving
control disabled. The separate PythonPID page still runs the Python reference.

## Service API

Existing `StartPidTrial(config)`, `PidTrialStatus()`, and `StopPidTrial()` bindings
remain available. Additional dictionary fields:

| Field | Default / meaning |
|---|---|
| `controller_kind` | `conventional` or `nla`; default conventional |
| `continuous` | false; true runs until stopped instead of duration expiry |
| `nla_deadband` | 0.0 |
| `nla_trend_tolerance` | 0.0 |
| `nla_direction_check_interval` | 1.0 seconds |
| `nla_initial_direction` | +1 |
| `nla_direction_confirmations` | 2 |
| `nla_minimum_direction_samples` | 3 |
| `nla_integral_memory_s` | 20.0 seconds of bounded control time |
| `nla_integral_window_multiplier` | 2.0; fallback when integral memory is zero |
| `nla_max_control_dt` | 0.25 seconds |
| `nla_reset_integral_in_deadband` | false |
| `nla_output_max` | 100.0 maximum increment; GUI uses Max Step |
| `nla_integral_max` | 100.0 maximum integral increment |
| `nla_derivative_filter_tau` | 0.05 seconds |

NLA currently requires direct single-channel allocation (1 for the measured
channel, 0 elsewhere). It starts from the pending channel target and consumes
each fresh telemetry timestamp once. Backward timestamps fault the run.

`NLAPID::update(setpoint, measurement, dt)` returns a **signed target increment**.
The service adds it to the previous target exactly once; no additional dt
factor or fixed command bias is applied. Target clipping/slew is tracked
separately from internal NLA increment saturation. When external limits prevent
following a step, the next update ages the integral with zero error. This
service-level integration policy supplements the reference engine's internal
anti-windup; it is not plant-model compensation.

Status adds `controller_kind`, `nla` (all reference result fields),
`command_target`, `command_delta`, `control_rate`, and `calculation_us`.
`control_output` remains the engine output: conventional offset versus NLA
increment. For NLA the tuner integrates absolute movement rate for its effort
term, avoiding a sample-rate-dependent sum of increments. Conventional effort
retains its historical offset-based definition. Costs belong to their selected
controller; use a common physical effort metric for cross-algorithm studies.

## Verification

From the repository root, after building CycloViz for the active Python:

```text
python CrockerGUI/tests/NLAPIDParityTest.py
python CrockerGUI/tests/CppNLAPIDIntegrationTest.py
python CrockerGUI/tests/PythonPIDPageTest.py
python CrockerGUI/tests/PidAutoRunTest.py
ctest --test-dir CrockerGUI/build -C Debug -R "^(PIDTest|ControlServicePidTrialTest)$" --output-on-failure
```

Parity replays 10,000 updates against Python, including reversals, window
expiration, setpoint changes, derivative filtering, saturation, and resets.
Integration tests use the actual C++ simulator, including seven NLA BO trials,
continuous control, dry run, timestamp deduplication, and watchdog faults.
No hardware run is part of these tests.
