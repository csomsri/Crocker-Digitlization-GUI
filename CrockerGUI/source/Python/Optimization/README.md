# Standalone Bayesian Optimization

This package holds the reusable Bayesian optimization layer. It is intentionally
separate from PID control, the GUI, and hardware execution.

The optimizer only owns three things:

- the named bounded parameter space,
- proposal generation,
- scored observation history.

The caller owns the experiment. For PID tuning, that means the PID page and
control service still own arming, interlocks, command limits, dry-run behavior,
trial execution, and response scoring.

## Code Map

| File | Responsibility |
| --- | --- |
| `parameter_space.py` | Defines parameters, candidates, bounds, and candidate validation. |
| `observations.py` | Stores evaluated experiments and separates safe observations from audit history. |
| `training.py` | Turns safe observations into `train_x` and `train_y` tensors. |
| `surrogate_model.py` | Builds and fits the `SingleTaskGP` surrogate model. |
| `acquisition.py` | Builds `qLogExpectedImprovement` and optimizes it for next candidates. |
| `bayesian_optimizer.py` | Orchestrates the full workflow. |

The real-world evaluation is outside this package. The caller proposes a
candidate, runs the experiment, computes a score, and records an observation.

Example:

```python
from source.Python.Optimization import (
    BotorchBayesianOptimizer,
    OptimizationObservation,
)

optimizer = BotorchBayesianOptimizer(
    [
        ("temperature", (20.0, 80.0)),
        ("pressure", (0.5, 4.0)),
    ],
    use_cuda=False,
)

candidate = optimizer.propose_batch(1)[0]

# Run the real experiment somewhere else and calculate a scalar cost.
optimizer.record_observations([
    OptimizationObservation(candidate=candidate, score=12.5, safe=True)
])
```

PID gain tuning now uses this package through a thin adapter in
`source/Python/Optimization/pid_gain_adapter.py`.

## Genetic PID search

`genetic_optimizer.py` provides the bounded, deterministic GA shared by the
C++ and Python GA PID workspaces. It proposes gain candidates and consumes
fitness scores; it never runs PID or writes hardware. Evaluation, recovery and
command integration live in `source/Python/Automation/ga_*.py`. See
`CrockerGUI/GA_INTEGRATION_PROPOSAL.md` for the integration map.

## Hybrid GA / BO PID search

`hybrid_pid_optimizer.py` shares measured GA observations with BO and requires
paired measured improvement before handover. It has no GUI or device access.
The fifth automation page uses the same trial evaluator for both optimizers,
restores a fixed baseline between trials, and validates gains before applying.
See `CrockerGUI/HYBRID_GA_BO_PID.md` for defaults, safety behavior and tests.
