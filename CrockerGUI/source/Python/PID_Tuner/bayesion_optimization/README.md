# Safe Bayesian Optimizer

This directory is intended to hold the safe Bayesian Optimization layer for PID tuning and related automated tuning experiments.

The long-term goal is a Torch/BoTorch-based optimizer that proposes PID gain candidates, such as `Kp`, `Ki`, and `Kd`, then evaluates them using measured closed-loop response quality. Candidate trials should be scored from metrics such as settling time, overshoot, steady-state error, control effort, and any safety violations.

The optimizer should never command hardware directly. Its role is to propose and record trials. The GUI and control layer must remain responsible for arming, dry-run behavior, operator approval, command bounds, max-step limits, interlock/fault checks, observation windows, and emergency stop behavior.

Current status: the AI Control section exposes only the operational PID Control
page. The previous assisted/BO tuning and exploration pages were removed while
their workflow is reconsidered. The optimizer code in this directory is not
connected to the frontend or normal PID operation.

`bayesian_optimization.py` implements the Torch/BoTorch PID gain optimizer. It
starts with reproducible, space-filling Sobol candidates and, after enough safe
trials, fits a `SingleTaskGP` and proposes batches with
`qLogExpectedImprovement`. Trial scores are costs (lower is better), so the GP
models their negative. Unsafe trials remain in the audit history but are not
used to teach the performance model.

Typical outer loop:

```python
optimizer = BotorchPidOptimizer((0, 5), (0, 2), (0, 1))
for candidate in optimizer.propose_batch(4):
    # Apply candidate gains through the control layer, run the closed-loop
    # observation window, calculate response metrics, and enforce interlocks.
    optimizer.record_results([measured_trial_result])
```

The score supplied in `PidTrialResult` should combine the metrics appropriate
for the machine, for example weighted settling time, overshoot, steady-state
error, and control effort. Keep the units normalized before combining them.

Run `python CrockerGUI/tests/BotorchPidOptimizerTest.py` from the repository root
for a CPU smoke test of both the Sobol and GP/qLogEI proposal paths.
