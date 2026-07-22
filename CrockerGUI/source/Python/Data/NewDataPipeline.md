# New Data Pipeline

This document proposes the data pipeline for the current Crocker Digitalization
GUI. It is meant to describe the target architecture, the responsibilities of
each process, and the practical mental model for how data should move through
the system.

The main goal is to keep acquisition, storage, processing, and display separate.
The GUI should not own the logging loop, SQLite should preserve raw data before
analysis, and CUDA should be used only where large numerical batches justify the
extra complexity.

## Proposed Main Data Flow

```text
Hardware / simulator / ZMQ source
        |
        v
Python data logger process
        |
        v
SQLite raw data tables
        |
        v
Python data processor process
        |
        +--> routine processing in Python / NumPy
        |
        +--> heavy batch processing in CUDA / C++
        |
        v
SQLite processed data tables
        |
        v
GUI monitoring, alarms, plots, recall, and database viewer
```

The key idea is that the raw measurement stream is saved first, before heavier
processing or display logic touches it. Raw data should remain replayable. If a
processor crashes, the logger should keep collecting data. If the GUI closes,
the logger should be able to keep collecting data.

## Current Implementation

The first implementation lives in this directory:

| File | Role |
| --- | --- |
| `pipeline_schema.py` | Creates SQLite connections, enables WAL mode, and initializes the pipeline tables. |
| `data_logger.py` | Standalone Python logger process. The first source is smoke simulation frames. |
| `data_processor.py` | Standalone Python processor process. The first processor computes rolling averages. |
| `pipeline_manager.py` | Starts and stops the logger and processor from the GUI. |

The GUI can start the experimental pipeline with:

```text
python main.py -simulation -smoke --data-pipeline
```

The default database path is:

```text
data/crocker_pipeline.sqlite3
```

The logger and processor can also be run manually:

```text
python -m source.Python.Data.data_logger --db-path data/crocker_pipeline.sqlite3
python -m source.Python.Data.data_processor --db-path data/crocker_pipeline.sqlite3
```

The current logger source is the smoke simulator. Logging real ZMQ/control data
will require a telemetry fan-out, shared snapshot source, or publish/subscribe
stream so the logger can observe telemetry without competing with the existing
request/reply control connection.

## What To Do Next

Use this as the reminder list when returning to the data pipeline later:

1. Add a real telemetry source for the logger.
   - The current logger uses smoke simulation frames.
   - For real data, add a ZMQ publish/subscribe stream, telemetry fan-out, or
     shared snapshot source so logging does not interfere with control
     request/reply traffic.
2. Build a small database monitoring page.
   - Show the selected SQLite path.
   - Show latest run metadata.
   - Show recent `readings` rows.
   - Show recent `processed_metrics` rows.
3. Connect calibration metadata.
   - Load channel names, engineering units, and scaling rules from the
     calibration system.
   - Replace placeholder `units = raw` values with real engineering units.
4. Add operator controls.
   - Start/stop logging from the GUI.
   - Choose a database path.
   - Add run labels, operator name, and notes.
5. Expand processing only after the raw data path is stable.
   - Add real alarms and summary metrics first.
   - Add CUDA only for proven heavy batch workloads, not for routine database
     or GUI work.
6. Add replay/export tools.
   - Replay a previous `run_id` through plots.
   - Export selected readings or metrics to CSV.
   - Keep old runs readable even if the schema evolves.

Things that can wait:

| Later task | Why it can wait |
| --- | --- |
| CUDA kernels | Need a specific heavy calculation and representative data first. |
| Database migration system | Useful after the schema changes a few times. |
| Postgres or time-series database | SQLite is enough until local logging becomes a proven bottleneck. |
| Advanced dashboards | Raw logging and simple processed metrics should be reliable first. |

## Main Data Groups

The new system should treat data as five main groups:

1. Live raw readings from hardware, simulator, or ZMQ.
2. Calibration metadata that converts raw values into engineering units.
3. Processed results such as rolling averages, spectra, fitted values, model
   predictions, and alarm events.
4. Operator-facing configuration such as thresholds, run labels, selected
   channels, and display preferences.
5. Run/session metadata that ties readings, processing results, and operator
   notes together.

## Process Responsibilities

| Component | Responsibility |
| --- | --- |
| Acquisition source | Produces live samples from real hardware, a simulator, or a ZMQ endpoint. |
| Python data logger | Runs independently from the GUI, timestamps incoming samples, batches writes, and stores raw readings in SQLite. |
| SQLite raw database | Stores raw data durably with run IDs, timestamps, channel names, values, units, and source metadata. |
| Python data processor | Reads raw data, applies routine calculations, schedules heavy jobs, and writes derived results. |
| CUDA/C++ module | Accelerates expensive batch calculations such as waveform analysis, large simulation steps, FFT-style processing, optimization, or high-volume matrix/vector work. |
| SQLite processed tables | Store metrics, alarms, summaries, model outputs, and completed processing results for display and review. |
| GUI | Reads current and historical data from SQLite, displays state, and controls start/stop/configuration without blocking acquisition. |

## SQLite Database Model

SQLite should be the first database target because it is simple, local,
inspectable, and included with Python. It is a good fit for a first reliable
logging layer.

Suggested initial tables:

| Table | Purpose |
| --- | --- |
| `runs` | One row per logging session, experiment, or operator-defined run. |
| `readings` | Raw timestamped channel values from the live source. |
| `processed_metrics` | Derived values such as rolling averages, calibrated values, fitted values, spectra, or model outputs. |
| `alarm_events` | Alarm state transitions, thresholds, measured values, and timestamps. |
| `processing_jobs` | Optional queue/status table for larger CPU or CUDA processing jobs. |
| `operator_notes` | Optional run notes, comments, labels, or shift information. |

Possible starter schema:

```sql
CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at REAL NOT NULL,
    ended_at REAL,
    mode TEXT NOT NULL,
    source TEXT NOT NULL,
    operator TEXT,
    notes TEXT
);

CREATE TABLE readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    channel TEXT NOT NULL,
    raw_value REAL,
    engineering_value REAL,
    units TEXT,
    source TEXT NOT NULL,
    quality TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE processed_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    units TEXT,
    window_start REAL,
    window_end REAL,
    processor TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE alarm_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    alarm_name TEXT NOT NULL,
    channel TEXT,
    state TEXT NOT NULL,
    measured_value REAL,
    threshold_value REAL,
    message TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
```

SQLite should use WAL mode so one process can write while other processes read:

```sql
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
```

The logger should be the only process that writes raw readings. Processors can
write derived tables. GUI code should mostly read, with explicit write actions
only for operator configuration, notes, or commands.

## Logger Design

The logger should be intentionally simple:

1. Connect to the selected source.
2. Create or resume a `runs` row.
3. Receive or poll samples.
4. Timestamp each sample as close to acquisition as possible.
5. Normalize each sample into channel/value rows.
6. Batch inserts into SQLite.
7. Commit regularly.
8. Shut down cleanly and mark the run as ended.

The logger should not run complex analysis. It should focus on preserving the
truth of what arrived.

Recommended logger behavior:

| Behavior | Recommendation |
| --- | --- |
| Process model | Separate Python process launched by the GUI or by a command line script. |
| Write ownership | Owns writes to `readings`. |
| Batch size | Configurable, for example 50 to 500 readings per commit. |
| Flush interval | Configurable, for example 250 ms to 1000 ms. |
| Error handling | Keep logging if one malformed packet arrives; record quality/status when possible. |
| Shutdown | Mark `runs.ended_at` and close the SQLite connection. |

## Processor Design

The processor should run separately from the logger. It can tail new raw
readings, process by time window, or process by explicit jobs.

Routine processing should stay in Python first:

- calibration checks
- rolling average/min/max
- alarm threshold comparisons
- simple smoothing
- plotting summaries
- run summaries

CUDA/C++ should be used only for large work where the GPU wins after accounting
for CPU-to-GPU and GPU-to-CPU transfer cost:

- waveform or image-like batch processing
- beam simulation batches
- large matrix/vector operations
- optimization over many candidate settings
- FFT-style spectral analysis
- high-volume model evaluation

CUDA should not write directly to SQLite. The safer pattern is:

```text
Python processor reads raw rows
        |
        v
Python batches numeric arrays
        |
        v
CUDA/C++ computes heavy result
        |
        v
Python receives result
        |
        v
Python writes processed rows to SQLite
```

This keeps database ownership simple and makes CUDA an accelerator rather than
the control center of the data system.

## GUI Role

The GUI should treat the database as its source of truth for stored data. It can
show live values, historical plots, alarm state, and processed metrics, but it
should not block while waiting for logging or processing.

The GUI can be responsible for:

- choosing the ZMQ endpoint or simulator mode
- starting and stopping the logger process
- starting and stopping the processor process
- displaying logger/processor health
- reading recent values for monitoring pages
- reading processed metrics for plots and dashboards
- adding operator notes or run labels

The GUI should avoid:

- long blocking database writes
- direct CUDA work on the UI thread
- owning the only copy of live data
- doing heavy processing in timer callbacks

## Practical Mental Model

Use this model when building or debugging the new system:

1. The acquisition source produces live raw values.
2. The logger preserves those values in SQLite as quickly and plainly as
   possible.
3. Calibration metadata explains how raw values become engineering values.
4. The processor reads raw data and writes derived facts.
5. CUDA accelerates only the expensive numerical sections of processing.
6. The GUI reads raw and processed data without owning the acquisition loop.
7. Runs connect everything together so a session can be replayed, analyzed, and
   audited later.

If a displayed number looks wrong, check the path in this order:

1. Did the source send the expected raw value?
2. Did the logger write the expected row to `readings`?
3. Is the row attached to the correct `run_id`?
4. Is the calibration metadata correct and enabled?
5. Did the processor compute the expected derived value?
6. Did CUDA receive the expected batch, if CUDA was involved?
7. Is the GUI reading the intended raw or processed table?

## Migration Notes From Old Project

The old project used a single `channel_data` table centered around a fixed
channel layout. The new system should prefer a more flexible row-oriented
reading table:

```text
old:
timestamp, ch1, ch2, ch3, ..., main_magnet, bitmask

new:
timestamp, channel, raw_value, engineering_value, units, source, run_id
```

This makes it easier to add new channels without changing the schema every time.
It also makes processing jobs easier because channel names can be filtered and
grouped directly.

For early compatibility, the GUI can still expose views that look like the old
wide table. Those should be database queries or helper functions, not the core
storage shape.
