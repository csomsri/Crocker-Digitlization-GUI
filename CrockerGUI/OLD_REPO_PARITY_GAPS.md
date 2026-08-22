# Old Repo Parity Gaps

This note starts the hardware-readiness review session. The current repo has enough of the Field Ctrl path to begin cautious machine testing, but it does not fully match the old repo yet.

## Current Position

- Field Ctrl ZMQ control is the main hardware-ready path.
- Trim coil scaling is live in the transport path.
- The data logger copies transport snapshots instead of applying its own scaling.
- Beam calibration and alarm services exist as add-on services, but they still need real site config files and more complete UI coverage.
- Sequencer/automation is likely the most relevant missing capability after hardware bring-up starts.

## Missing Or Incomplete Capabilities

1. Active config files
   - Add real `config/beam_cal.json`.
   - Add real `config/alarm_config.json`.
   - Current repo has examples, not final machine calibration.

2. Sequencer / automation parity
   - Old-style sequence templates and run workflows are not fully connected to live hardware.
   - Sequencer runs should integrate with scaling, snapshots, logging, and operator-visible status.
   - This is the highest-priority parity item after basic Field Ctrl hardware testing.

3. Curve editing in the UI
   - Backend scaling can support curve/interpolation entries.
   - Scaling page is still mainly a linear gain/offset editor.
   - Need curve import/edit support if operators should manage old-style calibration from the GUI.

4. Full device calibration coverage
   - Live scaling currently focuses on the 14 Field Ctrl channels.
   - Old repo covered broader device classes:
     - source/extraction
     - vacuum
     - RF
     - beam transport
     - beam current
     - main magnet / trim coils

5. Monitoring pages are not fully live
   - Monitoring pages exist, but most are shells or routed through Field Ctrl state.
   - Need full backend signal maps for vacuum, RF, source/extraction, beam transport, and beam current.

6. Alarm settings UI
   - Alarm engine exists and can view/reload/acknowledge active alarms.
   - Need full UI editing for thresholds, timing windows, channels, and old alarm display options.
   - If oscillating too much set alarm 

7. Beam range UI completeness
   - Beam Range page shows calibrated beam state and supports manual range selection.
   - It does not expose every old `beam_cal.json` option from the GUI yet.

8. Snapshot / recall workflow
   - Pages exist, but old-style saved-state and recall behavior is still thin.
   - Need clearer operator workflows for capturing, inspecting, and restoring machine state.

9. Calibration records / Excel workflows
   - Old repo had `scaling_curves.xlsx`, `calibration_records.xlsx`, and related calibration-history behavior.
   - Current repo does not yet import/export those workbook workflows.

10. Interlocks / safety rules
    - Alarm detection exists.
    - A complete action/interlock layer that blocks or modifies commands based on machine state is not implemented.

## Review Focus

For the immediate review session, prioritize:

1. Field Ctrl ZMQ command and telemetry correctness.
2. Scaling direction and config loading.
3. Logger correctness for raw, engineering, bitmask, beam, and alarms.
4. Startup/shutdown behavior around LabVIEW and ZMQ.
5. Any race or stale-snapshot behavior that could affect real hardware testing.
6. Sequencer design requirements before building the next live-control feature.
