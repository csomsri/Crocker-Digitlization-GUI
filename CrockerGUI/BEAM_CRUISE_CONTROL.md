# Beam cruise control

Live control provides Start, Stop, Tune now and Apply BO. PID maintains the beam
target using the selected trim coil. Automatic BO starts after persistent drift;
validated gains remain pending until the operator clicks Apply BO.
Navigation links open Live control, PID settings and BO tuning without starting
a controller. Diagnostics, trial history and operator settings are separate dialogs.

Operator defaults: 0.3 nA drift band, 15 s persistence and cooldown, unlimited
sessions, 20 s validation, 30 minute search cap, plateau patience 5.
Waiting for LabVIEW ramping is optional. Real hardware still uses its approved
profile, telemetry checks and interlocks. No real hardware validation was performed.

Implementation: CruiseController.py manages the control lifecycle,
CruiseWorkspace.py builds the workspace and dialogs, CruiseNavigation.py manages
navigation, and cruise_supervisor.py schedules drift-triggered searches.

## First-order TC10 simulation

From the CrockerGUI directory run:

    python main.py -simulation -first-order

Open Automation > PID Control. TC10 and a 0.8 nA beam target are preselected.
Click Start, then Tune now to begin BO immediately, or allow persistent drift
to trigger automatic tuning. Apply BO uses validated gains; Stop ends control.

The synthetic plant has a 2 s time constant and 0.004 nA/A gain. Only TC10
affects beam. The preset uses 10 trials of 20 s, 250 A maximum and gain search
bounds Kp 0-100, Ki 0-80, Kd 0-10. Operators can adjust settings.
This mode runs a local ZMQ plant. Detector values use the inverse of range 0
in beam_cal.json; use manual detector range 0. Python experiments can set
FirstOrderBeamPlant.disturbance_na to test drift.
