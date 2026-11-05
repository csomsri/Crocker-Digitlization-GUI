# Visualization experiments

Standalone design experiments live here before integration into the application.
These scripts read data and open Matplotlib figures; they do not control hardware.

## Current cyclotron visualization workflow

### Historical-data Bayesian optimization replay

```powershell
.venv/Scripts/python.exe historical_bo.py
```

This uses BoTorch/PyTorch/GPyTorch from the local environment. It selects a
600-reading archive pool, reveals 24 initial readings, and makes 20 further
qLogNoisyExpectedImprovement selections across five seeds. The remaining beam
labels stay hidden until selected. Random search uses the same initial readings
and budget. Only archived combinations are queried; no hardware is accessed and
no synthetic response is passed off as a measurement. `--pool-size`, `--initial`,
`--steps`, and `--seeds` configure the replay.

Outputs in `outputs/cyclotron/historical_bo` include `historical_bo.png`,
`replay.csv`, `archive_pool.csv`, `scaling_audit.csv`, `next_archive_settings.csv`,
`summary.json`, and `report.md`. Uncertainty plots distinguish latent mean
uncertainty from individual-reading predictive uncertainty and report empirical
interval coverage. Next settings are archive-query recommendations in recorded
units, not physical current commands or demonstrated machine improvements.
The shaded search curves show min–max across seeds, not confidence intervals.

### Compare predictive error

```powershell
.venv/Scripts/python.exe compare_regressors.py --task both
```

This compares Gaussian process and ordinary linear regression for two tasks:
beam from TC1–TC10, and coil settings from acquisition row position. It sorts
the parsed data by timestamp, reserves the final 20% as a chronological holdout,
and fits both methods on the same evenly spaced selection of up to 600 rows
from the earlier 80%. `--max-train` changes that cap. Preprocessing and kernel
optimization use training data only; GP uses two optimizer restarts and one
independent normalized GP per nonconstant target. Constant targets use a
constant prediction. There is no UMAP or cluster membership in this benchmark.

Outputs under `outputs/cyclotron/model_comparison` include `comparison.json`,
`metrics.csv`, `report.md`, and actual/predicted holdout CSVs for each task.
MAE and RMSE use nA for beam and recorded units for coils. R² measures explained
variance; it is not percentage accuracy and is undefined for constant targets.
Training-mean and last-training-value baselines are included. This is a capped
training comparison on one recording, not independent-run validation or a test
of beam optimization. Beam values depend on the selected historical calibration.

All methods now default to `outputs/cyclotron/beam_measured.csv` when that parsed
file exists. Otherwise they fall back to the historical alpha run sheet as before.
An explicit `--data` always overrides the default. From this directory:

```powershell
.venv/Scripts/python.exe umap_trim_coils.py
.venv/Scripts/python.exe umap_3d.py --third-axis umap
.venv/Scripts/python.exe pca_trim_coils.py
.venv/Scripts/python.exe pacmap_trim_coils.py
.venv/Scripts/python.exe parallel_coordinates.py
.venv/Scripts/python.exe beam_vs_trim_coils.py
.venv/Scripts/python.exe umap_group_regression.py
```

Every view has the same 0–3, 3–5, 5–8 and 8+ nA checkboxes, counts, fixed axes,
and fixed beam color scale. Missing/negative measurements are separate when
applicable. PCA and PaCMAP use only TC1–TC10 for coordinates, just like UMAP.
Parallel coordinates shows TC1–TC10 and measured beam; main magnet is omitted.
The ten-panel view toggles the same acquisition band on all ten axes together.

Linear and GP regression views use beam color for measured points and group
colors for cluster outlines and prediction stars. Range controls hide/show
measurements only: they do not refit models, change cluster outlines, or assign
measured beam values to prediction stars. To fit a restricted band, use the
min/max CLI filters before fitting. Cyclotron-default regression outputs are
saved beneath `outputs/cyclotron/group_regression` (or `group_gp`), separately
from the historical run-sheet outputs.

## Cyclotron telemetry database

### Select ranges inside the visualization

Both UMAP windows include **Beam ranges** checkboxes: **0–3**, **3–5**,
**5–8**, and **8+ nA**. Select any combination. Each label shows its available
point count; the panel also shows the total visible points. All ranges start on.
Toggling them changes visibility without refitting UMAP, changing axis limits,
or rescaling the beam colorbar. Point inspection and 3D rotation still work.
Boundaries belong to the higher display band: `[0,3)`, `[3,5)`, `[5,8)`, `[8,infinity)`.
Negative and missing measurements get separate toggles when present.

Load the full measured sample so all available bands can be selected:

```powershell
python VisualizationExperiments/umap_trim_coils.py --data VisualizationExperiments/outputs/cyclotron/beam_measured.csv
python VisualizationExperiments/umap_3d.py --third-axis umap --data VisualizationExperiments/outputs/cyclotron/beam_measured.csv
```

The controls only show rows loaded from the input. A CSV already restricted to
3–5 nA cannot reveal the other bands. An empty band is shown with count zero.
Coordinate exports retain all loaded rows; the checkboxes only filter the view.

### Select a beam-current band

Set `--min-beam-na LOW --max-beam-na HIGH` to select **LOW < beam <= HIGH**.
Either bound can be omitted for an open-ended interval. The bounds must be
finite and LOW must be smaller than HIGH. Adjacent bands such as 1–3, 3–5,
5–8 and 8–10 nA do not overlap. These are user-chosen current bands, not
statistical significance categories.

Example from the repository root:

```powershell
python VisualizationExperiments/parse_cyclotron.py --beam-calibration CrockerGUI/ExperimentFiles/OctoberPID/beam_cal.json --min-beam-na 3 --max-beam-na 5 --output VisualizationExperiments/outputs/cyclotron/beam_3_to_5.csv
python VisualizationExperiments/umap_trim_coils.py --data VisualizationExperiments/outputs/cyclotron/beam_3_to_5.csv
python VisualizationExperiments/umap_3d.py --third-axis umap --data VisualizationExperiments/outputs/cyclotron/beam_3_to_5.csv
python VisualizationExperiments/beam_vs_trim_coils.py --data VisualizationExperiments/outputs/cyclotron/beam_3_to_5.csv
```

SQLite filtering happens before sampling. The same min/max settings can filter
an existing calibrated CSV directly; in that case only that CSV's existing rows
are available. For distribution comparisons, use one embedding of the combined
bands: separately fitted UMAP axes cannot be compared directly.

`--beam-range-index` independently selects a zero-based hardware detector
range when needed; it is separate from these calibrated current bounds.

### Beam above 3 nA, trim-coil settings only

From the repository root:

```powershell
python VisualizationExperiments/parse_cyclotron.py --beam-calibration CrockerGUI/ExperimentFiles/OctoberPID/beam_cal.json --min-beam-na 3 --output VisualizationExperiments/outputs/cyclotron/beam_gt3.csv
python VisualizationExperiments/umap_trim_coils.py --data VisualizationExperiments/outputs/cyclotron/beam_gt3.csv
python VisualizationExperiments/umap_3d.py --third-axis umap --data VisualizationExperiments/outputs/cyclotron/beam_gt3.csv
python VisualizationExperiments/beam_vs_trim_coils.py --data VisualizationExperiments/outputs/cyclotron/beam_gt3.csv
```

This user-selected cutoff is strictly **greater than 3 nA**, not a statistical
significance test. It selects 604,109 eligible acquisitions in this recording
before taking the default 5,000-row sample. `--max-points 0` exports them all.
Only TC1–TC10 enter either UMAP; beam determines color. `--third-axis umap`
fits three coil-space components, with no main-magnet height. Its X/Y values
need not match the separately fitted 2D embedding. The existing default 3D
mode still uses main magnet for height.

The ten-panel `beam_vs_trim_coils.py` plot shows beam against each individual
recorded coil value directly, without dimensionality reduction. Constant coil
channels appear as vertical lines. Other settings vary simultaneously, so these
are observed associations, not isolated coil response curves. Samples represent
acquisitions, not unique settings or independent experiments; point density
reflects the recording and sampling. The threshold also applies to CSV/Excel
visualization input via `--min-beam-na`, after beam normalization.

To select rows with calibrated beam measurements using the historical October
PID range curves (commands from the repository root):

```powershell
python VisualizationExperiments/parse_cyclotron.py --beam-calibration CrockerGUI/ExperimentFiles/OctoberPID/beam_cal.json --beam-only --output VisualizationExperiments/outputs/cyclotron/beam_measured.csv
python VisualizationExperiments/umap_trim_coils.py --data VisualizationExperiments/outputs/cyclotron/beam_measured.csv
python VisualizationExperiments/umap_3d.py --data VisualizationExperiments/outputs/cyclotron/beam_measured.csv
python VisualizationExperiments/umap_group_regression.py --data VisualizationExperiments/outputs/cyclotron/beam_measured.csv --output-dir VisualizationExperiments/outputs/cyclotron/beam_regression
```

This uses each row's `beam_range_idx` and interpolates the selected calibration
curve. Legacy `curve` outputs are nA; current config `points` outputs are uA.
Readings outside the curve domain, nonfinite readings, and unknown ranges are
excluded with `--beam-only`; the parser does not clamp or extrapolate them.
Filtering happens **before** the 5,000-row sample is selected. The source detector
value, range, calibration path, and filter are retained in the CSV. Calibration
is an interpretation using the selected file, not proof it was the calibration
active during recording. The historical file gives 715,013 eligible rows for
this database, all at range index 2, with calibrated values between 1 and 10 nA.
`--beam-only` means a valid measurement, not proof of physical beam presence.
Use `--min-beam-na VALUE` for a strict lower threshold based on your beam-on
criterion. Both options also work directly on SQLite visualization input with
`--beam-calibration`. Do not also supply `--beam-unit` for raw voltage data.

From the repository root, parse the historical database to a visualization-ready CSV:

```powershell
python VisualizationExperiments/parse_cyclotron.py
```

Default output is `VisualizationExperiments/outputs/cyclotron/parsed.csv`.
The parser uses only the Python standard library and opens SQLite read-only.
It retains every original field, source SQLite row ID, database path, and adds
`timestamp_utc`, `Trim Coil 1` through `Trim Coil 10`, and `Main Magnet` aliases.
LabVIEW timestamps are interpreted as seconds since 1904-01-01 UTC.
The recording uses **TC11 in place of TC8**. The default physical TC1..TC10
mapping is `ch1 ch2 ch3 ch4 ch5 ch6 ch7 ch11 ch9 ch10`. Parsed `Trim Coil 8`
therefore contains `ch11`; the original raw `ch8` and `ch11` columns remain intact.
Plots label the substituted axis `TC8 ← TC11`. Earlier accuracy reports and
saved coordinates that used ch8 are superseded and must be regenerated.
Older parser CSVs with the former default mapping are corrected on loading
when their raw ch11 values are available. Override with `--coil-columns` followed by ten database channel
names in the desired order. All values retain their recorded calibration.

The default selects up to 5,000 evenly spaced row positions after sorting by
timestamp and row ID, including the first and last samples. This is sampling,
not averaging, and can miss short transients. `--max-points 0` exports all rows.
Raw `beam_current` is always retained. Beam color remains gray unless you supply
`--beam-unit nA|uA|mA|A` to confirm the stored unit; this applies unit conversion
only, not sensor calibration or range-dependent scaling.

All existing visualization entry points can also read the database directly:

```powershell
python VisualizationExperiments/umap_trim_coils.py --data CrockerGUI/data/DataFORViz/cyclotron_data/cyclotron_data.db
python VisualizationExperiments/umap_3d.py --data CrockerGUI/data/DataFORViz/cyclotron_data/cyclotron_data.db
python VisualizationExperiments/pca_trim_coils.py --data VisualizationExperiments/outputs/cyclotron/parsed.csv
python VisualizationExperiments/parallel_coordinates.py --data VisualizationExperiments/outputs/cyclotron/parsed.csv
```

SQLite input accepts the same `--max-points`, `--coil-columns`, and `--beam-unit`
options as the parser. PCA, PaCMAP and group regression share this loader too.
Defaults for existing run-sheet commands are unchanged. For telemetry, points
represent sampled acquisitions, which may include noise around repeated settings.
Group regression still uses row position rather than elapsed time.

## Two groups and next-setting regression

```powershell
python umap_group_regression.py
python umap_group_regression.py --no-show --output-dir outputs/group_regression
```

This fits the original ten-coil UMAP, splits its coordinates using seeded KMeans
with two clusters, and circles/labels group A (left centroid, blue) and B (orange).
It exports `group_A.csv`, `group_B.csv`, and `all_settings.csv` with source rows
and group membership. Circles enclose each group and can overlap; membership is
determined by KMeans, not circle overlap.

Three multi-output linear regressions predict TC1–TC10 from row position:
one for A, one for B, and C for all rows. Each dataset preserves input run-sheet
order, assigns positions 0 through n−1, and predicts position n. This is a linear
trend extrapolation, not a chronological forecast: historical dates are unsorted.
Each group needs at least three rows. The final 20% (rounded up) is held out for
per-coil MAE reporting before the final model is fitted on all available rows.

Predictions are transformed with the original fitted scaler and UMAP model,
without refitting the embedding. Stars show A/B predictions in their group colors
and C in purple. `predictions.csv` contains predicted currents and coordinates;
`regression_report.json` contains coefficients and forward holdout errors.
Predicted settings are unmeasured extrapolations and do not imply improved beam.
The default figure is `outputs/group_regression/umap_group_regression.png`.
Common input, seed, preprocessing, `--save`, and `--no-show` options also apply.

The interactive window includes **Show regression** to toggle prediction stars
and their labels, and **Show linear equations** to inspect all 30 coil equations.
Use `--hide-regression` to start with the stars hidden. Both plot versions are
saved automatically (the second has `_without_regression` in its filename).
`linear_equations.txt` and `linear_equations.png` show the vector combination
`predicted currents = intercept + t * slope`, each coil's coefficients, and its
next predicted value. Here `t` is row position within A, B, or the full dataset;
the regression does not combine coil currents as input features. UMAP itself is
nonlinear, so these equations describe the currents before UMAP projection.

### Gaussian process alternative

```powershell
python umap_group_regression.py --model gp
python umap_group_regression.py --model gp --no-show
```

This preserves the same embedding, A/B groups, row-order input, next-position
target, and prediction toggle. Results go to `outputs/group_gp` by default, keeping
the linear outputs available for comparison. Each coil has an independent GP
with a learned constant-times-RBF kernel plus white noise. Row positions are
standardized and coil targets normalized separately for each fitted model;
holdout preprocessing and kernel fitting use only the training portion.
`predictions.csv` includes predictive standard deviations in recorded coil units.
`gp_details.txt`/`.png` show approximate marginal 95% predictive intervals, and
`regression_report.json` includes fitted kernels, normalization, dual weights,
and holdout MAEs. The details button replaces the linear-equations button.
Intervals include fitted white noise and are not joint ten-coil or UMAP confidence
regions. Stars project the predicted mean currents only. The unsorted worksheet
order still limits interpretation as a chronological forecast.

An isolated `.venv` is provided locally with the experiment dependencies. The
scripts use it automatically if the launching Python does not have UMAP installed,
so the plain `python` commands below work without changing the GUI environment.
To set up on another checkout, from this directory:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Then run:

```powershell
python umap_trim_coils.py
python umap_3d.py
python pca_trim_coils.py
python parallel_coordinates.py
python pacmap_trim_coils.py
```

Both compute the same two-dimensional UMAP from **only the ten trim-coil currents**.
The 2D figure uses UMAP 1 and UMAP 2 as its axes. The 3D figure uses those same
coordinates for X/Y and **main magnet current for height**, rather than a third
UMAP component. Both color points by measured output beam current when available.
Rotate the 3D view with the mouse. Click a point to print its source row and all
ten currents. The default input is resolved relative to these scripts, so the
working directory does not change which data is read.

## Input data

Default when available: `outputs/cyclotron/beam_measured.csv`. Otherwise use
the original `../reference_values/Bunch of Run Sheets/alphas 1 2020_2.xlsx`,
worksheet `alpha data`. If that local ignored workbook is absent, the scripts fall
back to `../reference_values/alpha_2020_2_operating_settings.csv`.
Required columns: `Trim Coil 1` through `Trim Coil 10`. Main magnet defaults to
`Main Magnet`. Whitespace around column names is stripped. Incomplete/nonfinite
coil vectors are excluded, reported, and never filled with zero. Negative currents
and signed beam measurements are preserved. Source rows are retained in exports.

**The current alpha extract has no measured beam data.** Its points appear gray,
explicitly marked as missing beam, with no invented color values. To obtain the
requested color scale, supply measured output-beam values in a CSV or workbook:

```powershell
python umap_trim_coils.py --data measured_runs.csv --beam-column beam_nA
python umap_3d.py --data measured_runs.csv --beam-column beam_nA --magnet-unit A
python umap_3d.py --data "../reference_values/Bunch of Run Sheets/alphas 1 2020_2.xlsx" --sheet "alpha data" --beam-column "Stop 2 uA"
```

Use `--magnet-unit A` only after confirming source units. The historical header
does not specify magnet units, so the default label says “recorded units.”
Automatically recognized beam columns are `beam_nA`, `mean_beam_nA`,
`output_beam_nA`, or `Stop 2 uA`; multiple matches require explicit selection.
Custom columns need `--beam-unit nA|uA|mA|A` unless their names specify units.
Colors are converted to nA. Choose the diagnostic that actually measures output;
the script does not substitute ESD current, source current or energy as beam.
`--require-beam` fails when no measured color values are available.

## Reproducibility and exports

```powershell
python umap_trim_coils.py --seed 42 --neighbors 10 --min-dist 0.1 --save outputs/umap_2d.png --export outputs/coordinates.csv --no-show
python umap_3d.py --seed 42 --save outputs/umap_3d.png --no-show
```

Inputs are standardized per coil before UMAP, giving each varying coil equal
scale. Use `--no-standardize` to explore raw current distances. Neighborhood count
is capped at the number of complete rows minus one. The seed and preprocessing
are shared between scripts. With identical inputs/settings/package versions,
their X/Y embeddings match. Missing magnet values hide points only in the 3D
view; they do not change the fit. Every data point is a dot. Missing beam values
remain visible as gray dots; measured values use the beam color scale.

Parsed data and coordinate exports include `output_beam_nA` and
`output_beam_status` (`measured` or `missing`). The normalized `output_beam_nA`
column is selected by default when present; use `--beam-column` to override it.
The extracted alpha CSV also retains the original beam fields, source column and
source cell. `Stop 2 uA` is the selected output diagnostic for this extraction;
confirm that diagnostic choice for the intended operating setup before BO use.
All four supplied alpha workbooks were checked: their circulating, deflected and
Stop 2 measurement columns contain no values. Blank fields remain blank.

UMAP distances and axes are exploratory coordinates, not current units or proof
of causal beam improvement. Different energies/configurations can form apparent
structure; filter to comparable operating conditions before drawing conclusions.
The historical sample is small. Check stability across seeds and neighborhoods.

To test the colored layout without representing synthetic values as measured runs:

```powershell
python umap_trim_coils.py --demo
python umap_3d.py --demo --magnet-unit A
```

Both demo figures are explicitly labeled synthetic.

## PCA, parallel coordinates, and PaCMAP

All three additional scripts use the shared input default (parsed cyclotron
beam data when available, otherwise the original alpha run sheet),
retain the same source rows and output-beam parsing, and accept the common
`--data`, `--sheet`, `--beam-column`, `--beam-unit`, `--save`, `--export`,
`--no-show`, `--seed`, and `--no-standardize` options.

- **`pca_trim_coils.py`**: 2D PCA from the ten trim currents. PC1/PC2 axis labels
  report explained variance; the terminal reports their combined variance. Inputs
  are standardized per coil unless `--no-standardize` is selected. Beam and main
  magnet do not influence the components.
- **`parallel_coordinates.py`**: one line per acquisition across TC1–TC10
  and output beam. Axes use separate min–max scaling to compare patterns;
  original value ranges are printed beneath the labels. Constant axes map to 0.5,
  missing values break lines, and wholly missing beam axes are marked “not
  recorded.” `--no-standardize` displays original values on a common raw scale.
- **`pacmap_trim_coils.py`**: 2D PaCMAP from the same ten standardized coil currents.
  Uses PCA initialization, `MN_ratio=0.5`, `FP_ratio=2`, and the selected seed.
  `--neighbors` controls neighborhood size, capped conservatively for small
  datasets to leave points available for far-pair sampling. At least six complete
  settings are required. Neither beam nor main magnet enters the embedding.

All scatter markers are dots. All three color measured output beam when present,
and show gray for missing beam values. Click a point or line to print source values.
PaCMAP is available in the isolated environment; on a new checkout, install the
updated requirements file. No GUI integration is performed by these experiments.

```powershell
python pca_trim_coils.py --no-show --save outputs/runsheet_pca.png --export outputs/runsheet_pca.csv
python parallel_coordinates.py --no-show --save outputs/runsheet_parallel.png
python pacmap_trim_coils.py --no-show --save outputs/runsheet_pacmap.png --export outputs/runsheet_pacmap.csv
```

PaCMAP reference: [official implementation and parameter descriptions](https://github.com/YingfanWang/PaCMAP).

Reference: [UMAP basic usage](https://umap-learn.readthedocs.io/en/latest/basic_usage.html)
and [parameter guide](https://umap-learn.readthedocs.io/en/latest/parameters.html).
