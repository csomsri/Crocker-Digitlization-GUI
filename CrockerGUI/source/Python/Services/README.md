# Runtime Add-On Services

These Python services sit around the C++ transport/control layer. They enrich
live machine snapshots with configuration-driven metadata and records, but they
are not the hard real-time control loop.

## Current Services

- `BeamCalibrationService.py`
  - Converts beam-current readback into calibrated display values.
  - Uses `config/beam_cal.json`.

- `AlarmService.py`
  - Watches configured RF/vacuum signals for warning conditions.
  - Can save/reload the active alarm config.
  - Uses `config/alarm_config.json`.

- `SignalMapService.py`
  - Adds named backend signals such as `rf_kv`, `vac1`, and
    `main_magnet_current` to transport snapshots.
  - Uses `config/signal_map.json`.

- `InterlockService.py`
  - Evaluates configured safety rules against named snapshot signals.
  - Can mark telemetry channels as interlocked.
  - Can filter command dictionaries by forcing interlocked channels off and
    disabled.
  - Uses `config/interlock_config.json`.

- `CalibrationWorkbookService.py`
  - Imports/exports scaling curve `.xlsx` workbooks.
  - Appends calibration-history records to `.xlsx` files.
  - Uses only the Python standard library for its simple workbook format.

## Important Reminder

The current interlock service is intentionally a Python-side policy layer. This
is fine while rules and limits are still being reviewed, but it should not be
treated as the final hardware safety gate.

Before relying on interlocks for unattended or high-confidence hardware
operation, move the enforcement path into C++ or directly beside the C++ command
gateway so commands cannot bypass it.

The baseline `config/interlock_config.json` ships with:

```json
"enabled": false
```

Leave it disabled until real machine limits and channel mappings have been
reviewed.
