# Bayesian PID Tuner — Remaining Work

This file tracks what is still needed before the Bayesian Optimization PID tuner can be considered finished and ready for progressive commissioning.

## Highest Priority

- [ ] Add a repeatable baseline/reset procedure between trials so every gain set starts from a comparable plant state.
- [ ] Build the live visualization in the reserved viewport.
  - Current response, target, and error
  - Trial score and best score
  - Tested PID gain combinations
  - Surrogate prediction and uncertainty where practical
- [ ] Add an automated multi-trial session mode with manual approval, automatic approval, pause, and safe stop options.

## Trial Safety

- [ ] Add abort limits for excessive error, overshoot, control effort, command saturation, sensor faults, and communication loss.
- [ ] Mark each candidate clearly as proposed, approved, running, completed, rejected, aborted, or unsafe.
- [ ] Lock gain bounds and trial settings while a tuning session is running.
- [ ] Verify that stopping or losing communication always returns the controller to a known safe state.

## Optimization Quality

- [ ] Normalize the performance metrics before combining them into the optimization cost.
- [ ] Show how settling time, overshoot, steady-state error, and control effort contribute to the final cost.
- [ ] Repeat the best trial before approving its gains to confirm that the result is reproducible.
- [ ] Compare the approved gains against the original PID gains before applying them.

## Records and Workflow

- [ ] Save and reload tuning sessions, trial history, settings, metrics, gain sets, timestamps, and abort reasons.
- [ ] Export trial history for engineering review.
- [ ] Require an explicit confirmation before applying approved gains to the normal PID controller.
- [ ] Keep applying gains separate from enabling the PID or hardware output.

## Hardware Commissioning

- [ ] Add and calibrate the control-allocation/sensitivity mapping for the real plant.
- [ ] Validate with recorded data and a digital twin.
- [ ] Perform hardware-in-the-loop testing.
- [ ] Perform output-disabled dry runs.
- [ ] Begin low-current, supervised trials with conservative limits.
- [ ] Complete controlled commissioning before enabling unrestricted hardware tuning.

## Testing

- [ ] Add tests for baseline reset and repeatability.
- [ ] Add tests for every abort condition and watchdog path.
- [ ] Add tests for pause, resume, stop, and communication loss.
- [ ] Add tests for session persistence and recovery.
- [ ] Add tests confirming that applying gains never enables PID control or hardware output automatically.

## Current Status

The current implementation is a useful simulation foundation: it can request BoTorch candidates, run simulated C++ PID trials, calculate performance metrics, record results, display trial history, validate a best result, and transfer gains to the PID page. Hardware tuning remains intentionally blocked until the allocation mapping and safety commissioning work are complete.
