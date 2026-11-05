# Direct trim-coil Bayesian optimization

## Run it

In the existing application, open **Automation → Trim-coil BO**, choose a trial
budget and seed, then select **Start simulation**. The workspace displays a
synthetic two-coil plant; it never connects to the cyclotron. Fitting runs in a
separate process so the page stays responsive. Abort requests stop proposals and
verify reference restoration before the process exits. A fit already in progress
finishes before the request is processed; no subsequent candidate is applied.

From `CrockerGUI/`, using the project's Python environment:

```powershell
python -m source.Python.Automation.trim_coil_simulator --trials 10 --seed 1729 --output logs/my_trim_coil_run.json
```

The output must be a new filename. Each GUI run uses a unique JSON filename in
`CrockerGUI/logs/`. Logs include configuration, bounds, seed, applied settings,
raw samples/readbacks, window statistics, confirmation decisions and stop/recovery
outcomes. The summary distinguishes candidate trials from total measurement windows.
Elapsed session time in the simulator is accelerated plant time, not fitting time.

## Session reference and dashboard

The simulator captures its existing targets and readbacks before starting the
session. No run sheet is loaded. Repeated baseline windows establish starting
beam; the captured target vector remains the recovery destination while the
confirmed incumbent can improve. The synthetic plant still starts at its fixture
settings; this is not a connection to the live machine.

The MISO dashboard shows numbered coil cards with current readback, fixed
reference target, captured starting readback, commanded target and settling status.
It shows measured beam, confirmed gain, latest measured cost (`-mean_beam_nA`),
candidate budget, total acquisition windows and initialization progress. Cost history
includes all windows; confirmed-best and reference layers remain separate. Parallel
coordinates show all supplied coil dimensions scaled to local bounds and colored
by measured beam. The current fixture supplies two channels, not ten live channels.

## What runs today

The default **Trim coils + beam** view plots beam current and TC1/TC2 currents
against the same simulation-time axis. Solid current traces are actual readbacks;
dashed traces are commanded targets. Telemetry includes settling and reference
returns, and is saved in the audit log alongside acquisition windows.

The workspace also includes **Beam progress**, **Coil search**, **Confirmations**, and
**Measurements** tabs. Toggle the reference, confirmed-best, variability and
candidate-path layers above the plots. Hover over points for measurement details.
Beam error bars show ±1 within-window standard deviation, not uncertainty of the
mean. The coil map colors measured points by beam; it does not interpolate a GP
surface. Confirmation plots display the mean paired gain and its configured
one-sided lower bound against the minimum useful gain threshold.

- Local Sobol initialization, explicitly seeded with repeated reference windows.
  Distinct settings, rather than repeat count, determine when GP fitting begins.
- Sequential `SingleTaskGP` plus qLogNEI. Means are learned with inferred noise;
  the optimizer also accepts reliable per-window `mean_variance_nA2` metadata.
  If any observation lacks that metadata, it infers noise for the entire dataset.
- Fixed session reference and separate confirmed incumbent. All settings return
  to the reference after each window, including confirmation windows.
- Stable readback hold followed by a separate beam measurement window. Held or
  stale packets do not accumulate acquisition samples. Unstable/invalid windows
  stop the session without fabricating objective observations.
- Three interleaved incumbent/candidate confirmation pairs by default. Promotion
  requires mean paired gain minus a configured uncertainty multiplier times its
  standard error to exceed the minimum useful gain. These are independent
  synthetic windows; applying the procedure to machine data requires correlation
  and distribution checks. The multiplier is not advertised as a calibrated
  confidence level or a sequential-testing guarantee.
- Periodic drift checks, final incumbent/reference remeasurement, ownership,
  abort, partial-write detection, timeout handling and stopped/blocked recovery.
- Synthetic defaults: two coils within ±0.5 A, approximately 10 nA baseline,
  0.1 nA minimum useful gain. All numerical defaults are simulation settings,
  not recommended machine operating values.

The GP does not learn a safety boundary from excluded failures. The coordinator
stops after an invalid experiment and recovery. Existing PID BO remains separate.

## Measured-reference records

`ReferenceStore()` resolves the repository `reference_values/` directory from its
module location, independently of the working directory. Packaged runs can use
`ReferenceStore(explicit_directory)`. Store each measured record as `<reference_id>.json`.
`load(id, expected_configuration=...)` requires an exact configuration match;
`list_ids()` lists only valid records whose filenames match their IDs.

Required schema (the numbers below are synthetic examples, not machine data):

```json
{
  "schema_version": 1,
  "record_type": "measured_reference",
  "reference_id": "synthetic-example",
  "captured_at": "2026-01-01T00:00:00+00:00",
  "operator": "simulator",
  "source_dataset": "synthetic",
  "machine_configuration": {"mode": "simulation", "species": "synthetic"},
  "coils": [
    {"channel": "TC1", "unit": "A", "target": 0, "readback": 0}
  ],
  "beam": {
    "diagnostic": "synthetic-output",
    "unit": "nA",
    "mean": 10,
    "stddev": 0.02,
    "sample_count": 20,
    "window_s": 2
  }
}
```

The loader rejects unsupported schemas, duplicate JSON keys/channels, invalid
units, missing values, nonfinite numbers and incompatible configurations.
It can convert a record to `RecoveryReference` using an explicit channel-index
mapping. Loading does not make a record live-verified or authorize hardware use.
Historical run-sheet extracts remain historical: their unknown units and missing
beam measurements are not converted into executable references.

## Validation

From the repository root:

```powershell
python CrockerGUI/tests/TrimCoilBOTest.py
python CrockerGUI/tests/TrimCoilBOPageTest.py
```

The backend suite exercises references, actual qLogNEI proposals, confirmation,
objective sign, bounds, ownership, abort during fitting, stale/held telemetry,
configuration changes, diagnostic failure, loss, partial writes, settling timeout,
time budget and recovery. The offscreen GUI tests exercise the real child process,
trial display, audit export and graceful abort.

## Remaining before machine use

The current workspace deliberately runs the fixed synthetic fixture. Real-reference
selection, configurable coil subsets/bounds and measurement controls, apply-best
execution and saving improved measured records still need GUI integration.
Time-aware modeling and multi-seed comparisons against equal-budget random search
also remain to be implemented before claiming experimental performance.

There is no direct-coil ControlService adapter. `TrimCoilSession` rejects backends
whose mode is not simulation. Joint-coil limit/transition validation and recovery
must be integrated and reviewed before that restriction is changed. The existing
single-coil `FailureRecovery` is not used as though it supported multiple coils;
the simulator uses its own validated whole-vector command path and readback/beam
verification. No disabled output is enabled by this workflow.
