# IPAC visualization benchmark development plan

## Research question

How much does CUDA change the cost of preparing and displaying Crocker telemetry, from a single plot to the full eight-section dashboard? Compare Python/Matplotlib as the end-to-end baseline. Use the same OpenGL renderer for C++ CPU and CUDA to isolate the effect of where the plot data is prepared.

## Milestones

| Milestone | Development work | Acceptance criteria |
| --- | --- | --- |
| 1. Verify the Python environment | Set up Python 3.13 and CycloViz. Run Smoke2 with the Python section pages and dashboard. Record a short run. | All eight telemetry sections display data. A recording produces a readable CSV with visualization and telemetry metrics. |
| 2. Verify CPU/OpenGL and CUDA/OpenGL | Build both native backends. Compare the trim bar workload first, then run the eight-section dashboard. | All three modes produce equivalent bar values for matched inputs. Every populated dashboard panel reports a paint. |
| 3. Make telemetry measurable and replayable | Add fixed-sequence ZMQ replay and a telemetry-only workload. Instrument packets sent, decoded, queued, selected, and rendered. Measure decoding and queue wait separately. | Packet counts explain losses and intentionally combined updates. Every mode can run the same replay using a fixed warm-up and measurement window. |
| 4. Build matched plot workloads | Add rolling time-series and heatmap workloads to all three configurations. Define representative and stress sizes. | Each plot passes numerical checks across all three modes and can be recorded individually. |
| 5. Benchmark the dashboard | Run all eight sections together with a fixed layout and update schedule. Record per-plot timings and total frame work. | Full dashboard recordings cover all eight sections and show which pipeline stage limits the achieved update rate. |
| 6. Automate runs and produce paper figures | Launch each configuration in a fresh process, repeat the workload matrix, capture run settings, and generate tables and figures from raw CSVs. | A second person can reproduce the results from the saved commands, settings, and analysis script. |

## Measurements

- **Telemetry.** Offered, decoded, selected, and displayed update rates. Record decode time, queue wait, and skipped updates.
- **Visualization.** Preparation and rendering time, median and p95 frame work, and achieved update rate. Report CUDA upload, kernel, and download times separately. Account for the subsequent OpenGL buffer upload.
- **Resources.** Process and system CPU usage, GPU utilization, RAM, and VRAM.
- **Reproducibility.** Record hardware, driver and software versions, build configuration, plot dimensions, workload size, input rate, warm-up and measurement durations, sample counts, and run-to-run variation.

## First deliverables

1. Verify a short Python Smoke2 recording with all eight telemetry sections populated.
2. Verify a matched three-way bar-plot run using the same Smoke2 input sequence.
3. Add fixed replay and telemetry-only measurements before collecting results for the paper.

Keep historical cuDF analysis and the calculator project outside this development scope.

## Proposed repository structure

```text
IsolatedVisualizationTestEnvironment/
  IPAC_DEVELOPMENT_PLAN.md
  README.md
  requirements.txt
  CMakeLists.txt
  scripts/
    Setup-Python.ps1
    Build-Native.ps1
    Run-Benchmark.ps1
    Run-Suite.ps1
  harness/
    main.py                 # Select workload, backend, source, and recording settings
    telemetry.py            # Crocker ZMQ adapter, replay, and packet counters
    window.py               # Dashboard and one page per telemetry section
    recording.py            # Run metadata, timings, and resource samples
  renderers/
    matplotlib_plot.py
    opengl_plot.py           # Shared by the C++ CPU and CUDA configurations
  workloads/
    telemetry_only/
    bar_plot/
      README.md
      workload.py            # Inputs, output contract, and Python preparation
      native/
        BarPlot.hpp
        BarPlot.cpp
        BarPlotCuda.cu
      results/
    time_series/
    heatmap/
    dashboard/
  analysis/
    summarize.py            # Reproduce tables and figures from recorded runs
```

Start with `telemetry_only` and `bar_plot`. Build time-series, heatmap, and dashboard workloads once the matched bar comparison works. Each plot workload owns its input specification, implementation, and results. The dashboard composes plot workloads and offers eight pages: trim channels, extraction, extraction angles, source, transport, vacuum, RF power, and beam current. A separate overview draws all eight together.

Use the existing Crocker decoder and Smoke2 simulator for integration. Take one decoded packet per dashboard update. For repeatable runs, replay the same packet sequence and pacing across modes. A telemetry-only run uses the same receive path and captures timing and counts without plotting. Store raw recordings by workload and run ID, along with the benchmark configuration and environment metadata.

## Setup and scripts to implement

| Script | Responsibility |
| --- | --- |
| `Setup-Python.ps1` | Create a local Python 3.13 virtual environment, install the benchmark dependencies, and verify imports. Keep the virtual environment out of Git. |
| `Build-Native.ps1` | Build CycloViz and the selected native backend in separate Release build directories. Check CMake, MSVC, the Windows SDK, and submodules. Require the CUDA toolkit only when CUDA is selected. |
| `Run-Benchmark.ps1` | Launch one workload using the local virtual environment. Accept backend, source, telemetry section, input rate, workload size, warm-up, measurement duration, and output path. Use Smoke2 for live checks and fixed replay for paper runs. |
| `Run-Suite.ps1` | Run a saved matrix in fresh processes, repeat each case, and save settings and raw results. Flag failed or incomplete runs. |
| `analysis/summarize.py` | Read completed recordings, calculate run-level statistics and variation across repeats, and generate figures and tables. |

Set up Python first, then build CycloViz for the ZMQ path. Verify a short Smoke2 recording with the Python backend before building the CPU/OpenGL configuration. Add CUDA after the CPU/OpenGL reference passes, so both native backends use the same renderer and can be compared on the same workload.
