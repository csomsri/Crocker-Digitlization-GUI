# Reference recovery

PID and standalone BO use `FailureRecovery`; hybrid failed trials use the same
coordinator with their session reference. GA and normal hybrid trial sequencing
share the pure `RecoveryManager` planner through the compatibility imports in
`ga_recovery.py`.

A reference contains TC command, actual current, beam measurement and capture
time. PID captures before starting; BO retains its first captured reference for
the session; hybrid retains its existing session reference. Recovery does not
replace a reference with the result of a failed trial.

For a recoverable failure, stop the native PID worker, cancel tuning, then
restore enabled TC outputs in bounded increments. PID/BO failure recovery uses
0.02 A steps at no more than 20 steps per second, a 0.005 A command tolerance,
0.5 A actual tolerance, 0.2 nA beam tolerance, 2 s stable hold, and 20 s timeout.
Hybrid uses its configured recovery settings. These defaults require review for
the intended operating conditions; capturing a reference does not certify a
hardware-safe operating point.

Recovery checks fresh connected telemetry, authorization, enabled output and
fault/interlock status before writing. It does not enable outputs, bypass an
interlock, or resume PID or optimization. Other workspaces cannot acquire the
backend while failure recovery is active. Duplicate packets do not produce
repeated commands or count toward stable recovery.

Native PID fault handling continues to disable outputs for its fault conditions.
Those failures therefore report recovery blocked. This change deliberately does
not weaken native hardware protection to make restoration succeed. Calibration
changes and failures during existing hybrid recovery stop the session rather
than starting a second recovery attempt. Recovery timeout or rejection ends
recovery and reports the reason; no new trial is started.

Legacy simulator trials may begin with outputs disabled. Such a start has no
verified recovery reference and reports recovery blocked on failure. Hardware
starts require reference capture to succeed. Automatic recovery applies to
TC1–TC12; no automatic magnet or centering-channel recovery is provided.

Saved operator-approved references and automatic retry/resume are not implemented.
The UI reports restoring, recovered, blocked or stopped in its existing status
fields. Recovery remains subject to the LabVIEW/hardware protection policy.

Verification: `python CrockerGUI/tests/FailureRecoveryTest.py`,
`python CrockerGUI/tests/HybridPIDTest.py`, and
`python CrockerGUI/tests/PidControlPageTest.py` use fake or simulated hardware.
