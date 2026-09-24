# Concurrent worker stress test

Run from the repository root in the project's Python 3.13 environment:

```powershell
py -3.13 CrockerGUI/tests/MultithreadStressTest.py
```

Requires PySide6 and a compatible compiled CycloViz extension. Defaults to 30
seconds, four producers at up to 250 submissions/second **to each database**, and
two additional CPU load threads. Example heavier run:

```powershell
py -3.13 CrockerGUI/tests/MultithreadStressTest.py --seconds 60 --producers 8 --rate 250 --cpu-workers 4
```

## What actually runs concurrently

- Real C++ ControlService simulator at 200 Hz and a continuous dry-run PID at
  100 Hz. The script never starts a network transport or sends hardware commands.
- Two instances of the application's AsyncSQLiteWriter, with a simple test
  schema and independent SQLite files. This exercises the real mailbox, batching,
  retries, capacity limits, and shutdown logic, rather than full telemetry schemas.
- Multiple producer threads submitting uniquely identified records to both writers.
- The application's FileWriter receiving periodic export jobs.
- Native CPU load threads using hashlib/OpenSSL, with no GPU libraries.
- A Qt main-thread event loop with a 10 ms heartbeat. There are no GUI windows;
  rendering, page interactions, and optimization algorithms are not exercised.
- A contention thread holding database A's write lock for two seconds, one third
  of the way through the run. B, PID, and heartbeat must continue advancing.

## Results and controls

Progress is printed once per second. Each run creates its own timestamped folder
under `CrockerGUI/logs/multithread-stress`, containing `report.json`, two test
databases, and a file-worker output. Existing application data is not used.
These artifacts are retained for inspection; longer runs consume more disk and
memory because the test retains accepted record identities for exact comparison.

The final exit status is 0 for PASS and nonzero for FAIL. Checks include exact
accepted-versus-stored record sets, SQLite integrity, producer/CPU-worker progress,
file completion, PID/simulator progress, independent operation during the database
lock, queue drainage, and a bounded shutdown. A parent process watchdog terminates
an overdue child even if its Qt loop or native shutdown hangs.

- `--rate`: desired submissions/sec per producer per database, best effort.
- `--cpu-workers 0`: isolate queue/control behavior without extra CPU load.
- `--lock-seconds 0`: disable injected database contention.
- `--max-heartbeat-ms 500`: default maximum permitted heartbeat lateness.
- `--shutdown-timeout 15`: drain/join budget in seconds. Native shutdown is also
  bounded by the parent watchdog.
- `--output PATH`: parent folder for timestamped run artifacts.

Rejected submissions cause FAIL and are reported separately from accepted data
loss. At extreme settings, rejection can be correct bounded-queue behavior; it
identifies overload at that setting, not necessarily a worker defect. Maximum
queue depth is sampled, not an exact high-water mark. Timings depend on system
load and power settings. This test demonstrates concurrent progress, not that
every thread is executing CPU instructions simultaneously or that all app paths
are free of races/deadlocks.

If Windows sandbox permissions prevent SQLite or subprocess operation, run it
from a normal terminal. No administrator rights are normally needed.
