# MISO Bayesian optimization of trim-coil currents

**Status:** simulation implementation available. No joint-coil hardware adapter is enabled.

Implemented: strict measured-reference loading, sequential qLogNEI optimizer,
poll-driven trial/confirmation/recovery coordinator, coupled-coil simulator, JSON
audit logs, and an Automation → Trim-coil BO simulation workspace. Existing PID
optimization defaults are unchanged. See [usage and remaining work](MISO_TRIM_COIL_BO_USAGE.md).

The sections below describe the target design; the component table records the
original starting point. Hardware integration, operational configuration controls,
and time-aware BO remain future work.

## Recommendation

Use sequential, local Bayesian optimization (BO) to maximize measured output beam
current by adjusting a small operator-selected subset of trim coils together.
Start from a verified beam-producing reference, evaluate one candidate at a time,
and accept a new best setting only after repeated measurements confirm improvement.

Your **propose → apply → settle → measure → learn → keep or restore** algorithm is
a sound foundation. The main additions are noise-aware candidate selection,
explicit confirmation of improvements, a consistent return protocol, and drift checks.

Here, **MISO means multiple-input, single-output**: coil currents are the inputs
and one beam-current metric is the output. It does not mean multi-information-source BO.

## 1. Objective and scope

```text
x = [I_1, ..., I_d]                      selected coil-current targets, A
measurement = f(x, time) + noise         measured output beam current, nA
goal = maximize expected output beam within permitted operating conditions
existing optimizer cost = -mean_beam_nA
```

The training code negates this cost internally for BoTorch maximization. Do not
negate it twice. Optimize coil-current targets, not PID gains; existing current
regulation and LabVIEW ramping remain responsible for reaching targets.

Trim-coil changes modify the spatial magnetic field and can affect transport and
extraction. The GP learns beam response to coil combinations, including interactions.
It does not reconstruct the magnetic field or particle trajectories, and a finite
trial budget does not guarantee the global optimum.

**More output beam is the initial success metric.** It does not alone prove better
transmission efficiency or less beam striking the machine. Transmission efficiency
requires compatible input and output measurements, such as output/input current;
loss reduction requires suitable loss measurements. Keep loss limits as explicit
constraints. Hold other machine settings fixed and record them so source changes
are not mistaken for trim-coil improvements.

## 2. Proposed model and acquisition algorithm

1. Select a small coil subset and define local offsets around the verified
   reference, intersected with permitted channel limits. Keep the search bounds
   fixed during the initial session. Check joint settings and transitions too:
   a rectangular box alone does not establish physical feasibility.
2. Measure the reference repeatedly to characterize noise. Include it explicitly
   in training, then collect a budgeted local Sobol initialization design. Repeated
   baseline windows estimate noise but do not replace distinct spatial samples.
   Configure initialization for dimension and budget; do not use full hardware ranges.
3. Fit a single-output Gaussian process with normalized current inputs and
   standardized beam output. Start with the existing stationary `SingleTaskGP`
   during a short, stable session. Benchmark kernel changes in simulation rather
   than assuming a particular kernel is already configured.
4. **Proposed acquisition: qLogNoisyExpectedImprovement (qLogNEI), with q = 1.**
   Unlike taking the largest noisy measurement as an exact incumbent value, it
   accounts for uncertainty in baseline observations. Pass evaluated input locations
   as `X_baseline`. This requires an implementation change: current code uses qLogEI.
5. Optimize acquisition within the local domain and known joint constraints,
   validate the resulting vector and transition, then run one experiment.
   Record its result before proposing again. A poor but valid measurement still
   teaches the GP and must remain in training.

An acquisition score permits an experiment; it neither certifies physical safety
nor proves improvement. Avoid blindly executing a precomputed batch on the machine.

Record variability, sample count, timestamps, and uncertainty of each window mean.
If reliable mean variances are available, add `train_Yvar` support. Otherwise infer
observation noise and retain repeats. Raw sample variance is not variance of the
mean; correlated telemetry can also make variance/sample-count underestimate
uncertainty. Use independent repeat windows or a justified correlation-aware estimate.

## 3. Reference, best setting, and confirmation

| Setting | Meaning |
| --- | --- |
| Session reference | Fixed operating point verified at startup; recovery destination. |
| Incumbent | Best setting supported by confirmation measurements in this session. |
| Candidate | Proposed setting awaiting evaluation or confirmation. |

Require fresh readbacks within target tolerance for a configured stable hold,
then acquire a separate beam window. Validate diagnostic status, saturation,
polarity, units, and beam stability, with timeouts. Use an explicit physical sign
convention; do not silently take an absolute value. Invalid windows are not objective data.

A single larger measurement does not establish improvement. For a promising
candidate, perform a budgeted comparison with recent incumbent measurements using
comparable windows and the same transition protocol. Interleave repeats where
practical to reduce drift bias. Define the promotion rule before the session:

```text
estimated_gain = candidate_mean - incumbent_mean
promote only if lower_confidence_bound(estimated_gain) > minimum_useful_gain
```

Choose repeat count, uncertainty procedure, confidence level, and useful gain from
diagnostic characterization and operational needs. Account for correlation.
Use a fixed confirmation budget rather than retesting until a lucky result passes;
repeated promotions also require care in interpreting confidence. An inconclusive
comparison leaves the incumbent unchanged. Prediction alone never promotes it.

## 4. Experiment loop

For initial simulation and commissioning, use **reference → candidate → reference**
for every evaluation, including confirmation. Apply the same protocol to incumbent
remeasurements. This resolves the original conflict between returning to the best
setting and returning to baseline. It costs ramp time and does not guarantee removal
of hysteresis. Validate that tradeoff before adopting candidate-to-candidate operation.

```text
START
  validate reference, configuration, diagnostic, limits, and budgets
  acquire exclusive control ownership
  restore and verify reference; measure repeated baseline windows
  incumbent = reference

REPEAT while budget remains and no stop is requested
  choose initialization point, or fit GP and propose one BO candidate
  validate whole vector and transition before writing
  apply through existing command path and LabVIEW ramp
  wait for settling; collect and validate beam window
  record valid observation for model training
  restore and verify reference
  if candidate is promising and confirmation budget remains:
    compare candidate and incumbent with repeated measurements
    record all valid measurements; promote only if confirmation passes
  perform scheduled reference/drift check

FINISH
  remeasure incumbent and reference if budget permits
  report confirmed gain, uncertainty, measurement count, and elapsed time
  restore and verify reference by default
  offer explicit apply-best action; verify it if selected
```

Reserve budget for returns, confirmations, drift checks, and final verification.
Stop on trial/time budget, operator stop, invalid measurement, material configuration
or drift change, or execution failure. Optional stagnation stopping needs a predefined
rule based on confirmed gains; a small acquisition value alone does not prove convergence.

### Failure and abort

- Reject invalid proposals before application; never silently clip them.
- Check intermediate states and detect rejected or partially applied writes.
  Valid endpoints alone do not establish a valid sequential transition.
- On beam loss, stale telemetry, settling timeout, or execution failure, stop trials
  and invoke the existing stop/recovery policy when permitted.
- Recover to the session reference through the recovery coordinator; verify
  readbacks and beam. Blocked or timed-out recovery leaves optimization stopped.
- Log failures without inventing objective values. Excluding failed trials does
  not teach the GP a feasibility boundary. Do not automatically restart after recovery.
- Abort cancels outstanding trial work and stops new optimization writes without
  competing recovery writers. PID tuning and other automation cannot share coil ownership.

The GP is not an interlock. Existing limits and interlocks remain authoritative.

## 5. Drift and time-aware BO

Record timestamps and periodically remeasure the reference in every mode. Compare
promising candidates with recent incumbent measurements. If reference changes
exceed a predefined drift tolerance, stop and revalidate the session.

Start with standard BO. Add time-aware BO only when repeated measurements show drift
that matters over the run duration. Possible extensions include spatial/temporal
covariance or a validated forgetting/reset strategy. Adding timestamps alone does
not implement forgetting. Predict at expected measurement time; time is context,
not a parameter the optimizer chooses. Drift modeling does not replace settling checks.

## 6. Existing implementation and gaps

Paths below are relative to `CrockerGUI/`, except `../reference_values/`.

| Component | Existing capability | Required work |
| --- | --- | --- |
| `source/Python/Optimization/bayesian_optimizer.py` | Named bounds, Sobol initialization, GP proposals, history | Coil adapter, explicit reference seeding, distinct-point initialization policy |
| `source/Python/Optimization/training.py` | Cost negated to maximization objective | Optional per-window mean variance |
| `source/Python/Optimization/surrogate_model.py` | SingleTaskGP, normalization, standardization | Optional train_Yvar; drift model later if justified |
| `source/Python/Optimization/acquisition.py` | qLogEI with largest observed objective as best_f | qLogNEI path for noisy beam trials |
| `source/Python/Automation/reference_recovery.py` | Pure restoration planner with target/readback, beam, stable-hold, timeout checks | Session-reference integration |
| `source/Python/Automation/failure_recovery.py` | Recovery coordinator | Trial stop/abort/recovery integration |
| `source/Python/Automation/hardware_profile.py` | Operating-limit checks | Joint-coil integration review; operator-limits approval currently restricts allocation to a single trim-coil identity |
| `../reference_values/` | Documentation only, no measured records or loader | Versioned data and shared validated loader |

The name `safe_observations` is a software filter, not physical certification.
The optimizer's default initialization count is not a validated experimental design
for an arbitrary number of coils. Direct multi-coil execution is not ready merely
because the optimizer accepts multiple parameters.

### Reference records and audit data

Add `reference_store.py` under `source/Python/Automation/`, loading by explicit ID.
Resolve shared data relative to application paths, with an explicit packaged-run
override, rather than the shell working directory.

Records need schema version, stable ID, capture time, operator/source, machine
configuration, named coil targets/readbacks in A, diagnostic identity, beam current
in nA, acquisition protocol, and variability. Keep limit-profile identity separate
from the reference. Reject placeholders, missing/nonfinite data, duplicate channels,
unsupported schemas/units, and incompatible configurations.

Revalidate references live at startup. Historical measurements enter training only
when configuration and acquisition are compatible. Preserve original captures;
save accepted improvements as new reference records.

Log targets, actual readbacks, timestamps, raw windows or durable links, beam
statistics, mean uncertainty, score, outcome/reason, configuration, limit-profile
identity, model settings, random seed, and incumbent changes.

## 7. Implementation order and acceptance

1. **Reference store and pure adapter:** validate ID loading independent of working
   directory, units, channel mapping, bounds, objective sign, and invalid data rejection.
2. **Noise-aware optimizer:** add qLogNEI and optional observation variance; check noisy
   repeats and objective sign. Preserve PID optimization behavior unless separately validated.
3. **Fake-backend trial coordinator:** verify ownership, partial writes, stale telemetry,
   settling/acquisition timeouts, loss, abort, returns, confirmation, and blocked recovery.
4. **Coupled-coil simulation:** include noise, drift, hysteresis, and injected failures.
   Compare with unchanged-reference operation and bounded random search using equal total
   measurement/time budgets, including returns and confirmation. Across multiple seeds,
   report confirmed gain, false promotions, failures, and elapsed-time distributions.
5. **GUI:** show reference, selected coils/bounds, diagnostic, budgets, trial table,
   incumbent and uncertainty, drift checks, and recovery state. Keep it distinct from PID BO.
6. **Hardware commissioning:** review joint-coil limits/transitions, verify units,
   characterize settling/noise, and begin locally under existing hardware authorization.

## 8. Configuration needed before hardware use

- First coil subset, beam diagnostic, and machine-configuration identity.
- Verified reference and permitted joint-setting/transition domain.
- Readback tolerance, settling hold, acquisition window, diagnostic-validity rules, timeouts.
- Loss criteria, recovery policy, drift tolerance, and check cadence.
- Initialization, confirmation, final verification, and total trial/time budgets.
- Minimum useful gain and the uncertainty/confirmation procedure.

No operating currents, timing values, or loss thresholds are prescribed here.
They must come from measured machine behavior and the applicable limit profile.

## Sources

The repository plan and code are the basis of this review. External sources support
BO design choices, not cyclotron operating limits or application performance guarantees.

- [BoTorch closed-loop qLogEI/qLogNEI tutorial](https://botorch.org/docs/v0.17.2/tutorials/closed_loop_botorch_only): noisy/constrained BO and observation variances.
- [BoTorch getting started](https://botorch.org/docs/getting_started): GP fitting, acquisition, and candidate selection.
- [Bogunovic, Scarlett, and Cevher (2016), Time-Varying Gaussian Process Bandit Optimization](https://proceedings.mlr.press/v51/bogunovic16.html): resetting and gradual forgetting with GP-UCB; background for a later drift extension, not the exact qLogNEI algorithm proposed here.
