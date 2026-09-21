# Adaptive-Direction PID Update

## Purpose

This update implements the beam-current PID flow shown in Figure 3 of
`MOP6342_edited_version.pdf` while preserving the separate **PID CONTROL** and
**GA AUTO-TUNE** tabs.

The controlled variable is the calibrated extracted beam current in nA. The
actuator is a selectable trim coil, with **TC10 selected by default**.

## Error and direction logic

The signed tracking error is still calculated and displayed:

```text
e[k] = beam_setpoint - beam_measured[k]
```

Because `e[k]` can be positive or negative, the PID magnitude is calculated from
its absolute value:

```text
E[k] = abs(e[k])
```

The actuator direction is a separate state, `d[k] = +1` or `-1`:

```text
PID_magnitude = limit(Kp*E + Ki*integral(E) + Kd*dE/dt)
delta_TC_target = d * PID_magnitude
```

At each configurable direction-comparison interval:

- If `E` decreased, keep the same direction.
- If `E` increased beyond the trend tolerance, reverse the direction.
- If the change is within the trend tolerance, retain the direction.
- If `E` is inside the deadband, send zero increment and hold the TC target.

A change in the sign of `e` does **not** by itself reverse the actuator. For
example, `e = +2 nA` followed by `e = -1 nA` is an improvement because
`abs(e)` fell from `2 nA` to `1 nA`; the direction is therefore retained.

## New PID-page displays

The PID tab now emphasizes the error decision with:

- signed error `e`;
- error magnitude `|e|`;
- color-coded magnitude trend: decreasing, increasing, steady, or deadband;
- current adaptive direction `d`;
- beam setpoint versus measured-beam graph;
- absolute-error versus deadband graph;
- signed TC increment, PID magnitude, and P/I/D magnitude terms;
- current TC target and next proposed TC target.

The absolute-error trend is green when decreasing, red when increasing, amber
when steady/initializing, and cyan inside the deadband.

## New-sample protection

The main GUI may poll faster than new beam packets arrive. The PID tab now
executes the control law only once for each new beam sample timestamp. A held
sample cannot be integrated repeatedly or generate several TC commands before
new feedback is available.

The **PID Poll Period** only controls how often the GUI checks for a new beam
sample. The actual PID update interval is calculated from consecutive beam
sample receive timestamps.

## Timing choice

The paper reports an approximately 1 s first-order time constant and a measured
10–90% response time of about 2.17 s. The GUI therefore starts with a
configurable **1.0 s direction-check interval**. This interval is an
implementation setting informed by the measured plant response; the schematic
does not prescribe an exact numeric interval.

## Beam feedback path

`MagneticFieldControllerWindow.py` now takes `beam_current` and
`beam_range_idx` from the same CNL packet already supplied to the controller. It
uses the existing `beam_cal.volts_to_nA(...)` calibration path and stores the
calibrated sample in `ControllerContext` with a freshness timestamp.

The PID stops if beam feedback is missing or older than the selected stale-data
limit.

## Hardware-output protection

The PID starts in preview mode. Armed commands are accepted only when:

1. **ARM HARDWARE OUTPUT** is checked;
2. an output callback is connected;
3. the selected actuator is TC1 through TC12;
4. the selected trim coil is powered ON and enabled;
5. the controller owns PID mode;
6. the beam measurement is valid and fresh.

The signed PID output is added to the existing engineering-unit TC target and
then passes through the project's existing target limits, engineering-to-raw
scaling, and control queue.

Start with preview mode, conservative gains, a small maximum `delta TC`, and
verified TC target limits. Confirm that the displayed `|e|` trend and adaptive
direction behave correctly before arming hardware output.

## Files changed

- `pid_controller.py`
- `pid_ga_control_tab.py`
- `controller_context.py`
- `MagneticFieldControllerWindow.py`
- `controller_theme.py`
- `test_pid_modules.py`

The GA backend and GA page remain separate and otherwise unchanged.

## Backend verification

From the project folder:

```bat
python test_pid_modules.py
```

The tests cover:

- conventional signed PID behavior;
- positive and negative signed errors;
- crossing the setpoint without an incorrect direction reversal;
- reversal only when absolute error increases;
- deadband hold behavior;
- trend-tolerance noise rejection;
- delayed direction decisions;
- learning either sign of a simple TC-to-beam plant;
- the existing GA backend.
