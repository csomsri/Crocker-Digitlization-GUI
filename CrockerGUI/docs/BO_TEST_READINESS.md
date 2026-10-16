# October PID and BO readiness — October 14, 2026

The local simulation workflow is ready to exercise. This is not a hardware commissioning approval or proof of optimized gains.

## Start the GUI

From the repository root:

```powershell
python CrockerGUI/main.py -simulation -first-order --data-pipeline --db-path data/bo-test/crocker_pipeline.sqlite3
```

Use Automation -> PID + BO -> AI tuning · BO. Keep the first-order preset (TC10, 0.8 nA, gain ranges Kp, Ki and Kd each 0–1). Use 10 trials and 20 seconds per trial, then Run trial budget. The first six usable observations initialize the model; trial seven and later can use the GP/acquisition model. Model preparation may take longer on the first run because PyTorch/BoTorch imports are cold. Watch the preparation status before interpreting a pause as a hung trial.

For individual trials, expand Manual trials, Prepare session, then Run Proposed Trial. Review results in Results / history. On the tuning page, the review controls are below the response plots. Validate best gains starts the separate validation run (60 seconds by default). Apply is disabled until validation completes successfully. Applying gains does not itself enable normal PID. Stop control stops the active controller/tuning workflow.

Data for the above command is under `CrockerGUI/data/bo-test/`:
- `crocker_pipeline.sqlite3`: telemetry `readings` / `readings_readable`.
- `crocker_pid.sqlite3`: `pid_samples_readable`, `pid_trials`, `pid_events_readable`, and `pid_sessions_readable`.

The existing default PID database is separate; it will not show these runs.

## Verified

- OctoberPIDTest.py: 14 passed; replay against the October source, native/Python parity, both plant directions, feedback averaging, October fitness parity.
- CppNLAPIDIntegrationTest.py: 8 passed; seven actual BO trials, live service, held-output stop, interlock handling and validation-start behavior.
- PythonBOMetricsTest.py: 8 passed; Python-only seven-trial BO, shared scoring, response metrics and model availability.
- BOHistoryTest.py: 4 passed; trial IDs, history filtering and precise CSV/SQLite persistence.
- GainValidationTest.py: 4 passed; too-short validation rejection, target/gain precision, October scoring behavior and the new BO duration preflight.
- PidControlPageTest.py: passed; simulator moves toward setpoint and UI trial workflow completes.
- BOReadinessTest.py: passed; full first-order plant -> local ZeroMQ -> GUI beam calibration -> native October PID -> BoTorch -> recording and shutdown.

The retained BO smoke-test output is `CrockerGUI/logs/bo-readiness/20261014-215502-a23ef522/`: `report.json`, telemetry database and PID database. Seven trials and 176 PID samples were read back. A genuine model-based proposal was reached. Validation was started and cancelled; this test did not claim validated gains. It used two-second trials and reduced acquisition sampling/restarts to keep the smoke test short.

## Findings and fixes

A 0.5-second trial with a 0.3-second feedback average can produce too few samples for scoring. BO now rejects trial durations shorter than three feedback windows (minimum 0.5 seconds) before starting, with a message explaining how to fix the settings. Telemetry loss or slow GUI sampling can still prevent enough scored samples; the guard is a minimum setup check, not a guarantee.

Some regression assertions still expected the superseded cost profiles, two-page layout and early oscillation rejection. Updated them to the independently parity-tested October objective and current UI, and gave the Python BO integration trial enough feedback windows. The production objective was not changed.

October fitness scores oscillation and settling behavior; it does not add hard diagnostic rejection thresholds. Full-duration validation checks completion and trial validity, and cruise mode additionally compares against its measured baseline. A pass is not a separate stability certificate. Trial cost reductions in the short smoke test do not prove convergence: the plant state carries between candidates, so gain quality needs a longer, repeatable validation experiment.

Repeat the retained proof:

```powershell
python CrockerGUI/tests/BOReadinessTest.py -v
```


## First-order simulator range update (October 15)

The first-order plant now starts at zero and uses a synthetic gain of 0.016 nA/A
with a 2-second time constant: 3 nA corresponds to 187.5 A, below the unchanged
250 A output cap. It uses `config/first_order_beam_cal.json`, a simulation-only
0–5 nA calibration, including a true zero point. Hardware and other simulation
modes continue to use `config/beam_cal.json`.

The first-order manual PID preset is Kp=15, Ki=0, Kd=0, deadband 0.05 nA. BO
search bounds remain 0–1 for each gain. These are synthetic simulation settings,
not calibrated machine parameters. Earlier readiness recordings used the older
plant coefficient and calibration and remain historical evidence only.

Reproduce the 45-second 0-to-3 nA step and SQLite checks with:
`python CrockerGUI/tests/BeamStepThreeNanoampTest.py -v`.


## Stop and restart

An explicit Run now enables the selected output and waits for fresh readback
before capturing a new trial reference. Previously Stop disabled the output and
the next reference capture failed, so a new session could not start. Hardware
starts still require explicit arming, connected fresh telemetry, valid beam
feedback, and no fault/interlock. Candidate generation alone does not enable
outputs. Stop cancels a pending enable and stale callbacks cannot start a trial.

Regression: `python CrockerGUI/tests/BORestartTest.py -v` covers repeated BO
start/stop cycles, top-level Stop control, and stopping during output enable.
The full BOReadinessTest also stops and restarts three times before completing
its seven-trial recorded session.


Restart fix verification retained at
`logs/bo-readiness/20261015-192113-2e62443b/report.json`: three interrupted
sessions followed by seven completed trials, 414 recorded PID samples, an actual
BoTorch model proposal and successful validation start/cancel. All writer error,
rejected-record and pending-record checks passed.
