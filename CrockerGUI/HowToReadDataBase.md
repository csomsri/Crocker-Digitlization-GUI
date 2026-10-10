# How to read the database for PID results

**Start with `CrockerGUI/data/crocker_pid.sqlite3`.** This is the PID database.
Use **DB Browser for SQLite** for the instructions below. A “trial” is one tested
set of gains; a “session” can contain several trials and recovery periods.

## 1. Open the correct file

1. Stop the experiment and close the Crocker GUI normally so queued records finish writing.
2. Open **DB Browser for SQLite** → **Open Database**.
3. Select `CrockerGUI/data/crocker_pid.sqlite3` in this project. If the application
   was launched with another database location, the PID file is beside that
   database and still named `crocker_pid.sqlite3`.
4. Select **Browse Data**, then choose `pid_sessions` in the **Table** dropdown.
5. To use a query below, select **Execute SQL**, paste **one query**, and press
   the **Run ▶** button. Replace `PASTE_SESSION_ID` or `PASTE_TRIAL_ID` with the
   actual ID, keeping the single quotes.
6. Export a query's result grid with its **Save results / Export** control and
   choose CSV. For a whole table, use **File → Export → Table(s) as CSV file**.

Use a local copy for analysis. If copying while the application is running,
the `.sqlite3` file alone may omit records still in its `-wal` file; closing
the application normally before copying is the simplest method.

## 2. Know what each database contains

| File / table | What it tells you |
|---|---|
| `crocker_pipeline.sqlite3` — Database A | General machine telemetry, independent of PID. |
| A: `runs` | Telemetry recording runs and start/end times. |
| A: `readings` | Timestamped channel readings, raw/engineering values and units. |
| A: `processed_metrics`, `alarm_events`, `operator_notes` | Derived values, alarms and notes. |
| `crocker_pid.sqlite3` — Database B | PID execution, BO/GA/Hybrid trials and controller events. |
| B: `pid_sessions` | Page, engine, hardware/simulation/dry-run environment, configuration and session times. |
| B: `pid_trials` | One completed search result: trial ID, source and JSON containing gains, cost and metrics. |
| B: `pid_samples` | Measured response, setpoint, error, coil command/readback and gains over time. |
| B: `pid_events` | Trial starts, configuration changes, validation outcomes, transitions and stop reasons. |
| B: `recording_gaps` | Dropped recording messages; inspect before selecting data for the paper. |

Database B starts recording after PID successfully starts. Arming, enabling a
coil, or opening a page alone does not create a PID experiment.
The BO **Trial History / Results** page shows the current in-memory search;
SQLite keeps earlier sessions after the application closes.

## 3. Find the experiment by time

Run this in Database B. Newest sessions appear first:

```sql
SELECT id AS session_id,
       strftime('%Y-%m-%d %H:%M:%f', started_at, 'unixepoch', 'localtime') AS start_local,
       strftime('%Y-%m-%d %H:%M:%f', ended_at, 'unixepoch', 'localtime') AS end_local,
       page, engine, feedback_source, environment
FROM pid_sessions
ORDER BY started_at DESC;
```

1. Find the date and time when you pressed **Run trial / Start PID**.
2. For the BO beam page, look for `page = PidControlPage` and
   `feedback_source = calibrated_beam`.
3. Check `environment`: `hardware`, `simulation`, or `dry_run`. Keep these
   categories separate when reporting experimental results.
4. Copy the full `session_id`. Do not match trials by time alone.

**Examples in the database inspected on October 10, 2026:** a recent simulation
PID session ran October 9, **13:00:03–13:00:09**. Stored BO result rows include
September 21 at **12:33:04, 12:34:05 and 12:34:48**. These are examples from the
existing file, not timestamps of a new hardware experiment. Example times are
Pacific daylight time; `localtime` uses the timezone of the computer viewing
the database.

### Which timestamp should you use?

| Field | Meaning |
|---|---|
| `pid_sessions.started_at` / `ended_at` | Whole PID session boundaries. |
| `pid_trials.timestamp` | When the result was submitted for recording, near trial completion. **Not the trial start.** |
| Result JSON: `result.started_at` / `result.ended_at` | BO/Hybrid trial boundaries recorded after this history fix. |
| `pid_events.timestamp`, event `pid_started` | Trial start event; `details` contains its `trial_id` and configuration. |
| `pid_samples.timestamp` | When the application recorded the observation. |
| `controller_elapsed` | Worker-reported elapsed seconds; use for the BO response plot's horizontal axis. |
| `beam_timestamp` / `telemetry_timestamp` | Accompanying beam/transport observation times; not guaranteed to be the exact input time of that controller iteration. |

Absolute timestamps are Unix seconds (UTC). The SQL conversion makes them
readable; retain the original numbers and state your timezone when exporting.
An empty `ended_at` can mean an ongoing session or an interrupted recording.

## 4. List the BO trials and their results

Paste your session ID below. Cost is **lower-is-better**; it is not beam current.

```sql
SELECT t.id AS trial_id,
       strftime('%Y-%m-%d %H:%M:%f',
                json_extract(t.result, '$.result.started_at'),
                'unixepoch', 'localtime') AS trial_start_local,
       strftime('%Y-%m-%d %H:%M:%f', t.timestamp,
                'unixepoch', 'localtime') AS result_recorded_local,
       json_extract(t.result, '$.result.candidate.kp') AS kp,
       json_extract(t.result, '$.result.candidate.ki') AS ki,
       json_extract(t.result, '$.result.candidate.kd') AS kd,
       json_extract(t.result, '$.result.score') AS cost,
       json_extract(t.result, '$.result.safe') AS valid,
       json_extract(t.result, '$.result.metrics.steady_state_error') AS steady_error,
       json_extract(t.result, '$.result.metrics.steady_state_rms') AS steady_rms,
       json_extract(t.result, '$.result.overshoot') AS overshoot,
       CASE WHEN json_extract(t.result, '$.result.metrics.settled') = 1
            THEN json_extract(t.result, '$.result.metrics.settling_time')
       END AS settling_s,
       json_extract(t.result, '$.result.metrics.settled') AS settled_label,
       json_extract(t.result, '$.result.termination_reason') AS reason,
       (SELECT COUNT(*) FROM pid_samples s WHERE s.trial_id = t.id) AS recorded_rows
FROM pid_trials t
WHERE t.session_id = 'PASTE_SESSION_ID' AND t.source = 'BO'
ORDER BY t.timestamp, t.id;
```

`valid = 1` means the trial was accepted for optimizer training, not that it
settled or was approved by validation. `valid = 0` means a failed/invalid trial;
large penalty costs such as `1e12` are not successful measurements.
Settling and oscillation flags are diagnostic labels under the October policy.
`settling_s` is empty when the response did not satisfy its recorded settling
criteria. BO's stored steady error/RMS diagnostics estimate the final 20% of
the sampled trace; the October fitness steady-state term uses its separate
score window (5 seconds by default). State which measurement/window you report.

The `result` cell contains JSON. Double-click it in **Browse Data** to inspect
the full metrics/configuration. Older results can have no trial-start field.
October scoring is identified by a non-NULL `result.metrics.october_score`;
do not compare those costs directly with older objective-function costs.

GA results use `score` and `gains` at the top level of JSON instead of
`result.score` and `result.candidate`. Hybrid source names also include
baseline/confirmation stages; inspect their `comparison` object.

## 5. Export one BO response for the paper

Copy a `trial_id` from step 4. This query keeps the first recorded observation
of each worker iteration and removes repeated status polls:

```sql
WITH response AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY controller_iteration ORDER BY id
    ) AS observation
    FROM pid_samples
    WHERE trial_id = 'PASTE_TRIAL_ID'
      AND controller_state = 'tuning'
      AND sample_kind = 'status_poll'
      AND controller_iteration > 0
)
SELECT controller_elapsed AS elapsed_s,
       feedback AS measured, target AS setpoint, error, feedback_unit,
       tc_channel, tc_command_a, tc_actual_a, kp, ki, kd,
       controller_output, controller_iteration,
       timestamp AS recorded_unix_s, beam_timestamp, telemetry_timestamp,
       beam_quality, calibration_revision, environment, enabled, armed
FROM response
WHERE observation = 1
ORDER BY controller_elapsed, id;
```

Plot **measured and setpoint versus elapsed_s**, then **error versus elapsed_s**.
Plot `tc_command_a` and `tc_actual_a` separately: a requested target is not the
same as measured coil current. Beam feedback uses **nA**; coil current uses **A**.
The separate Python coil-feedback page uses `feedback_unit = A`.

These BO rows are polled status observations, not every internal controller
update. Gaps in `controller_iteration` reveal skipped updates. Do not infer
high-frequency oscillations or reproduce the exact optimizer score from this
trace alone. Use stored trial metrics for the recorded score and disclose the
sampling method in the paper.

## 6. Check validation and recording quality

```sql
SELECT strftime('%Y-%m-%d %H:%M:%f', timestamp,
                'unixepoch', 'localtime') AS time_local,
       event, details
FROM pid_events
WHERE session_id = 'PASTE_SESSION_ID'
ORDER BY timestamp, id;
```

1. Look for `pid_started` and check gains, setpoint, limits and averaging settings.
2. Look for `validation_result`; validation is recorded as an event and response
   samples, not necessarily a separate `pid_trials` row. For its trace, use the
   trial ID from its `pid_started` event and change the response query's state
   to `validation`.
3. Check stop reasons, beam quality/calibration changes, disabled output and
   `recording_gaps`. Keep invalid/incomplete runs identifiable rather than
   silently combining them with successful trials.
4. For recordings made **before this fix**, verify that the trial's samples have
   the same gains and start window as its `pid_started` event. The previous
   result-recording timing could misassociate trial IDs. Existing historical
   rows are preserved; they are not automatically repaired. A zero
   `recorded_rows` count is a reason to investigate the session, not proof the
   experiment produced no measurements.
5. Save the trial ID, session ID, CSV, gains, setpoint, environment, configuration,
   sample count, duration and validation outcome with each reported figure.

To inspect the surrounding machine data, open Database A. Match
`pid_sessions.a_session_id` to `runs.session_id`, then select `readings` for that
run/time window. A's `beam_control_current` is in **µA** (multiply by 1,000 for
nA); `beam_current` is the display-smoothed value. A matching `snapshot_id`
helps join observations, but differing sampling rates can leave unmatched rows.

Viewer reference: [DB Browser for SQLite](https://sqlitebrowser.org/),
[official project](https://github.com/sqlitebrowser/sqlitebrowser).
