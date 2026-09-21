# Testing Bayesian PID tuning with smoke2

The C++ **PID Control** page now regulates calibrated **beam current (nA)**
by commanding a selected **TC current (A)**. The coil-current preset described
below applies only to the unchanged **PythonPID** page. Smoke2 does not couple
TC current to beam current, so it cannot validate C++ beam regulation or beam
gain tuning. Use an explicitly coupled test plant for that purpose.

From the repository root:

```powershell
cd CrockerGUI
python main.py -simulation -smoke2
```

Open AI Control → PythonPID, arm PID, open Optimized Tuner, and click
**Load smoke2 BO preset**, then **Auto Run N Trials**.
The preset loads TC1, a 250 A target, 20 trials of 10 seconds,
Balanced scoring, Kp 0–2, Ki 0–2, Kd 0–0.1, command limits 0–400 A,
and a 10 A/tick step setting (80 A/s for BO trials). It disables Dry Run
so the trials actually command the local simulated plant. It does not arm
PID or start a trial for you. Allow more than 200 seconds for the full run:
model fitting and candidate selection add time between experiments.

Smoke2 uses the ZMQ command/telemetry path, so the PID page retains its
explicit arming requirement even though the endpoint is a local simulator.
The preset button only appears in smoke2 mode.

## What smoke2 simulates

Smoke2 is a 14-channel running-power-supply test plant, not the cyclotron
physics model. TC1 starts at 200 A; all channels start at nonzero current
with output on and GUI enable off. Uncontrolled channels drift gently
around their initial values. Enabled channels follow their commands with
a first-order lag: each step closes a fraction `min(1, 2.8 × dt)` of the
remaining gap. Output off makes a channel approach zero. There is no
cross-channel coupling, beam optimization, or explicit measurement noise.

The test asks BO to choose PID gains that bring TC1 toward 250 A.
Balanced cost is settling time + 2 × overshoot + 4 × final absolute error
+ 0.01 × integrated absolute control output. Lower cost is better.
Settling uses a 1% tolerance: 2.5 A at this target. Final error is averaged
over the last fifth of the samples.

## Reading the surrogate

- The first six safe observations are exploration trials. Until then the
  plot reports how many safe observations are still needed.
- After six safe trials, the Gaussian-process model predicts cost across
  Kp (horizontal) and Ki (vertical), holding Kd at the displayed slice.
  BO still searches all three gains.
- Green indicates lower predicted cost; blue, amber, and red indicate
  progressively higher cost. Paler cells indicate greater uncertainty.
  Colors rescale with the current surface, so compare history costs to
  judge improvement between updates.
- The amber marker is the candidate and the green marker is the best
  observed safe trial. Trial markers project their Kp/Ki onto the plot;
  their Kd may differ from the surface slice.
- Expect a broad favorable region rather than a guaranteed sharp optimum.
  Integral action can reduce residual error; excessive gains can increase
  overshoot or command activity. This is a qualitative expectation, not
  a measured optimum for this preset. Individual trial costs need not
  improve monotonically because BO also explores uncertain regions.

Trials do not reset the plant to an identical starting current. Starting
state and command history can therefore affect scores; this setup tests
the end-to-end BO workflow, but is not a controlled gain benchmark.
Unsafe trials stay in history and are excluded from training.

Trial History shows the current session, newest first, with numeric sorting,
read-only rows, metric units, and a bold best-safe result. Preparing a new
session clears that history. Review and approve gains before applying them;
applying gains leaves PID disabled.
