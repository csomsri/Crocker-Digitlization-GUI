# Future Visualization Downsampling And CUDA Plan

This is a parking-lot design note. It is not part of the active software flow yet.
The current priority remains the Bayesian PID work; this file captures the
visualization preprocessing ideas so they are easy to resume later.

## Problem

High-rate telemetry can make plots look like noise when the display path reduces
sample count by dropping or lightly smoothing points. If the incoming frequency
is much higher than the plot resolution, the renderer should first normalize the
data into display buckets that preserve the signal shape and important
excursions.

The goal is not to hide real noise. The goal is to avoid visual aliasing caused
by drawing too many raw samples into too few pixels.

## Desired Behavior

- Convert high-Hz telemetry into lower-Hz display-ready samples before plotting.
- Average samples inside each time bucket when the operator wants a stable trend.
- Preserve min and max values inside each bucket so short spikes are still
  visible.
- Carry first and last values so steps and edges are not smeared away.
- Compute RMS and standard deviation so noisy regions can be distinguished from
  smooth regions.
- Keep raw readings available in SQLite; downsampling should only affect display
  products or derived metrics.
- Keep a CPU fallback for all CUDA functionality.
- Do not run CUDA work on the PySide UI thread.

## First Useful Data Product

For each channel and time bucket, produce:

| Field | Purpose |
| --- | --- |
| `bucket_start` | Start timestamp for the bucket. |
| `bucket_end` | End timestamp for the bucket. |
| `count` | Number of raw samples represented. |
| `mean` | Stable trend value for line plotting. |
| `min` | Lowest observed value, for envelope rendering. |
| `max` | Highest observed value, for envelope rendering. |
| `first` | First sample in the bucket, for step preservation. |
| `last` | Last sample in the bucket, for edge preservation. |
| `rms` | Energy/noise magnitude. |
| `stddev` | Variability inside the bucket. |

The line chart can initially draw `mean`. Later, an envelope renderer can draw
`min` to `max` as a translucent band with the mean trace on top.

## Display Modes

- `mean`: draw one averaged point per bucket.
- `envelope`: draw min/max band plus mean line.
- `first_last`: draw first and last values for preserving sharp steps.
- `raw`: draw raw samples when the dataset is already small enough.
- `adaptive`: choose raw, mean, or envelope based on samples per pixel.

## Proposed API

Python-facing function:

```python
downsample_timeseries(
    timestamps: list[float],
    values_by_channel: list[list[float]],
    target_points: int,
    mode: str = "adaptive",
) -> dict
```

Return shape:

```python
{
    "backend": "cpu" | "cuda",
    "target_points": 360,
    "channels": [
        {
            "name": "TC1",
            "buckets": [
                {
                    "start": 123.0,
                    "end": 123.083,
                    "count": 5,
                    "mean": 42.1,
                    "min": 40.8,
                    "max": 44.0,
                    "first": 41.7,
                    "last": 42.4,
                    "rms": 42.12,
                    "stddev": 0.61,
                }
            ],
        }
    ],
}
```

## CPU Implementation First

Before adding CUDA to the build, implement a small pure-Python or NumPy version
that is easy to test:

1. Sort or assume timestamp-ordered samples.
2. Split the visible time range into `target_points` buckets.
3. Accumulate count, sum, sum of squares, min, max, first, and last.
4. Emit only non-empty buckets.
5. Add tests for spikes, steps, uneven timestamps, empty buckets, and single
   sample buckets.

This gives us a correctness oracle for the CUDA version.

## CUDA Implementation Later

CUDA becomes useful when offline history plots or live multi-channel windows are
large enough that CPU preprocessing becomes a visible delay.

Suggested CUDA shape:

- One kernel maps samples to bucket indices and accumulates per-bucket stats.
- Use block-local reductions where possible.
- Use atomics for bucket `count`, `sum`, `sum_squares`, `min`, and `max`.
- Handle `first` and `last` either with timestamp-aware atomics or a second pass.
- Return contiguous arrays to Python; Python formats them for existing plot
  widgets.

Build rules when this becomes active:

- Add an option like `CROCKER_ENABLE_CUDA`.
- Enable CUDA only when requested and available.
- Keep the Python extension importable without CUDA.
- Expose the same Python function for CPU and CUDA backends.

## Where It Would Fit Later

- Live magnetic field plots:
  `CrockerGUI/python/app/Monitoring/MagneticFieldMonitoringPage.py`
- Field control time-domain plot:
  `CrockerGUI/python/app/widgets/MagneticFieldWidgets.py`
- Database history plots:
  `CrockerGUI/python/app/Monitoring/DatabaseHistoryPage.py`
- Optional data processor metrics:
  `CrockerGUI/source/Python/Data/data_processor.py`

The first integration should probably be the database history plots because they
can involve large datasets and are lower risk than live control displays.

## Important Non-Goals For Now

- Do not change CMake yet.
- Do not add CUDA to the active Python extension yet.
- Do not change the live plot behavior yet.
- Do not write derived downsampled data back to SQLite until the schema and UI
  semantics are deliberate.
- Do not use downsampling as a substitute for alarm logic or hardware safety
  checks.

## Resume Checklist

1. Finish or pause the Bayesian PID priority.
2. Add CPU downsampling utility plus tests.
3. Use it in database history plots behind a local feature flag.
4. Add envelope rendering.
5. Benchmark large historical runs.
6. Add CUDA backend only if the benchmark justifies it.
