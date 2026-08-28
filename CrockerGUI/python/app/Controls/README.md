# Controls
This includes the windows where the Cyclotron shall be controlled Digtially

## Beam Range Mental Model

Think of Beam Range like a manual stick shift.

The beam current is the road speed. The range selector is the gear. Changing
gear does not create the motion by itself; it changes how much useful resolution
you get from the measurement.

- Low beam range is like low gear.
  - Use it for tiny beam currents.
  - You get finer sensitivity, like having more torque and control at low speed.
  - If the beam gets too large for that range, the readback can saturate or stop
    being useful.

- High beam range is like high gear.
  - Use it for larger beam currents.
  - You get more headroom before the measurement tops out.
  - You lose some fine sensitivity for very small currents.

- Full scale is like the top speed of that gear.
  - A `1 nA` range means the gauge is most meaningful from zero up to about
    that range's full scale.
  - A `100 uA` range can measure much larger current, but it is a coarse gear
    for tiny beam signals.

So the operator question is not "what beam do I want?" It is:

```text
What measurement gear should I be in so the current readback is sensitive but
not saturated?
```

For now the GUI reads the live machine as ground truth. Manual beam range
selection changes the calibration used to interpret the beam readback; it should
not be treated like a command that changes the beam itself.

## Field Control Sequencer Direction

The sequencer should live as a tab/workflow inside Field Control, not as a
separate Automation page. It is part of direct trim-coil operation: operators
are telling the Field Control system how to move channel targets over time.

The basic sequence entry should be simple:

```text
target value + dwell time
```

Example:

```text
Ramp TC1 to 100 A, then wait 5 s.
Ramp TC1 to 150 A, then wait 10 s.
Ramp TC1 to 0 A, then wait 3 s.
```

The important behavior is:

- The operator enters a target value and a time value.
- The control system ramps from the current target/readback toward the requested
  target.
- Once the requested target is reached, the sequencer holds there for the
  requested time.
- After the dwell time finishes, the next sequence step begins.
- The machine readback remains ground truth; the sequencer is only changing the
  intended target path.

So a step like `100 A for 5 s` means:

```text
Go to 100 A, wait at 100 A for 5 seconds, then move to the next step.
```

This should feel like a structured version of manually typing targets into the
Field Ctrl page and pressing Apply, with safety checks and status visible while
it runs.

## Sequencer Implementation Notes

The first sequencer implementation is split this way:

- C++ `ControlService`
  - Owns the actual sequence runner thread.
  - Accepts sparse sequence steps.
  - Applies channel targets through the same pending-command and transport path
    used by Field Ctrl.
  - Waits until the target is reached within tolerance.
  - Dwells for the requested time.
  - Stops on transport disconnect, telemetry timeout, channel fault, or
    interlock.

- Python `FieldCtrlPage`
  - Adds a Sequencer tab inside Field Control.
  - Lets the operator enter rows of `Channel`, `Target A`, and `Dwell s`.
  - Calls the C++ `StartSequence`, `StopSequence`, and `SequenceStatus`
    bindings.
  - Keeps the displayed Field Ctrl targets synchronized while the sequence runs.

This is intentionally not wired through the AI Control / Automation section.
