# GA PID integration

Implemented after approval: two Automation entries, **GA + C++ PID** and
**GA + Python PID**, sharing the controller workflow and one new GA implementation. The Python page
retains the copied layout; the C++ page now uses BO-style PID/tuner navigation.

## File structure

```text
python/app/Automation/
  GAPIDPage.py                 C++ page and matching Python subclass; app integration
  ControlOwnership.py         Shared manual/PID/BO/GA ownership checks
  GA/
    __init__.py
    PIDGAControlTab.py         Frontend copied from ExperimentFiles, ported to PySide6
    CppLayout.py              C++-only BO-style controls, tuner and settings dialogs
    CppTrendPlot.py           C++ charts: legends, latest values, axes and hover readouts
    ControllerContext.py      Qt presentation bridge and calibrated beam feedback
    Theme.py                  Local replacement for absent reference theme helpers
    TrendPlot.py              Replacement two-series Qt plots
source/Python/Optimization/
  genetic_optimizer.py        Bounded population, elitism, crossover and mutation
source/Python/Automation/
  ga_evaluation.py            Warm-up, scoring, abort thresholds and CSV exports
  ga_recovery.py              Pure baseline/reference recovery planner
  ga_backend_adapter.py      Checked commands through the shared C++ ControlService
source/Python/Control/
  NLAPID.py                   Existing Python PID, unchanged
  CppPIDAdapter.py            Dataclass adapter for existing CycloViz.NLAPID
source/Controls/ControlSystem/
  NLAPID.cpp                  Existing C++ PID, unchanged
source/Controls/Service/
  ControlService.cpp          Existing transport/command service, unchanged
ExperimentFiles/
  pid_ga_control_tab.py       Original reference, unchanged
Exports/GA/<timestamp>/       Run metadata, per-candidate CSV and summary CSV
tests/GAPIDTest.py           Evolution, scoring, recovery, both pages and output tests
```

The Python and C++ pages share the frontend controller class and GA code.
CppLayout rearranges the existing connected widgets only for C++; Python keeps
its original layout. PID setup leads to a separate GA tuner through Open GA
Tuner / Back to PID Control, with advanced settings in dialogs.
The injected PID engine determines control execution. Both engines calculate incremental target
changes; commands go through the existing C++ ControlService shared with Field
Ctrl. The C++ variant calls the already-bound C++ NLAPID directly; it does not
use a replacement Python PID or the channel-based StartPidTrial worker. This
preserves the copied page's distinct beam feedback and trim-coil actuator.

The copied QWidget retains its event timers and candidate sequencing. Numerical
PID calculations, genetic evolution, evaluation, recovery planning and the
command boundary live outside the frontend. A separate ga_pid_session.py was
not introduced in this port; extracting the existing event orchestration would
be a later refactor, without duplicating the UI or PID engines.

## Frontend fidelity and new AI source

Preserved the reference's PID CONTROL and GA AUTO-TUNE tabs, three-column PID
workspace, gain radar, monitoring readouts, candidate response plots, fitness
history, configuration controls and recovery workflow. PyQt6 imports were
converted to the application's PySide6. The absent theme and plot support files
were implemented locally, so their exact original rendering cannot be preserved.

The user confirmed that the missing GA engines do not exist and authorized new
implementations. Search uses a deterministic default seed, bounded uniform
initial population including seed gains, top-half parent selection, one elite,
blend crossover and clipped Gaussian mutation. Both pages share this engine.

Scoring excludes warm-up and combines time-weighted mean absolute tracking
error, final-window absolute error, total actuator movement, saturation fraction
and signed-error crossings. The weighted sum r is mapped monotonically to
999999 * (1 - 1/(1+r)). Safety violations receive an additional 1000000, so
unsafe candidates always rank below valid candidates. CSV includes untransformed
terms and the final score. Recovery requires targets, actual currents and beam
feedback to return to the captured reference for the configured stable hold.

## Integration and operating scope

- PageRegistry and AutomationPage expose both pages.
- MainWindow supplies the shared backend and its current_beam_state provider,
  including assigned monitor pages. Calibrated microamps are converted to nA.
- Missing C++ bindings produce a visible disabled C++ PID action; execution
  never silently falls back to Python.
- Preview performs no writes. Output and automatic GA retain the application's
  simulation tuning restriction; live beam-feedback commissioning is not enabled.
- Output requires fresh beam and transport data, arming, enabled/on actuator,
  valid limits and no fault/interlock. Repeated packets do not repeat writes.
  Rejected commands restore staged targets and abort the copied run workflow.
- Manual, BO and other PID/GA pages cannot issue competing commands while a
  controller owns the shared backend. Main/assigned-window cleanup stops timers.
- Baseline is restored between candidates; original gains are restored after
  automatic search. Applying the best gains remains an explicit UI action.

## Validation

`python CrockerGUI/tests/GAPIDTest.py` covers both actual PID engine classes,
a complete automatic generation through each, bounds/reproducibility, recovery,
preview, rejected writes, ownership, stale/duplicate packets, CSV exports and
1280/1440/1920-wide layout checks. It does not connect to physical hardware.

Additional verification: PythonPIDPageTest (4 tests), CppNLAPIDIntegrationTest
(8 tests), assigned-window rendering, and MainWindow construction with both
new entries sharing Field Ctrl's backend. Both GA PID variants also issued
commands through a real C++ ControlService simulator. PidControlPageTest passed
on a separate rerun after earlier BO candidate-generation timeouts. The broader
ResponsiveLayoutTest still stops at the existing PID Control scroll-area
assertion, before reaching GA; that failure remains open.
