# CUDA Acceleration Plan

This folder is for optional CUDA acceleration in the Crocker Digitalization GUI.
CUDA should improve heavy numerical processing, visualization preparation, and
offline reanalysis. It should not own hardware control, SQLite writes, or PySide
UI updates.

The preferred pattern is:

```text
SQLite raw readings or live telemetry batch
        |
Python data processor
        |
NumPy / contiguous numeric arrays
        |
C++ / CUDA extension
        |
processed arrays, grids, and metrics
        |
Python writes processed results
        |
GUI displays results
```

Keep CUDA as an accelerator with CPU fallbacks. This lets the system run on
non-CUDA machines while using the lab CUDA workstation for larger processing
jobs.

## Current Status

- `Kernel.cu` is only a placeholder kernel.
- `CMakeLists.txt` does not currently enable the CUDA language.
- The Python dependencies include Torch, BoTorch, and GPyTorch, but the current
  focus for this folder is data processing and visualization, not PID tuning.
- CUDA work should be added only after a concrete batch calculation exists and
  CPU timing shows the workload is large enough to benefit.

## Primary Targets

### 1. Visualization Preprocessing

Use CUDA to turn large raw arrays into display-ready data products before the
GUI renders them.

Good first functions:

```text
compute_histogram(values, bins)
compute_heatmap(x_values, y_values, bins_x, bins_y)
compute_density_grid(x_values, y_values, weights, bins_x, bins_y)
compute_spectrogram(samples, window_size, hop_size)
compute_channel_correlation(sample_matrix)
```

Useful GUI outputs:

- heatmap grids
- histograms
- phase-space density maps
- spectrogram-style views
- channel correlation matrices
- high-density scatter plot binning

This is the best first CUDA feature because the project already has chart types
for heatmaps, histograms, spectra, scatter plots, and phase-space style displays.
The output is easy to verify visually and does not touch hardware safety paths.

### 2. Signal Processing Pipeline

Use CUDA inside the data processor for buffered telemetry windows.

Useful functions:

```text
compute_fft_magnitude(samples, sample_rate)
compute_band_power(samples, sample_rate, bands)
compute_rolling_stats(values, window)
apply_fir_filter(samples, coefficients)
detect_peaks(samples, threshold, min_distance)
compute_cross_correlation(a, b, max_lag)
```

Useful processed metrics:

- RF spectral peaks
- noise floor
- ripple magnitude
- channel drift
- peak frequency
- band power
- cross-channel lag
- rolling min, max, mean, RMS, and standard deviation

These results should be written back through Python into processed tables, not
directly from CUDA into SQLite.

### 3. Offline Replay And Reanalysis

Use CUDA for old runs after raw readings are already stored.

Helpful workflows:

- regenerate large plots from millions of readings
- compare two runs over the same channel set
- recompute metrics with updated thresholds
- reapply calibration changes without collecting new data
- scan historical runs for anomalies
- produce export-ready arrays for reports

This is low risk because it does not affect live machine operation. It can also
be run as a background job while the GUI stays responsive.

## Additional High-Value Ideas

### Data Quality Scoring

Compute quality flags over large windows:

- missing sample runs
- flatlined channels
- sudden jumps
- saturation near limits
- excessive noise
- timestamp jitter
- sensor disagreement

This would help operators quickly tell whether a run is trustworthy before
spending time interpreting plots.

### Event Detection

Scan telemetry for interesting transitions:

- beam-on or beam-loss events
- RF trips
- magnet current steps
- vacuum excursions
- recovery periods
- alarm precursor patterns

CUDA can process many channels and windows in parallel, then return compact
event candidates for the Python layer to validate and store.

### Adaptive Downsampling

Generate plot-friendly summaries without losing spikes.

For each time bucket, CUDA can compute:

- min
- max
- mean
- RMS
- first and last sample
- spike count

This lets the GUI display long runs smoothly while preserving important short
events that normal averaging would hide.

### Run Comparison Metrics

Compare a current run against a baseline run:

- channel-by-channel difference
- RMS deviation
- maximum excursion
- time lag
- correlation score
- before/after calibration impact

This would be especially useful for commissioning, maintenance checks, and
verifying that a machine state matches a previous good run.

### Anomaly Feature Extraction

CUDA can compute feature vectors over many sliding windows:

- rolling means and variances
- FFT peaks
- derivatives
- cross-channel correlations
- threshold dwell times
- recovery times after events

Those features can feed simple Python anomaly rules first, and later a learned
model if the dataset grows enough.

### Fast Export Preparation

For large historical runs, CUDA can prepare report/export products:

- binned plots
- summary tables
- per-channel statistics
- compact event timelines
- spectral summaries

This keeps reports responsive when the raw database becomes large.

## Recommended Implementation Order

1. Add a small C++/CUDA extension with a CPU fallback and unit tests.
2. Implement `compute_histogram` and `compute_heatmap`.
3. Connect those outputs to existing visualization pages.
4. Add adaptive downsampling for long time-series plots.
5. Add FFT magnitude and band-power metrics.
6. Add data quality scoring.
7. Add offline replay/reanalysis jobs.
8. Add run comparison and event detection.

## Design Rules

- CUDA should receive numeric arrays and return numeric arrays or small metric
  structs.
- CUDA should not directly read or write SQLite.
- CUDA should not run on the UI thread.
- Every CUDA feature should have a CPU fallback.
- Start with batch/offline processing before live processing.
- Benchmark transfer cost against CPU NumPy/SciPy before keeping a kernel.
- Prefer simple, testable kernels over one large mixed-purpose kernel.
- Store enough metadata to know whether a processed result came from CPU or CUDA.

## First Useful Milestone

The first milestone should be a histogram and heatmap accelerator:

```text
Python reads selected readings
Python packs values into arrays
CUDA computes histogram / heatmap bins
Python stores or displays the result
GUI renders the existing chart type
```

This gives a visible improvement, avoids control-system risk, and creates the
extension structure needed for the later signal-processing and replay tools.
