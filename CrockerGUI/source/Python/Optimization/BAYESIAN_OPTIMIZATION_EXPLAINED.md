# Bayesian Optimization Explained

This document explains the standalone Bayesian Optimization layer in
`source/Python/Optimization` and how the PID tuner uses it through an adapter.

The short version:

```text
candidate -> experiment -> score -> observation -> training data
          -> surrogate model -> acquisition function -> next candidate
```

The optimizer does not run hardware, change PID gains directly, or judge machine
safety by itself. It proposes parameter values. The caller runs the experiment,
computes the score, checks safety, and records the result.

## What Bayesian Optimization Is Doing

Bayesian Optimization is used when each experiment is expensive and we cannot
try every possible setting. In this project, a candidate may be a set of PID
gains:

```text
[Kp, Ki, Kd]
```

Each completed trial produces a scalar cost:

```text
score = weighted settling time
      + weighted overshoot
      + weighted steady-state error
      + weighted control effort
```

Lower score is better.

The optimizer learns from completed safe trials and proposes the next candidate
that looks promising. Early on, it explores broadly. Later, it uses a model of
the response surface.

## Current Safety Level

This is currently bounded BO with external safety enforcement, not full Safe BO.

The optimizer enforces parameter bounds and excludes unsafe observations from
model training. The PID/control layer still owns:

- operator arming,
- dry-run behavior,
- command limits,
- hardware profile limits,
- interlocks,
- fault handling,
- trial stop conditions.

Unsafe observations remain in history for audit, but the performance model only
trains on observations marked `safe=True`.

Full Safe BO would add separate learned constraint models, such as:

```text
overshoot(Kp, Ki, Kd) <= max_overshoot
max_error(Kp, Ki, Kd) <= max_error
saturation_time(Kp, Ki, Kd) <= max_saturation_time
```

That is a good future direction, but it is not implemented yet.

## The Model

The current surrogate model is a BoTorch `SingleTaskGP`, defined in:

```text
surrogate_model.py
```

It models one objective:

```text
candidate parameters -> predicted trial quality
```

Because our trial score is a cost, lower is better. BoTorch acquisition
functions maximize objectives, so the training target is:

```text
train_y = -score
```

That turns the best low-cost trial into the largest objective value.

The model uses:

- `SingleTaskGP` for the Gaussian Process surrogate,
- `Normalize` to scale inputs into a stable model space,
- `Standardize` to normalize the objective values,
- `ExactMarginalLogLikelihood` for GP fitting.

Why a GP:

- It works well with small datasets.
- It gives uncertainty estimates.
- It is a strong fit for low-dimensional continuous tuning, such as `Kp/Ki/Kd`.
- It supports acquisition functions that trade off exploration and exploitation.

The same fitted GP can also be evaluated for visualization. The optimizer has a
`surrogate_grid(...)` method that samples the GP posterior over two chosen
parameters while holding the other parameters fixed. For PID tuning, the UI
plots a `Kp`/`Ki` cost slice while holding `Kd` at the best known value.

## Candidate Generation

Candidate generation has two phases.

### Phase 1: Sobol Exploration

Before enough safe observations exist, the optimizer uses Sobol sampling.

Sobol points are quasi-random. They are not normal random noise; they are
designed to cover the bounded search space evenly.

For PID gains, if the bounds are:

```text
Kp: 0 to 5
Ki: 0 to 2
Kd: 0 to 1
```

a Sobol point starts in normalized space:

```text
[0.20, 0.75, 0.40]
```

Then it is scaled into the real bounds:

```text
Kp = 1.0
Ki = 1.5
Kd = 0.4
```

Those candidates become training data only after the experiment is run and a
score is recorded.

### Phase 2: Model-Guided BO

After enough safe observations exist, the optimizer:

1. Builds training tensors from safe observations.
2. Fits the `SingleTaskGP`.
3. Builds a `qLogExpectedImprovement` acquisition function.
4. Optimizes that acquisition function inside the parameter bounds.
5. Returns the next candidate.

`qLogExpectedImprovement` asks:

```text
Where might we improve over the best known safe score?
```

It balances trying promising regions and exploring uncertain regions.

## Component Map

| File | Role |
| --- | --- |
| `parameter_space.py` | Defines the bounded search space and candidate values. |
| `observations.py` | Stores evaluated candidates and separates safe training data from audit history. |
| `training.py` | Converts observations into BoTorch tensors. |
| `surrogate_model.py` | Builds and fits the GP surrogate model. |
| `acquisition.py` | Chooses the next candidates using expected improvement. |
| `bayesian_optimizer.py` | Orchestrates the full BO loop. |
| `pid_gain_adapter.py` | PID-specific adapter around the standalone optimizer. |
| `python/app/Automation/SurrogatePlotWidget.py` | Qt widget that draws the live PID surrogate surface. |

## `parameter_space.py`

This file defines the optimization variables.

Important types:

```python
OptimizationParameter(name="kp", bounds=(0.0, 5.0))
OptimizationCandidate(values={"kp": 1.2, "ki": 0.1, "kd": 0.0})
```

`ParameterSpace` validates:

- every parameter has a non-empty name,
- parameter names are unique,
- bounds are finite and increasing,
- candidate values exist for every required parameter,
- candidate values are finite and inside bounds.

It also converts candidates to vectors in a stable parameter order:

```text
{"kp": 1.2, "ki": 0.1, "kd": 0.0}
-> [1.2, 0.1, 0.0]
```

## `observations.py`

This file represents completed experiments.

Important type:

```python
OptimizationObservation(
    candidate=candidate,
    score=4.73,
    safe=True,
    metadata={"overshoot": 0.2}
)
```

`ObservationHistory` stores all observations, including unsafe ones. It exposes
safe observations separately because only safe observations are used for model
training.

This is where evaluation results enter the optimizer. The actual evaluation
happens outside this package.

## `training.py`

This file builds BoTorch training tensors.

It converts:

```text
safe observations
```

into:

```text
train_x = candidate vectors
train_y = negative scores
```

Example:

```text
candidate = [1.0, 0.2, 0.0]
score = 3.5

train_x row = [1.0, 0.2, 0.0]
train_y row = [-3.5]
```

The negative score matters because BoTorch maximizes and our score is a cost.

## `surrogate_model.py`

This is where the model lives.

The function:

```python
fit_single_task_gp(...)
```

builds and fits:

```python
SingleTaskGP(...)
```

The GP is retrained when a model-guided candidate is requested. It is not
continuously trained during a trial. In the PID UI, proposal work runs in a
background executor so the GUI stays responsive.

The function:

```python
predict_posterior_mean_variance(...)
```

evaluates the fitted GP at query points. This is what powers the surrogate plot.
The plotted mean is converted back to cost space:

```text
predicted_cost = -posterior_mean
```

because the model is trained on `-score`.

## `acquisition.py`

This file decides where to sample next after the GP is trained.

The function:

```python
propose_expected_improvement_batch(...)
```

creates a `qLogExpectedImprovement` acquisition function and optimizes it with
BoTorch's `optimize_acqf`.

The acquisition function uses the GP's prediction and uncertainty to find
candidates that may improve on the best known result.

## `bayesian_optimizer.py`

This is the public orchestrator.

It owns:

- `ParameterSpace`,
- `ObservationHistory`,
- Torch/BoTorch lazy loading,
- Sobol startup proposals,
- GP training,
- acquisition-based proposal.
- GP posterior-grid generation for visualization.

The main method is:

```python
propose_batch(batch_size)
```

Its logic is:

```text
if safe observations < initial_safe_trials:
    return Sobol candidates
else:
    train GP on safe observations
    optimize expected improvement
    return model-guided candidates
```

The other main method is:

```python
record_observations(observations)
```

That is how evaluated experiment results are added to the BO history.

For visualization, the method is:

```python
surrogate_grid(axis_x="kp", axis_y="ki", fixed_values={"kd": best_kd})
```

It returns grid arrays for predicted mean cost and uncertainty. If there are not
enough safe observations yet, it returns `ready=False` and a status message
instead of fitting a GP.

## PID Adapter

The PID adapter lives in:

```text
source/Python/Optimization/pid_gain_adapter.py
```

It preserves PID-specific names:

```python
PidGainCandidate(kp, ki, kd)
PidTrialResult(...)
BotorchPidOptimizer(...)
```

Internally, it creates the standalone optimizer with:

```python
[
    ("kp", kp_bounds),
    ("ki", ki_bounds),
    ("kd", kd_bounds),
]
```

When a PID trial completes, it converts the PID result into an
`OptimizationObservation`. The scalar `score` trains the model. PID-specific
details, such as settling time and overshoot, are stored as metadata.

It also exposes:

```python
surrogate_grid(kd_value=...)
```

for the PID UI. That method asks the standalone optimizer for a `Kp`/`Ki` grid
with `Kd` fixed.

## End-To-End PID Flow

```text
1. PID page defines gain bounds.
2. BotorchPidOptimizer creates a standalone BotorchBayesianOptimizer.
3. Optimizer proposes [Kp, Ki, Kd].
4. PID/control layer runs a trial.
5. PID/control layer measures response metrics.
6. PID page computes a scalar cost.
7. PID adapter records a PidTrialResult.
8. Adapter converts it to an OptimizationObservation.
9. Standalone optimizer stores it.
10. PID UI requests a surrogate grid for plotting.
11. Once enough safe observations exist, the GP is fit.
12. Acquisition proposes the next candidate.
13. The tuner viewport plots observed trials, best/candidate markers, predicted
    mean cost, and uncertainty.
```

## What To Improve Next

Good next steps:

1. Add constrained BO with separate learned safety models.
2. Store unsafe observations in a way the future constraint model can learn from.
3. Add explicit noise handling if repeated trials show measurement variation.
4. Add model diagnostics so operators can see how much data the optimizer has.
5. Add warm-start support from known-good operating points.
