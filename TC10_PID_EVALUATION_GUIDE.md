# TC10 PID evaluation workflow

This guide describes the current CrockerGUI response recorder and tuning metrics. Your setup is **CrockerGUI → ZMQ → LabVIEW simulated hardware → measured-current feedback**. Results characterize that simulation and controller together; they do not yet establish real-coil performance. TC10 is stored as channel **9** because channel numbering starts at zero.

## 1. What you are evaluating

There are two separate questions:

- **Tuning:** Which Kp, Ki, and Kd values should we use?
- **Evaluation:** With those gains fixed, how well does TC10 respond to a repeatable target change?

The controller repeatedly reads measured current, computes error (`setpoint − measurement`), and updates the command. LabVIEW determines how the simulated current responds. The recorder observes the resulting response.

For NLA, the output is a **signed command increment**, not an absolute current target. It uses absolute error, an adaptive movement direction, a moving integral window, and derivative damping. Gains stay fixed during an ordinary run; adapting direction does not mean automatically tuning gains.

## 2. Repeatable evaluation procedure

1. **Choose TC10 and verify the feedback source.** Record that this is LabVIEW simulated hardware, along with the simulation settings/version. The saved `backend: zmq` alone does not identify the simulated plant.
2. **Choose the test before choosing the winner.** For example, use the same 100 → 300 A upward step and a separate 300 → 100 A downward step for each candidate. These are examples from your session, not universal operating limits.
3. **Keep conditions fixed.** Use the same initial current and command, controller kind, deadband, direction settings, integral memory, command bounds, slew limits, sampling setup, and recording duration. Reset controller state consistently and allow the starting condition to stabilize.
4. **Select the method label and recording duration.** A 60-second window measures longer-term behavior that a short tuning trial may miss. The method dropdown is a label for the record; selecting “Ziegler–Nichols” or “Bayesian optimization” there does not run that method.
5. **Apply the test gains and make the setpoint change.** Enabling PID starts recording. Changing setpoint or controller settings while PID is enabled causes a new recording interval. Avoid further edits during the test.
6. **Observe the complete window.** Watch measured current and the metrics. A fast first arrival is only one part of performance; look for later drift, overshoot, and repeated swings.
7. **Open Run History / CSV.** Check the end reason and settings, then inspect the raw response. Recording ends independently of control: PID continues after the recording window finishes.
8. **Repeat each condition**, preferably at least three times, and compare typical results and variation. Test both step directions. NLA’s initial direction can affect downward-step performance.
9. **Validate the chosen gains in a fresh run.** Use the same evaluation conditions for every tuning method. Do not declare a winner from the optimizer’s best trial alone.

“Record again” starts another observation window without creating a target change. If current already equals the target, that is a holding/steady-state test, not a step-response speed test.

## 3. What to read in the CSV and JSON

Response recordings are saved in `CrockerGUI/logs/pid_runs/`. Each run normally has a CSV and JSON with the same filename stem.

### Response CSV: the actual time series

| Column | Meaning | What to inspect |
|---|---|---|
| `elapsed_seconds` | Seconds since the recording began | First-sample delay, total coverage, and unusually large sampling gaps |
| `measurement` | Measured TC10 current in A | Initial current, approach to target, peak, drift, and repeated swings |
| `error` | Setpoint minus measured current in A | Positive means below target; negative means above target |

For example, at a 300 A setpoint:

```csv
elapsed_seconds,measurement,error
0.10,103.68,196.32
2.85,297.25,2.75
```

These rounded example rows show a substantial response over time. The second row enters the ±3 A metric band; that row alone does not prove settling.

In a spreadsheet, make an **XY scatter plot with lines**, using elapsed time as X and measurement as Y. Add horizontal lines at the target and tolerance limits. A second plot of error against time makes small deviations easier to see. Preserve the original CSV.

### Companion JSON: the context and final results

Read these before comparing two CSVs:

| Fields | Why they matter |
|---|---|
| `channel`, `controller_kind`, `backend`, `simulation_mode` | Identify the channel/controller and recorded backend configuration; simulation metadata may be incomplete |
| `setpoint`, `kp`, `ki`, `kd` | Identify the actual test settings |
| `nla_deadband`, direction/window settings, integral memory, output limit | These also change the response, even with identical gains |
| `dry_run`, output bounds | Check whether the record represents the intended command path and limits |
| `method` | User-selected label; not proof that the named tuning procedure was executed |
| `reason`, `duration_seconds`, `sample_count` | Check completion, early stop, and data coverage |
| `metrics` | Final calculated results, including Boolean flags and tolerance |

A JSON marked **“Recording / incomplete”** is not a finalized result. Inspect its CSV, but do not treat it as a completed evaluation. Record initial conditions and simulation details separately when the JSON does not capture them.

The response CSV does **not** contain actuator commands or P/I/D contributions. Separate command logs, when produced, serve that purpose. Do not infer command effort from the three-column response CSV.

## 4. Metric definitions and how to judge them

The metric tolerance is:

```text
tolerance = max(0.1 A, 1% × max(abs(target), 1 A), configured deadband)
```

At **300 A**, this is **±3 A**, so the metric band is **297–303 A**. At **100 A**, it is **±1 A**. This uses the target magnitude, not the step size.

Your **±0.05 A controller deadband** is separate: NLA stops requesting movement inside that smaller band. “Settled” therefore does not mean “within 0.05 A.”

| Metric | Current calculation | Interpretation |
|---|---|---|
| Transient time | First recorded entry into the tolerance band | Lower is faster. This label means first entry here, not conventional 10–90% rise time. |
| Settling time | First sample after the last out-of-band sample, provided at least 0.5 seconds remain in-band through the recording end | Lower is faster, but only when `settled` is true. Live results can change. |
| Steady error | Time-weighted mean **absolute** error over the final 20% of sampled duration | Lower means better final accuracy; opposite errors cannot cancel. |
| RMS error | Time-weighted root-mean-square error over the same final 20% | Lower is better; large deviations contribute more strongly. |
| Overshoot | Largest excursion beyond target in the step direction, across the recording | In A, not percent. For a downward step, measures excursion below target. |
| Oscillation amplitude | Half the largest of up to four recent completed detected swings, once enough swings exist | Approximate recent oscillation size, not a full signal-analysis measurement. |

For a roughly 60-second sampled interval, steady error and RMS describe the last roughly 12 seconds. These values do not summarize the initial step.

### True/False fields

| Field | True means | Usually desired |
|---|---|---|
| `entered_tolerance` | Reached the band at least once | **True** |
| `settled` | Stayed in-band through the end for at least 0.5 seconds | **True** |
| `sustained_oscillation` | Enough substantial swings were detected and recent swings did not shrink sufficiently | **False** |

The oscillation detector requires reversals greater than **twice the tolerance**. At 300 A, that threshold is **6 A**. It marks oscillation as sustained when at least four qualifying completed swings exist and the sum of the latest two is at least 80% of the preceding two.

Consequently, `sustained_oscillation: false` means **no sustained pattern was detected**, not “there is no fluctuation.” Small or fast oscillations can be missed. Recording uses fresh telemetry at nominally about **8 Hz**, not necessarily every control update.

## 5. Tuning methods

### Manual / baseline

Use an existing gain set as the reference, then make controlled gain changes and repeat the same test. Record each candidate. This is easy to interpret, but can take many trials and depends on the operator’s choices.

For NLA, Kp scales error-based movement, Ki adds recent error memory, and Kd damps movement as error magnitude falls. Their behavior is not identical to a conventional signed-error PID.

### Ziegler–Nichols (ZN): what “Ziegler” means

Ziegler–Nichols is a classical rule for obtaining initial PID settings from a measured plant response. One version uses a step-response model; the familiar closed-loop version identifies an **ultimate gain Ku** and **oscillation period Pu** under proportional-only conventional control. Those measurements are converted into starting gains. See [NI’s PID explanation](https://www.ni.com/en/shop/labview/pid-theory-explained.html).

For the classic closed-loop PID rule:

```text
Kp = 0.6 × Ku
Ti = Pu / 2
Td = Pu / 8

For parallel PID form:
Ki = Kp / Ti
Kd = Kp × Td
```

**These are conventional-PID formulas, not a validated tuning rule for this NLA controller.** NLA uses absolute error, adaptive direction, and time-scaled command increments. Do not paste ZN gains into NLA and assume equivalent behavior. A valid comparison must identify the controller form and any justified conversion. The closed-loop identification experiment deliberately seeks oscillation; use a controlled simulation procedure rather than treating it as an ordinary live evaluation step.

The recording dropdown currently supplies a ZN label; it is not a ZN autotuner.

### Random search

Choose gain combinations randomly within fixed bounds, run each trial, score it, and keep the best. It does not learn where good gains are likely to be. It provides a useful search baseline when compared with BO using equal bounds, trial counts, durations, and starting conditions. The recording dropdown alone does not launch random search.

### Bayesian optimization (BO)

BO learns a probabilistic approximation of how gains affect the trial score. It uses that model to propose another gain set, balancing promising regions with uncertainty. After measuring the next trial, it updates the model and repeats. This project has a BoTorch-backed optimizer. See [BoTorch’s model documentation](https://botorch.org/docs/models) and [BoTorch overview](https://botorch.org/).

Conceptually:

```text
Set gain bounds and trial budget
    → propose gains
    → run a trial
    → calculate metrics and score
    → update optimizer observations
    → propose the next gains
    → validate the selected gains independently
```

BO optimizes the score it is given. It does not prove stability or guarantee the globally best gains. Good performance in a short trial can still hide later oscillation or drift.

## 6. How the current BO score works

Lower score is better. The shared scoring function uses:

```text
score = time_weight × (settling_time + 0.25 × transient_time)
      + precision_weight × steady_error
      + effort_weight × control_effort
      + oscillation_weight × oscillation_penalty
      + 25 if not settled
```

The final `+25` applies only to an unsettled trial. When the target was never reached or never settled, the corresponding numeric time falls back to the recording end; always read the Boolean flags with the times.

| Profile | Change from Balanced |
|---|---|
| Balanced | Time 1; precision 4; effort 0.01; oscillation 1 |
| Fast response | Time weight becomes 3 |
| High precision | Precision weight becomes 8 |
| Low control effort | Effort weight becomes 0.08 |
| Suppress oscillation | Oscillation weight becomes 2 |

The oscillation penalty grows with detected cycles and amplitude relative to tolerance, with an additional penalty for sustained oscillation. **Overshoot and RMS are diagnostic metrics, not direct terms in this score.** Trial abort limits may separately reject a response. The ordinary response recorder does not measure command effort or publish a BO score.

## 7. Comparison worksheet

Use one row per repeat; do not combine different targets or test directions into an unlabeled average.

| Method | Controller | Repeat | Start → target (A) | Kp / Ki / Kd | Window (s) | Settled? | Settling (s) | Steady error (A) | RMS (A) | Overshoot (A) | Sustained oscillation? | Run filename |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Manual baseline | NLA | 1 | 100 → 300 | | 60 | | | | | | | |
| BO | NLA | 1 | 100 → 300 | | 60 | | | | | | | |

Choose an acceptable response based on your accuracy, overshoot, and oscillation requirements first, then compare speed among acceptable candidates. A 3-second arrival is not automatically better than a 4-second response if it later drifts or oscillates.

## 8. Implementation references

- `CrockerGUI/source/Python/Optimization/trial_metrics.py`: metric definitions and score.
- `CrockerGUI/python/app/Automation/RunMetrics.py`: recording, display, CSV/JSON output.
- `CrockerGUI/python/app/Automation/PidControlPage.py`: recording triggers and tuner controls.
- `CrockerGUI/source/Python/Control/NLAPID.py`: NLA reference algorithm.

These descriptions reflect the code reviewed for this guide; metric definitions should be checked again if the implementation changes.
