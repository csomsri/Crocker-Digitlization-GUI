# Field Control sequencer

The sequencer executes target-and-hold recipes. A step sends one or more current
targets, waits for measured arrival and settling, then holds for the requested
duration. LabVIEW/the simulator owns the physical current ramp. An omitted
channel keeps its prior target. Previously activated sequence channels remain
monitored, and all active sequence targets must be within tolerance to hold.

## Components

- `SequenceTypes.hpp`: definitions, durations, status, faults, events, stop
  policies, and the older `SequenceRunConfig` compatibility input.
- `SequenceValidator`: validates the complete recipe before ownership changes.
- `Sequencer`: deterministic state machine with an injected monotonic time.
- `SequenceRunner`: interruptible C++20 worker; feeds telemetry to the state
  machine, dispatches commands, catches failures, and publishes snapshots.
- `CommandGateway`: authoritative pending command, exclusive manual/sequence/PID
  ownership, sparse target merging, target checks, and reported interlock checks.
  `ControlService::mutex_` serializes gateway operations and transport sends.
- `ControlService`: public facade and lifecycle owner. Its operation mutex
  serializes starts, stops, and transport replacement without blocking worker
  access to the command mutex during a join.
- `SequencePanel.py`: Field Control editor and status display. It does not time
  steps or issue the sequence's individual commands.

## Timing and stop semantics

The UI uses 0.5 A tolerance, 0.2 s settling, 30 s arrival timeout, and a separate
1 s feedback timeout. Departing from tolerance resets the hold and reacquires
the targets. A step is additionally bounded by its arrival timeout plus hold
duration, preventing repeated departures from extending a run indefinitely.
Connection, finite feedback, channel faults, and interlocks are checked during
arrival, settling, and holding. An initial missing simulator packet is allowed
up to the feedback timeout; no targets are sent before feedback exists.

Successful completion retains final targets. Stop/fault defaults also retain
targets, so the machine may continue ramping toward them. The editor offers
"Disable sequence channels" as an alternative for both stop and fault; this
requests off/disable for every channel named anywhere in the recipe. It does
not ramp currents to zero. Disable dispatch failure is reported explicitly.
Normal stop is interruptible even at a low worker update rate.

`SendCommand` success means the transport staged the command, not that hardware
acknowledged or executed it. Neither a disable request nor a retained target is
a verified physical stop. Hardware readbacks remain ground truth.

## Integration

`StartSequence`, `StopSequence`, and `SequenceStatus` remain available through
the existing Python bindings. Sparse `targets` dictionaries and the original
single `channel`/`target` dictionaries are accepted. `time_seconds` remains a
compatibility alias for `dwell_seconds`, not an absolute schedule time.
`SequenceEvents()` exposes the latest run's transition history in memory;
persistent log export can consume it without changing execution logic.

Optional configuration keys include `settle_seconds`,
`telemetry_timeout_seconds`, `disable_channels_on_fault`, `minimum_targets`,
and `maximum_targets` (each limits array contains 14 values). The default
sequence input range is 0–1000 A, matching the existing Field Control editor;
this is an application input range, not a commissioned hardware safety limit.
Machine-specific bounds must be supplied by the caller. Hardware interlocks
reported in transport telemetry are enforced; separate Python alarm rules are
not automatically imported into C++.

Conflicting starts/manual writes are rejected while an automatic run owns the
commands. Stop the current run first to take over. `DisableAll` stops automatic
workers before dispatching disable, preventing a subsequent worker tick from
re-enabling channels. Scaling changes are rejected during automatic control.

## Validation

Build and run `SequencerTest`, `SequenceRunnerTest`,
`ControlServiceSequenceTest`, and `ControlServicePidTrialTest` with CTest.
Run `python tests/SequencePanelTest.py` after building the Python extension for
an offscreen, simulator-backed editor test. Add `--capture` to save a preview
under `build/sequence-panel.png`.

The tests cover deterministic timing, multi-channel arrival, hold restart,
feedback timeout/disconnection during hold, sticky faults, retained-channel
monitoring, input limits, ownership conflicts, cancellation, worker exceptions,
simulator execution, step editing, reordering, and stop policy. No live-machine
commissioning is implied. Excel import and absolute-time profiles are deferred.
