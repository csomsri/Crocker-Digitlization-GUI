# October PID integration

All active PID, BO, Hybrid and GA configurations select October's per-observation
adaptive direction mode. Python uses the supplied pid_controller.py with the
application class alias retained. C++ is verified against it by input replays.
Absolute error determines correction magnitude; increasing error reverses
direction immediately and can issue a corrected increment in that update.
Derivative action damps movement. Integral memory remains across reversals and
deadband entry. Integral/derivative calculations use elapsed observation time;
movement dt is bounded by the configured control interval.

Defaults: deadband 0.2, feedback averaging 0.3 seconds, derivative filter 0.2
seconds, TC target range 0–800 A. Output/integral guards use the TC target span.

## Restriction policy

October mode does not apply the added beam-error, beam-loss amplitude,
overshoot, TC-excursion, saturation timeout, software slew or per-tick step
restrictions. Trials run to their configured duration. Nonfinite or insufficient
feedback remains invalid. Oscillation, saturation and movement affect fitness
instead of causing rejection. BO, Hybrid, Cruise and GA do not exclude
candidates for being unsettled or oscillating. Validation has no fixed
60-second minimum or additional diagnostic observation/hold window.

The supplied October GA evaluator and target-reset manager are used directly.
BO and Hybrid share its normalized objective and default weights: tracking 1,
steady state 2, movement 0.25, saturation 5, oscillation 1. The 10 A movement
normalization is a score scale, not a displacement limit. BO and Hybrid no
longer expose the response-threshold popup or read its saved settings. Fixed
diagnostic defaults label plots/reports; they cannot affect fitness or eligibility.

Target reset sends the full difference to the captured software target.
There is no recovery step, dwell, timeout, beam threshold or measured-current
acceptance condition. Two-decimal software equality is checked. This does not
acknowledge physical settling; ramping remains the transport/LabVIEW's job.

Absolute coil bounds, explicit arming, finite/fresh feedback, connection health,
command ownership, transport rejection and hardware interlocks remain active.
Tuning is available on hardware and simulation. The active direct October path
does not impose the old reviewed field-allocation profile's added restrictions.
Legacy low-level configurations without October mode retain explicit optional
abort settings for compatibility.

## Integration boundary

The application's calibrated-feedback and transport adapters remain in place.
Fresh observations are averaged without repeating held timestamps. Acquisition
does not use the standalone October GUI's raw-voltage ring buffer or receive-side
response-wait mechanism. Replay parity establishes equivalent control math for
equivalent samples, not identical hardware acquisition timing.

Build: cmake --build CrockerGUI/build --config Debug --target CycloViz -j 4.
Restart an already-running GUI to load the rebuilt extension.

Tests cover controller replay, Python/C++ parity, both response polarities,
GA evolution/scoring parity, relaxed worker gates, diagnostic score independence,
target reset and BO/Hybrid/GA workflows. No real hardware trial was run.
