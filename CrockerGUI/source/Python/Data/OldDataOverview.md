# Data Overview

This project is a Python-based cyclotron/control-system GUI with monitoring,
calibration, sequencing, alarms, snapshot recall, and SQLite logging. The data
being worked with falls into four main groups:

1. Live control/monitoring samples from LabVIEW or a simulator.
2. Calibration data that converts raw values into engineering units.
3. Operator-facing settings, alarm thresholds, sequences, and snapshots.
4. UI assets used by the monitoring and controller windows.

* Please note that this overview is not a complete reference. It is meant to give
  a practical mental model of the data flow and how the various files relate to.
* Also note that this is an older project that has been updated over time. Some files are legacy and may not be used in the current system.

## OLD Main Data Flow

```text
LabVIEW / simulator / ZMQ packet
        |
        v
zmq_rep_server.py
        |
        v
sqlite_logger.py
        |
        v
cyclotron_data_fresh.db -> channel_data table
        |
        v
monitoring windows, plotting, SQLite viewer, alarms, snapshots
```

The key idea is that incoming data is logged in a single SQLite table. Older
columns preserve the original channel layout, while newer columns add explicit
raw and engineering-unit values side by side.

## SQLite Databases

### `cyclotron_data_fresh.db`

This is the current database target used by `sqlite_logger.py`.

- Table: `channel_data`
- Current row count inspected: `0`
- Purpose: ready-to-use logging database with the expanded schema.
- Timestamp column: `timestamp` as a `REAL`
- Digital/status column: `bitmask` as an `INTEGER`

Important column groups:

| Group | Columns | Meaning |
| --- | --- | --- |
| Legacy trim/control channels | `ch1` through `ch12`, `main_magnet`, `centering_beam` | Original channel values preserved for compatibility. |
| Raw trim values | `ch1_raw` through `ch12_raw`, `main_magnet_raw`, `centering_beam_raw` | Direct raw values from the incoming packet. |
| Engineering trim values | `ch1_eu` through `ch12_eu`, `main_magnet_eu`, `centering_beam_eu` | Calibrated values after scaling. |
| Source/extraction legacy | `arc_voltage`, `arc_current`, `filament`, `esd_kv`, `esd_ma`, `outside_iron`, `inside_iron` | Source and extraction readings. |
| Source/extraction raw | `arc_voltage_raw`, `arc_current_raw`, `filament_raw`, `esd_kv_raw`, `esd_ma_raw`, `outside_iron_raw`, `inside_iron_raw` | Raw source/extraction values. |
| Source/extraction engineering | `arc_voltage_eu`, `arc_current_eu`, `filament_eu`, `esd_kv_eu`, `esd_ma_eu`, `outside_iron_eu`, `inside_iron_eu` | Scaled source/extraction values. |
| Vacuum legacy/raw | `vac1` through `vac5`, `vac1_raw` through `vac5_raw` | Vacuum channel readings before conversion. |
| Vacuum engineering | `vac1_mbar` through `vac5_mbar` | Vacuum readings stored in mbar. |
| Beam current | `beam_current`, `beam_raw`, `beam_ua` | Beam-current raw and scaled values. |
| RF | `rf_kv_raw`, `rf_kv` | RF power/voltage raw value and kV value. |
| Timing | `latency` | Packet or logging latency, in milliseconds. |

### `CNL cyberpunk_Controller3 - SQLite - Monitoring/cyclotron_data.db`

This is an older populated database.

- Table: `channel_data`
- Current row count inspected: `146391`
- Schema: older/simple layout with `timestamp`, `ch1` through `ch12`,
  `main_magnet`, `centering_beam`, and `bitmask`.
- Purpose: useful as historical or sample data for the original monitoring
  layout.

## Calibration Files

### `calibration.json`

This is the main channel calibration file. It defines how raw values convert to
engineering values and how requested engineering values convert back to raw
output values.

Each key represents one channel or device signal, for example:

- Trim coils: `ch1` through `ch12`
- Magnet channels: `main_magnet`, `centering_beam`
- Source/extraction channels: `coax_a`, `inside_iron_a`, `outside_iron_a`,
  `esd_v`, `esd_a`, `filament_a`, `filament_v`, `arc_v`, `arc_a`
- Vacuum channels: `vac1` through `vac5`
- Beam/RF/transport channels: `beam_current`, `rf_power_kv`, `q1a_a`,
  `q1b_a`, `q2a_a`, `q2b_a`, `steer40_a`, `steer50_a`, collimator channels

Each channel has:

| Field | Meaning |
| --- | --- |
| `enabled` | Whether the calibration entry is active. |
| `raw_to_eng` | Converts raw input into engineering units for display/logging. |
| `eng_to_raw` | Converts desired engineering values back to raw output values. |
| `type: linear` | Uses `gain` and `offset`. |
| `type: curve` | Uses point pairs and interpolation. |

### `scaling_curves.xlsx`

This workbook stores calibration curve points by channel. Many sheets are named
after the same keys used in `calibration.json`.

- Example sheets with populated raw-to-engineering curves: `ch1`, `ch2`, `ch3`,
  `ch5`, `ch6`, `ch7`, `ch9`, `ch10`
- Many later device sheets exist as placeholders with `raw` and `eng` headers.
- The workbook appears to be a human-editable source for calibration curves.

### `calibration_records.xlsx` and `calibration_records1.xlsx`

These are saved calibration-history workbooks.

Common columns:

| Column | Meaning |
| --- | --- |
| `saved_at` | When the calibration record was saved. |
| `key` | Calibration/device key, such as `ch1`. |
| `group` | Logical group, such as `Trim`. |
| `label` | Operator-facing label, such as `TC1`. |
| `enabled` | Whether that calibration was enabled. |
| `r2e_gain`, `r2e_offset` | Raw-to-engineering linear parameters. |
| `e2r_gain`, `e2r_offset` | Engineering-to-raw linear parameters. |

`calibration_records.xlsx` has 197 rows. `calibration_records1.xlsx` has 50
rows and appears to be a later/smaller saved set.

## Beam Current Calibration

### `beam_cal.json`

This file defines beam-current ranges and how raw beam-current voltage maps to
beam current.

Configured ranges:

- `100 pA`
- `300 pA`
- `1 nA`
- `3 nA`
- `10 nA`
- `30 nA`
- `100 nA`
- `300 nA`
- `1 uA`
- `100 uA`

Most ranges use `mode: curve`, meaning each range contains a list of calibration
points like:

```text
[raw volts, current in nA]
```

Other settings:

| Field | Meaning |
| --- | --- |
| `select_mode` | `manual` or digital range selection. |
| `manual_index` | Selected range when manual mode is active. |
| `digital_source` | Where automatic range selection comes from, such as `bitmask_low4`. |
| `smooth_tau_s` | Smoothing time constant for display. |
| `deadband_display` | Small display changes below this are ignored. |
| `gauge_uses_range_fs` | Whether the gauge full scale follows the selected range. |
| `gauge_fullscale_override_uA` | Fixed full-scale value if range full-scale is disabled. |

The code in `beam_cal.py` loads this JSON, selects the active range, interpolates
curve points, and chooses display units.

## Sequencer Data

### `CNL_sequence_excel_example.xlsx`

This workbook is a template/example for time-based channel sequences.

Sheets:

| Sheet | Purpose |
| --- | --- |
| `Single_Channel_Sequence` | Time/value sequence for one selected channel. |
| `Multi_TC_Sequence` | Time-based sequence that can drive multiple trim coils. |
| `Instructions` | Human-readable instructions for using the template. |

The sequence format is centered around time steps:

- `Time [s]`
- Channel or value columns such as `Value [A]`, `TC1 [A]`, `TC2 [A]`, etc.

This data is used when the operator wants a channel or multiple trim coils to
follow a predefined time profile.

## Snapshot Data

### `trimcoil_snapshots.xlsx`

This workbook stores saved trim-coil states for recall.

- Sheet: `Snapshots`
- Current inspected size: 5 rows by 23 columns
- First columns: `timestamp`, `ch1`, `ch2`, `ch3`, ..., `ch11`

The snapshot file is meant to capture a known set of channel values so the
operator can return the system to a previous trim-coil configuration.

## Alarm and App Settings

### `alarm_config.json`

This file contains alarm thresholds and timing windows.

Important fields:

| Field | Meaning |
| --- | --- |
| `rf_dkv` | RF alarm delta threshold in kV. |
| `rf_window_s` | RF alarm comparison window in seconds. |
| `vac_factor` | Vacuum alarm factor threshold. |
| `vac_window_s` | Vacuum alarm comparison window in seconds. |
| `vac_channels` | Vacuum channels watched by alarms, currently `vac1` and `vac2`. |
| `rf_bg`, `vac_bg` | Background image names for alarm UI screens. |

### `app_settings.json`

This file controls plotting, logging, RF display, and vacuum display behavior.

Important fields:

| Field | Meaning |
| --- | --- |
| `plot_fps` | Target plot refresh rate. |
| `plot_sps` | Samples per second shown or processed by plots. |
| `plot_window_s` | Visible plot time window. |
| `log_batch` | Number of samples batched before database flush. |
| `log_flush_ms` | Maximum flush interval in milliseconds. |
| `rf_gauge_max_kv` | RF gauge full-scale value. |
| `rf_deadband_kv` | RF display deadband. |
| `vac_units` | Vacuum display unit, currently `mbar`. |
| `vac_min_exp`, `vac_max_exp` | Vacuum display exponent range. |
| `vac_tp_keys` | Vacuum channels associated with turbopump display keys. |

## Other Data Workbooks

### `SQ.xlsx`

This appears to be a numeric lookup or test-data workbook. It has one sheet,
`Sheet1`, inspected as 59 rows by 11 columns. The visible sample shows numeric
rows with values in the first column and later columns, but no descriptive
headers were present in the first inspected rows.

## Main Code Files That Use the Data

| File | Role |
| --- | --- |
| `main.py` / `main_control_gui.py` | Main application entry points and top-level GUI. |
| `zmq_rep_server.py` | Receives or simulates live packets for the system. |
| `sqlite_logger.py` | Creates/updates the SQLite schema and logs incoming samples. |
| `sqlite_viewer_qt.py` | Viewer for logged SQLite data. |
| `scaling.py` | Scaling/calibration helper used by the logger when available. |
| `beam_cal.py` / `beam_range.py` | Beam-current range calibration and display behavior. |
| `scale_cal_editor.py`, `ScaleCalWindow.py`, `SpinWheelCalWindow.py` | Calibration editing windows. |
| `snapshot_recall_qt.py` | Save/recall workflow for trim-coil snapshots. |
| `alarm.py`, `AlarmSettingsDialog.py` | Alarm processing and alarm configuration UI. |
| `MagneticFieldControllerWindow.py` | Main magnetic-field/trim-coil controller UI. |
| `MagneticFieldMonitoringWindow.py` | Magnetic-field monitoring UI. |
| `SourceExtractionMonitoringWindow.py` | Source/extraction monitoring UI. |
| `VacuumBeamMonitoringWindow.py` | Vacuum, beam-current, and RF monitoring UI. |
| `BeamTransportMonitoringWindow.py` | Beam transport monitoring UI. |

## Practical Mental Model

Use this model when changing or debugging the system:

1. Incoming packets provide raw live data.
2. `sqlite_logger.py` normalizes packet fields into the `channel_data` table.
3. `calibration.json`, `scaling_curves.xlsx`, and `beam_cal.json` explain how
   raw values should be interpreted.
4. The GUI windows display current values, trends, alarms, and saved states.
5. Excel workbooks hold editable calibration history, sequence templates, and
   saved snapshots.

If a number on screen looks wrong, check the path in this order:

1. Is the incoming raw value correct?
2. Is the right database column being logged?
3. Is the calibration entry enabled and using the right conversion type?
4. Is the display using raw, engineering units, or legacy columns?
5. Is the selected beam-current range or alarm setting affecting the displayed
   value?

