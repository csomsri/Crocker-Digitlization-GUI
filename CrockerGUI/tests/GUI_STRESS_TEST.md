# CPU GUI stress test

From the repository root:

```powershell
py -3.13 CrockerGUI/tests/GUIStressTest.py --seconds 10 --output CrockerGUI/logs/gui-stress
```

Requires the project's PySide6 environment. Each of three phases runs for the
specified duration. Uses four actual LiveTelemetryPage widgets, the application
stylesheet, synthetic telemetry, and Qt's offscreen raster rendering. It does not
start MainWindow, control services, hardware sockets, or database recording.

The test fills all histories beyond their 1,200-entry caps, checks pause/resume,
then requests 4, 20, and 60 refresh batches per second. Every batch updates and
captures all four pages. It also alternates page sizes and selected readings
every ten batches. A separate 10 ms Qt timer measures event-loop lateness.

Outputs:

- `stress.json`: actual batch rate, CPU seconds, refresh-only timings, complete
  batch timings (including synchronous widget captures), event-loop lateness,
  exceptions, and aggregated Qt messages.
- `monitoring.png`: final rendered page for visual inspection.

`passed` means no captured Python exceptions or failed functional assertions.
It does **not** mean the target rate was achieved. Read actual_hz and latency
distributions to assess performance. A batch renders four pages, so actual_hz
is not a desktop FPS measurement. Captures deliberately impose additional work.
Qt timers coalesce under load. Resize schedules depend on completed batches,
so these phases are stress scenarios rather than controlled scaling comparisons.

This bounded run does not establish long-term memory stability, GPU performance,
native window behavior, whole-application responsiveness, or absence of deadlocks.
Run performance measurements separately from other test suites to reduce noise.
The monitoring screenshot should contain readable text; offscreen Qt on Windows
needs explicit font registration, which this script performs when available.
