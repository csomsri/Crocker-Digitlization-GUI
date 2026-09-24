# CPU threading benchmark

Run from the repository root. Only the Python standard library is required:

```powershell
py -3.13 CrockerGUI/tests/CPUThreadBenchmark.py
```

For a longer measurement with a saved report:

```powershell
py -3.13 CrockerGUI/tests/CPUThreadBenchmark.py --workers 4 --tasks 32 --repeats 5 --python-iterations 1000000 --native-iterations 300000 --duration 5 --json CrockerGUI/logs/cpu-benchmark.json
```

The script uses CPU computation only. It does not import Qt, Torch, OpenGL, CUDA,
or the application, and does not connect to hardware or open application databases.
The optional JSON file is the only persistent output.

## What is measured

- **Python arithmetic:** compares serial, threaded, and process execution of a
  deterministic integer loop. A normal GIL-enabled interpreter generally cannot
  execute these Python loops simultaneously in multiple threads.
- **Native CPU arithmetic:** compares the same execution modes using OpenSSL's
  PBKDF2 implementation through `hashlib`, which can release the GIL. This is a
  dependency-free demonstration of native CPU parallelism, not a simulation of
  the application's PID mathematics.
- **Timed workers:** workers calculate briefly then wait until their next tick,
  resembling the app's timed control/simulator loops. Reports completed ticks,
  skipped intervals, actual thread CPU time, and explicitly instrumented waits.
  Increase `--tick-iterations` to introduce CPU pressure.

Every execution mode receives the same number of identical jobs. Results are
checked against serial execution on warmup and every repeat. Reported wall time,
throughput, and speedup use the median of measured repeats. Pool creation and one
full warmup batch are excluded from measurements and recorded separately in JSON.
Measured pool wall time includes dispatch and result transfer. Process startup can
still make one-off jobs slower even when steady-state process throughput is good.

`CPU cores` is summed worker thread CPU seconds divided by elapsed seconds. A
value above one is evidence of concurrent CPU execution; it is not total process
CPU usage and excludes scheduling/IPC work outside the measured jobs. Thread CPU
timer resolution makes very short jobs noisy. Use longer jobs for stable results.

High wait percentage with advancing ticks is expected for a lightly loaded timed
loop. It does not mean threads are broken. Work wall time includes possible GIL
and scheduler delays; explicit wait time is not a profiler's OS wait-state count.

Use `--workers 1`, `2`, `4`, etc. to examine scaling. Keep task count and workload
sizes fixed across comparisons, choose at least as many tasks as workers, and
avoid competing heavy jobs. No speedup threshold is treated as a test failure:
CPU quotas, power settings, GIL state, and system load affect results.

This is a synthetic benchmark, not instrumentation of a running Crocker GUI.
It cannot prove that the app is free of deadlocks or identify its rendering
bottlenecks. No hardware trials are parallelized by this script.
