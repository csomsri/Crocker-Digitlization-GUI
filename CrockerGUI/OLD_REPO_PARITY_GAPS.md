# Old Repo Parity Gaps

This note starts the hardware-readiness review session. The current repo has enough of the Field Ctrl path to begin cautious machine testing, but it does not fully match the old repo yet.

## Current Position

- Field Ctrl ZMQ control is the main hardware-ready path.
- Trim coil scaling is live in the transport path.
- The data logger copies transport snapshots instead of applying its own scaling.
- Beam calibration, signal mapping, interlock, alarm, and calibration workbook services exist as add-on/backend services. Active baseline config files are present, but they still need site calibration review and more complete UI coverage.
- Field Control sequencer is likely the most relevant missing capability after hardware bring-up starts.

## Missing Or Incomplete Capabilities

1. [x] Active baseline config files
   - Added active baseline `config/beam_cal.json`.
   - Added active baseline `config/alarm_config.json`.
   - Remaining: replace baseline values with final machine calibration after site review.

2. [x] Field Control sequencer foundation
   - C++ `ControlService` has a sequence runner for target+dwell steps.
   - Python bindings expose start, stop, and status.
   - Field Ctrl has a Sequencer tab for entering channel, target, and dwell rows.
   - Sequencer should live as a tab/workflow inside Field Control, not as a separate Automation page.
   - Sequencer runs should integrate with scaling, snapshots, logging, and operator-visible status.
   - Basic step model: enter a target value and dwell time; ramp to the value, then wait for the requested time before continuing.
   - Remaining: validate against live ZMQ/hardware and add old-style template import if operators still need Excel sequence files.

3. [x] Curve editing in the UI
   - Backend scaling can support curve/interpolation entries.
   - Scaling page supports curve point editing and scaling workbook import.
   - Remaining: validate against real old-style calibration workbooks/operators before calling this complete.

4. [x] Backend device signal calibration coverage
   - Live scaling currently focuses on the 14 Field Ctrl channels.
   - Added `config/signal_map.json` and a signal-map service for broader device classes:
     - source/extraction
     - vacuum
     - RF
     - beam transport
     - beam current
     - main magnet / trim coils
   - Remaining: replace baseline signal assumptions with final machine calibration after site review.

5. [ ] Monitoring pages are not fully live
   - Monitoring pages exist, but most are shells or routed through Field Ctrl state.
   - Backend signal maps now provide named signals for vacuum, RF, source/extraction, beam transport, beam current, and main magnet.
   - Remaining: connect/finish UI page coverage for each monitoring view.

6. [x] Alarm settings UI
   - Alarm engine exists and can view/reload/acknowledge active alarms.
   - Alarm page can edit and save current RF/vacuum thresholds, timing windows, channels, engine state, and event logging.
   - Remaining: add any old alarm display options and additional rule types needed by operators.
   - If oscillating too much set alarm.

7. [ ] Beam range UI completeness
   - Beam Range page shows calibrated beam state and supports manual range selection.
   - It does not expose every old `beam_cal.json` option from the GUI yet.

8. [x] Backend calibration records / Excel workflows
   - Old repo had `scaling_curves.xlsx`, `calibration_records.xlsx`, and related calibration-history behavior.
   - Added backend helpers to export/import scaling curve workbooks and append calibration-history records.
   - Remaining: add operator-facing UI/actions only if needed.

9. [x] Backend interlocks / safety rules
    - Alarm detection exists.
    - Added `config/interlock_config.json` and an interlock service that marks interlocked telemetry channels and can filter commands by forcing interlocked channels off/disabled.
    - Baseline interlocks are disabled until real machine limits are reviewed.
    - Remaining: wire command filtering directly into any future non-UI command gateway used for unattended operation.

10. [ ] Snapshot / recall workflow
    - Lowest priority.
    - Original goal was closer to a copy/paste convenience feature for machine settings.
    - Since the GUI reads the live machine as ground truth, this is not needed for the main hardware-ready path.
    - Keep only if operators later want a workflow for copying current readbacks into prepared target values.

## Review Focus

For the immediate review session, prioritize:

1. Field Ctrl ZMQ command and telemetry correctness.
2. Scaling direction and config loading.
3. Logger correctness for raw, engineering, bitmask, beam, and alarms.
4. Startup/shutdown behavior around LabVIEW and ZMQ.
5. Any race or stale-snapshot behavior that could affect real hardware testing.
6. Field Control sequencer live ZMQ/hardware validation.
