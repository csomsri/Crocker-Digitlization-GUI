# NLAPID and the PythonPID page

`NLAPID.py` is the standalone Python reference extracted from the supplied
adaptive-direction controller. It requires only the standard library. It includes
all adaptive helpers and the gain, limit, settings, and result dataclasses; it
excludes the conventional PID, GUI, GA, and Bayesian optimizer.

## Basic use

Run with `CrockerGUI` on the Python import path (the same root used by the app):

```python
from source.Python.Control.NLAPID import (
    NLAPID, PIDGains, PIDLimits, AdaptiveDirectionSettings,
)

# Example values for simulation, not tuned machine gains.
pid = NLAPID(
    gains=PIDGains(kp=0.01, ki=0.0001, kd=0.001),
    limits=PIDLimits(output_min=0.0, output_max=0.1, integral_max=0.1),
    settings=AdaptiveDirectionSettings(
        deadband=0.05,
        trend_tolerance=0.05,
        direction_check_interval=0.5,
        direction_confirmations=2,
        minimum_direction_samples=3,
        initial_direction=1,
        integral_memory_s=20.0,
        max_control_dt=0.25,
    ),
)
pid.reset(setpoint=10.0, measurement=9.0)
result = pid.update(setpoint=10.0, measurement=9.1, dt=0.1)
current_target_a = 2.0
target_min_a, target_max_a = 0.0, 5.0
proposed_target_a = max(
    target_min_a, min(target_max_a, current_target_a + result.output)
)
print(proposed_target_a, result.direction, result.error_trend)
```

`result.output` is a signed increment in actuator units per update. Add it once
to the target; do not multiply it by dt again. P, I, and D result fields are also
increments. Gains define a movement rate before time scaling. Conventional PID
gains therefore are not automatically equivalent. Gains default to zero.

The controller uses absolute error, a finite moving integral, a filtered
damping-only derivative, and a direction chosen from averaged error trends.
It returns zero inside the deadband and on the sample that reverses direction.
The integral is always cleared on reversal: the retained compatibility setting
`reset_integral_on_direction_change` does not change this behavior.
`output_min` and `integral_min` are ignored by the adaptive engine. Upper limits
guard increments, not absolute actuator targets. All internal time accumulation
uses dt capped at `max_control_dt`, including integral and direction windows.

## PythonPID page integration

Open Automation > PythonPID. `python/app/Automation/PythonPIDPage.py` reuses
the existing PID page layout and shared backend, replacing the calculation with
NLAPID. It includes deadband, initial direction, direction-window and trend
tolerance editors. Bayesian tuning reuses the PID page's optimizer, trial
history, GP plot, approval, and gain application workflow. Python BO trials
run `PythonNLATrial` in a worker thread and calculate control with Python
`NLAPID`; ControlService supplies telemetry and the command gateway. Normal
continuous Python control still runs on the Qt timer.
The page currently controls the selected channel actual value in amperes, just
like the original page; it does not switch feedback to beam current.

The following integration rules describe the page and future extensions:

1. Provide setpoint, gains, deadband, direction interval/tolerance, initial
   direction, integral memory, actuator selection, and target-limit controls.
2. On start, reset from the current measurement and selected direction. On
   actuator changes, stop and reset before restarting.
3. Process each fresh telemetry sample once. Derive dt in seconds from monotonic
   sample timestamps; skip duplicates and reject stale/out-of-order samples.
4. Call `update()` and form `current_target + result.output`. Clamp the absolute
   target to the actuator's operating bounds.
5. In preview, display the proposal. When armed, submit through the existing
   command gateway with its ownership, power/enable, interlock, and ramp checks.
   The C++ and Python controllers must not both command the same actuator.
6. Stop on stale feedback or rejected commands. Keep display refresh separate
   from control updates. Show error, direction, trend, P/I/D increments,
   saturation, commanded target, and actual readback.

The engine has internal increment anti-windup but receives no acknowledgement
of external target clipping or hardware ramp lag. The integration must account
for those conditions; `hold_integrator=True` ages integral memory using zero
error, but still permits proportional/derivative output and direction changes.

## Compare Python and C++

The C++ runtime now supports NLAPID only. Compare C++ NLA and Python NLA as control
algorithms. The C++ port now lives in `source/Controls/ControlSystem/NLAPID.cpp`.
Use C++ NLAPID on the existing PID Control page to run it or tune it with
Bayesian trials. Compare language/runtime performance using
identical algorithms, parameters, initial state, and input samples.

Save a replay fixture of setpoint, measurement, and dt. Feed both implementations
that same fixture and compare every PIDResult field, including reversal timing,
deadband, saturation, and integral expiration. Preserve bounded-dt handling and
the one-sample reversal hold in the port.

Measure update duration with a monotonic high-resolution clock, reporting median,
95th percentile, maximum, and missed control deadlines. Exclude GUI rendering,
network I/O, and logging from the engine timing. Separately compare closed-loop
tracking error, overshoot, settling time, and actuator travel in the same
simulator with the same disturbances. Replay alone cannot measure closed-loop
plant response to different outputs.

Bayesian tuning creates a fresh engine with candidate gains for each trial.
The standalone NLAPID engine itself has no Bayesian dependency.

## Shared BO response metrics

Both main PID screens also display continuous-run response metrics from the
same evaluator. Enable PID to start an interval; stopping or closing saves it.
Recordings default to 60 seconds (adjustable from 10 to 600 seconds), after
which recording stops while PID control continues. Use Record another window
to measure another interval. A 10,000-sample guard also bounds memory use.
CSV samples are flushed during recording; an interrupted recording retains its
samples and an incomplete JSON marker. Run History / CSV filters recordings by
inclusive UTC start dates and exports the visible run summaries. Double-click
a run to view or export a one-based inclusive sample range (the header is not
a point). Samples display in pages of 1,000 rows. Files are retained on disk;
there is no automatic deletion of experimental data.

The main PID page defaults to C++ NLAPID; PythonPID always uses Python NLAPID.
Controller selection, adaptive settings, and output limits are under the
expandable settings button. BO Trial History shows the current session, with
optional gain/secondary columns and export by trial-number range. It is distinct
from persisted Run History: a trial is one gain candidate; a run is a recorded
continuous-control measurement window. Smaller cost, settling/transient times,
and steady error are preferred when comparing equivalent experiments. A faulted
trial is excluded from training; a completed but oscillating trial is penalized.
Changing setpoint, gains, or controller settings ends the old interval and
starts a new one. Select the tuning-method label before enabling PID; applying
BO gains selects Bayesian optimization automatically. The label is descriptive
and does not run a tuning method.

Run summaries (JSON) and response samples (CSV) are automatically written to
`CrockerGUI/logs/pid_runs`. Summaries include settings, method, backend,
dry-run status, duration, termination reason, and final metrics. Live settling
is provisional and is revoked when the response exits tolerance. Steady error
and RMS use the latest 20% of the measurement interval, matching BO evaluation.
Continuous monitoring flags oscillation without automatically stopping control.
Sampling follows fresh telemetry at the GUI polling rate (nominally 8 Hz),
so this is not a high-frequency instability detector. Compare equal-duration
runs with matching starting conditions, setpoints, limits, and disturbances.

Both PID pages have a **Response Metrics** popup beside Trial History. BO uses
the same Sobol initialization and GP acquisition pipeline on both pages; only
the trial controller changes. The popup reports first entry into tolerance
(transient time), settling time (remaining inside tolerance through the end,
for at least 0.5 seconds), and final-20%-of-trial mean absolute error and RMS.
Tolerance is the greater of 0.1 measurement units, 1% of the target magnitude
(with a floor of one unit), and the NLA deadband. Unsettled responses are labeled.

Overshoot is displayed with zero cost weight. All profiles penalize oscillation;
Suppress oscillation doubles that penalty. Hysteretic error turning points
ignore swings within twice the tolerance. Non-decaying completed swings trigger
a large additional penalty. After at least one second and two detected cycles,
the tuner stops a persistently oscillating trial and records its penalized score
so BO can learn from it. Such gains cannot be approved. This detector uses GUI
status samples and can miss oscillations faster than the polling rate.

Balanced cost is settling time + 0.25 transient time + 4 steady-state absolute
error + 0.01 integrated absolute control rate + oscillation penalty, with 25
added for an unsettled response. Other profiles adjust these weights. Approval
uses observed trial results; it does not perform a separate validation run.
