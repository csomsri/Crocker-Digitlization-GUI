# Isolated visualization test environment

Compare three visualization pipelines in separate processes with the same benchmark page, Crocker ZMQ packet decoder, and simulator. The default dashboard updates all eight telemetry panels from one packet. A standalone trim bar plot remains available as a smaller workload.

| Configuration | Geometry preparation | Renderer |
| --- | --- | --- |
| `python-plot` | Python loop | Matplotlib Agg raster output in Qt |
| `cpu-opengl` | C++ loop on the CPU | Instanced OpenGL draw in Qt |
| `cuda-opengl` | CUDA kernel | Same instanced OpenGL draw in Qt |

The Python run is an end-to-end baseline. The CPU/OpenGL and CUDA/OpenGL pair holds the rendering code constant. CUDA uploads current channels, downloads the computed heights to the host, and then OpenGL uploads the heights for rendering. Document these transfers when interpreting results.

## Build on Windows

Use Python 3.13 for Crocker's existing CycloViz extension, CMake 3.24 or later, and a C++ compiler. Run these commands from the repository root in a Visual Studio developer terminal. Reuse your existing CycloViz build if it matches your Python interpreter.

```powershell
git submodule update --init --recursive
python -m pip install -r IsolatedVisualizationTestEnvironment/requirements.txt pybind11
cmake -S CrockerGUI -B CrockerGUI/build -DBUILD_TESTING=OFF -DPython_EXECUTABLE="$((Get-Command python).Source)"
cmake --build CrockerGUI/build --config Release --target CycloViz

$bench = "IsolatedVisualizationTestEnvironment"
cmake -S $bench -B "$bench/build-cpu" -DBENCHMARK_ENABLE_CUDA=OFF
cmake --build "$bench/build-cpu" --config Release
cmake -S $bench -B "$bench/build-cuda" -DCMAKE_CUDA_ARCHITECTURES=native
cmake --build "$bench/build-cuda" --config Release
```

The Python configuration needs only the existing CycloViz extension. Both native configurations require OpenGL 3.3 core. The CUDA build additionally needs an NVIDIA driver and CUDA toolkit that support the GPU and host compiler. With a single-config generator, set `-DCMAKE_BUILD_TYPE=Release` and omit the `Release` directory from the library path. On Linux, use `libbar_plot.so`.

## Run a comparison

Each command below launches one window and records a CSV. Omit `--record` and `--duration-seconds` to use interactive controls.

```powershell
$cpu = "$bench/build-cpu/features/bar_plot/Release/bar_plot.dll"
$cuda = "$bench/build-cuda/features/bar_plot/Release/bar_plot.dll"
$common = @("--feature", "dashboard", "--rate-hz", "60", "--warmup-frames", "30", "--record", "--duration-seconds", "30")
python "$bench/main.py" --mode python-plot @common
python "$bench/main.py" --mode cpu-opengl --library $cpu @common
python "$bench/main.py" --mode cuda-opengl --library $cuda @common
```

Warm-up excludes the first 30 rendered, valid frames by default. The duration is total window time including warm-up. Use the CSV's measured elapsed time and sample count when reporting results. For the dashboard stress case, add `--bars 256` to repeat each multichannel panel's input pattern. Use `--feature bar-plot --bars 14` for the standalone workload. Keep the window visible, use the same plot dimensions and packet rate, and repeat each workload across separate runs. Compare achieved FPS and coalescing together, because a renderer that cannot keep up will intentionally skip some incoming updates.

The page binds a private loopback port and starts the standard simulator by default. With `--external --port 5588`, start a separate simulator or replay client pointed at `tcp://127.0.0.1:5588`. Use a dedicated test sender. The server sends standard protocol replies.

## Measurements

| Metric | Scope |
| --- | --- |
| Process and system CPU, process RSS | Sampled about once a second. Process CPU includes native and simulator threads. 100% process CPU equals one logical core. |
| GPU utilization, VRAM, power, temperature | Device-wide NVIDIA telemetry, sampled about once a second. CSV includes the GPU identifier and sample age. Unavailable readings are blank. |
| Preparation and CUDA stages | Host wall time for preparing heights, including transfers and synchronization in CUDA mode. CUDA rows also give separate upload and download call times and CUDA-event kernel time. |
| Render time | Agg artist updates, raster draw and Qt repaint for Python. Height-buffer upload and draw through `glFinish` for OpenGL. The OpenGL timer excludes Qt window presentation. |
| Frame work, interval and throughput | Synchronous handler work through repaint, interval between recorded frame starts, and achieved processing rate. Frame work excludes ZMQ queue draining and CSV writing. |
| ZMQ receive rate, latency, queue and coalescing | Dequeued packet rate, Crocker decoder's timestamp-based latency, queue depth, and updates superseded by a newer packet in the same drain batch. Queue eviction within the server is outside the coalesced count. |
| Workload and renderer | Mode, bar count, requested simulator rate, warm-up count, renderer name, and physical plot dimensions. |

On multi-GPU systems, confirm the OpenGL renderer in the CSV and use the same GPU for both OpenGL runs. The CUDA run selects its telemetry device by PCI ID. For the other runs, set `--gpu-id` to the same NVIDIA PCI ID. Note driver, toolkit, software versions, device, measured duration, and run count in the paper's benchmark setup.

## Directory layout

- `backends/python_plot/` contains the Python and Matplotlib baseline.
- `backends/cpu_opengl/` and `backends/cuda_opengl/` contain the native geometry adapters and share `backends/opengl.py`.
- `features/bar_plot/` contains the bar-plot workload, C++ and CUDA sources, feature notes, and `results/<mode>/` outputs.
- `features/dashboard/` combines eight bar-plot panels, documents their input fields, and writes per-panel and dashboard measurements to its own `results/<mode>/` outputs.
- `main.py` registers features and launches the shared `benchmark_page.py`.

Add new workloads as sibling folders under `features/`. Register the widget in the launcher and its native target in CMake. Supply a description and a results folder. The feature widget exposes its name, mode, metrics, results path, and optional NVIDIA device ID, and implements `start()`, `process(packet, validate=False)`, and `stop()`.
