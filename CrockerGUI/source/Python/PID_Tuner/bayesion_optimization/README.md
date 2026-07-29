# Safe Bayesian Optimizer

This directory is intended to hold the safe Bayesian Optimization layer for PID tuning and related automated tuning experiments.

The long-term goal is a Torch/BoTorch-based optimizer that proposes PID gain candidates, such as `Kp`, `Ki`, and `Kd`, then evaluates them using measured closed-loop response quality. Candidate trials should be scored from metrics such as settling time, overshoot, steady-state error, control effort, and any safety violations.

The optimizer should never command hardware directly. Its role is to propose and record trials. The GUI and control layer must remain responsible for arming, dry-run behavior, operator approval, command bounds, max-step limits, interlock/fault checks, observation windows, and emergency stop behavior.

Current status: `trial_suggestion.py` contains an assisted trial suggester, not a real Torch/BoTorch Bayesian optimizer. It is a conservative scaffold used by the Automation assisted tuning page to suggest bounded one-at-a-time command trials, record scores, and log results while the actual safe BO PID tuner is still being designed.

`bayesian_optimization.py` is reserved for the real Torch/BoTorch PID gain optimizer. That implementation should propose batches of `Kp`, `Ki`, and `Kd` candidates, consume scored PID response trials, and use a BoTorch acquisition function to select the next batch.

Note: this scaffold may be removed later once the real safe Bayesian Optimization PID tuner is implemented.
