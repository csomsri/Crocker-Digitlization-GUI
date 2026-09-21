# Database A and PID Database B

Database A remains `data/crocker_pipeline.sqlite3`. Database B is
`crocker_pid.sqlite3` beside the configured A database. Existing A history is
preserved. The migration adds nullable `runs.session_id` and
`readings.snapshot_id` columns and indexes.

## Activation

B creates no file, connection, or writer thread when a PID page opens, when a
coil is enabled, when output is armed, or during initial hybrid recovery.
A successful PID start creates the first B session. This covers continuous
C++ and Python PID, both GA pages, BO trials and hybrid GA/BO trials.
Preview/dry-run PID execution is recorded and explicitly labelled.

After a tuning trial, the session remains open for recovery and transitions
between candidates. Stop, completion or page close ends the session. A later
PID start creates a new session. The B worker stays available after its first
use, but idle pages do not produce samples.

## Tables and units

| B table | Contents |
|---|---|
| `pid_sessions` | UUID, associated A session when A is active, page, engine, feedback source, environment, initial configuration, start/end times |
| `pid_samples` | Source snapshot identity/time, beam timestamp/quality/calibration revision, TC number (one-based), actual/command A, measured/target beam nA, controller feedback/target/error/unit, gains, output, state, search mode, environment and flags |
| `pid_trials` | Trial UUID, session, source, and JSON result including cost, metrics, safety/termination information and hybrid comparison predictions |
| `pid_events` | Start/stop, configuration changes, state/recovery transitions, optimizer handovers, validation results and reasons |
| `recording_gaps` | Count and time of rejected mailbox messages when the writer can next commit |

TC actual current and TC commanded current are separate. So are calibrated beam
output and beam target. The existing PythonPID page still uses coil feedback in
A; its beam target is NULL. Beam-feedback pages use nA. A retains its existing
smoothed `beam_current` reading and adds unsmoothed `beam_control_current` in uA.

`controller_state` distinguishes PID, tuning, validation, recovery and waiting;
`search_mode` distinguishes manual, GA, BO and hybrid; `environment` distinguishes
hardware, simulation and dry run. Detailed hybrid source names are in trial rows.

## Concurrency and failure handling

Each database has its own dedicated writer thread and SQLite connection. The
GUI submits immutable messages to bounded mailboxes without waiting for disk.
All desktop telemetry, alarm events and derived-metric writes use A's mailbox.
The rolling-average processor owns a read-only connection and submits its results
to A's writer. It is no longer a second database writer process.

Snapshot extraction and Qt widget reads stay on the GUI thread. Database writes,
commits, schema initialization and busy retries stay on writer threads. Legacy
automatic CSV/JSON exports use a separate bounded worker. Database History queries
and PID CSV history reads run in workers and deliver results through Qt timers.

Writers coalesce up to 100 messages or 100 ms per transaction. Each mailbox allows
4,096 queued messages, reserving 128 places for session/event/trial messages.
The worker may additionally hold a batch of 100 messages. Rejected records are
counted, shown in the application status bar, and persisted as recording gaps
when storage recovers. Failed SQL batches remain pending for ordered retry.
Continuous control never waits for recording. Subsequent optimization trials
are refused when B reports an error, a large backlog, or rejected messages.
After a recording gap, restart the application after fixing storage to begin
a clean recording run.

Normal window close stops controllers, requests drains, and polls completion
asynchronously. A ten-second drain deadline reports incomplete recording rather
than blocking the Qt event loop. Queued memory is not a durable spool: a process
crash, forced exit, permanent disk failure, or deadline expiry can lose records.

## Sampling limits

A uses the existing field polling rate. B records native C++/Python trial-worker
status at the page polling rate (nominally 8 Hz), not every internal control
iteration. These rows have `sample_kind='status_poll'` and carry controller
iteration/elapsed information separately from the latest telemetry timestamp.
The existing native status API does not expose the exact feedback timestamp
used for that iteration; the beam timestamp is the accompanying observation.
Do not interpret these as synchronized high-rate controller traces.

GA PID steps and continuous Python PID updates also emit
`sample_kind='controller_update'` records from their calculation paths. B can
record independently while A logging is disabled. An A session UUID plus the
source timestamp/sequence-based snapshot identity allows matching recorded
snapshots without waiting for either database to commit; a matching A row is
not guaranteed when sampling rates differ or a recording gap occurs.

## Verification

Run `python tests/DatabaseWritersTest.py -v` from `CrockerGUI`.
Tests use temporary databases and simulated controllers, including independent
database locks, queue overflow with reserved event capacity, ordered retries,
unwritable storage, idle activation, both GA engines, Python feedback units,
hybrid costs/recovery, history reads and asynchronous application shutdown.
The C++ lock test verifies controller iterations and GUI timer events continue
while Database B cannot commit. These are responsiveness checks, not hard
real-time guarantees or hardware commissioning.
