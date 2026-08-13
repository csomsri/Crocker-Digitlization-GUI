# Field Control Behavior

This page defines the intended meaning of the Field Ctrl controls and the
expected startup behavior for the running-machine simulation.

## Core Terms

| UI Field | Meaning |
| --- | --- |
| Channel | The trim coil or related supply being viewed or commanded. |
| Actual | The live machine readback. This should always follow what the machine reports. |
| Target | The value the GUI is preparing to command when Apply is pressed. |
| Output / On | The desired output power state for that channel. |
| En | Whether the channel follows the GUI Target. |
| Apply | Sends the selected channel's Target, Output, and En state to the backend. |
| Hold | Copies the selected channel's current Actual value into Target. |
| Zero | Sets the selected channel's Target to 0 A. It does not command the machine until Apply is pressed. |

## Important Separation

Actual and Target are intentionally different.

- Actual is machine truth.
- Target is GUI intent.

If TC1 is already running at 200 A before the GUI opens, the GUI should show:

```text
Actual: 200.00 A
Target: 0.00 A
Output / On: ON
En: OFF
```

That means the machine output is on and being read, but the channel is not
following the GUI Target yet.

## Startup Behavior

On startup, Field Ctrl should read live telemetry from the backend before syncing
machine state into the UI.

For `smoke2`, the expected startup state is:

| Field | Expected Startup Value |
| --- | --- |
| Actual | The simulated machine's live current, such as 200.00 A for TC1. |
| Target | 0.00 A until the operator changes it or presses Hold. |
| Output / On | ON, because the simulated machine is already running. |
| En | OFF, because GUI control has not been enabled yet. |

The GUI must not treat an empty/default backend snapshot as real machine state.

## Taking Control

To take control of a running channel:

1. Confirm Actual shows the live machine value.
2. Leave Output / On set to ON.
3. Set Target to the desired command value.
4. Turn En ON.
5. Press Apply.

Example:

```text
Before:
Actual: 200.00 A
Target: 0.00 A
Output / On: ON
En: OFF

Operator action:
Target -> 300.00 A
En -> ON
Apply

After:
Actual should move from 200.00 A toward 300.00 A.
```

## Output / On Behavior

Output / On is not the same as GUI enable.

| Output / On | En | Intended Behavior |
| --- | --- | --- |
| ON | OFF | Channel output remains on, but it is not following the GUI Target. |
| ON | ON | GUI commands the channel toward Target. |
| OFF | ON | GUI commands the channel output off, so Actual should move toward 0 A. |
| OFF | OFF | Channel output is off, so Actual should move toward 0 A. |

This is why `smoke2` starts with Output / On set to ON. The machine is already
running, so the GUI should reflect that live output state at startup. Operators
can still turn trim coils off one by one, or use bulk controls, by changing
Output / On and pressing Apply.

## Hold Behavior

Hold is the explicit way to make Target match Actual.

Example:

```text
Actual: 200.00 A
Target: 0.00 A

Press Hold:
Target: 200.00 A
```

Hold does not send a command by itself. Apply is still required.

## Smoke2 Simulation

Launch with:

```powershell
python main.py -simulation -smoke2
```

`smoke2` models a machine that is already running:

- Channels start at nonzero live current.
- Output / On starts ON.
- En starts OFF.
- Actual follows the simulated machine readback.
- Target remains the GUI command value.
- Output / On can turn a channel output on or off.
- The machine follows Target only after En is ON and Apply is pressed.
