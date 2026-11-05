"""Shared loading and embedding so 2D and 3D experiments use the same coordinates."""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from parse_cyclotron import DEFAULT_COILS, LEGACY_COILS

HERE = Path(__file__).resolve().parent
RUNSHEET = HERE.parent / 'reference_values' / 'Bunch of Run Sheets' / 'alphas 1 2020_2.xlsx'
BEAM_DATA = HERE / 'outputs/cyclotron/beam_measured.csv'
DEFAULT_DATA = BEAM_DATA if BEAM_DATA.is_file() else RUNSHEET if RUNSHEET.is_file() else HERE.parent / 'reference_values' / 'alpha_2020_2_operating_settings.csv'
COILS = [f'Trim Coil {i}' for i in range(1, 11)]


def beam_bands(values):
    """Nonoverlapping display bands; 3, 5 and 8 enter the higher band."""
    return [('0–3 nA', (values >= 0) & (values < 3)),
            ('3–5 nA', (values >= 3) & (values < 5)),
            ('5–8 nA', (values >= 5) & (values < 8)),
            ('8+ nA', values >= 8),
            ('Negative beam', values < 0)]


def add_beam_range_controls(fig, groups):
    """Keep one scatter per band so picking and 3D rotation remain intact."""
    from matplotlib.widgets import CheckButtons
    controls_ax = fig.add_axes([.79, .68, .20, .20], facecolor='#20262f')
    controls_ax.set_title('Beam ranges · select any', fontsize=9)
    labels = [f'{label} ({len(rows)})' for label, artist, rows in groups]
    controls = CheckButtons(controls_ax, labels, [True] * len(groups),
                            frame_props={'edgecolor': '#b5bdc9'},
                            check_props={'color': '#4bb8ff'})
    for label in controls.labels:
        label.set_fontsize(9)
    count = fig.text(.79, .64, '', fontsize=9, color='#b5bdc9')
    def update(_=None):
        total = 0
        for enabled, (_, artist, rows) in zip(controls.get_status(), groups):
            if artist is not None:
                for item in artist if isinstance(artist, (list, tuple)) else [artist]:
                    item.set_visible(enabled)
            if enabled:
                total += len(rows)
        count.set_text(f'{total:,} / {sum(len(rows) for _, _, rows in groups):,} points shown')
        fig.canvas.draw_idle()
    controls.on_clicked(update)
    # Widgets require a live reference for interactive callbacks.
    fig._beam_range_controls = controls
    update()
    return controls


def display_beam_bands(values, np):
    """Include missing measurements for views that plot incomplete beam data."""
    bands = beam_bands(values)
    return [(label, mask) for label, mask in bands if label != 'Negative beam' or mask.any()] + (
        [('Missing beam', ~np.isfinite(values))] if (~np.isfinite(values)).any() else [])


def arguments(three_dimensional, method='umap'):
    parser = argparse.ArgumentParser(description=(
        'X/Y: UMAP from ten trim currents; height: main magnet; color: measured beam.'
        if three_dimensional else 'UMAP from ten trim currents, colored by measured beam.'))
    parser.add_argument('--data', type=Path, default=DEFAULT_DATA, help='CSV, Excel, or SQLite input; defaults to parsed cyclotron beam data when available, otherwise the alpha run sheet')
    parser.add_argument('--max-points', type=int, default=5000, help='SQLite only: evenly spaced time-ordered rows; 0 loads all')
    parser.add_argument('--coil-columns', nargs=10, default=DEFAULT_COILS, help='SQLite channels in TC1..TC10 order; TC8 uses ch11')
    parser.add_argument('--beam-calibration', type=Path, help='SQLite: range-dependent raw detector calibration JSON')
    parser.add_argument('--beam-only', action='store_true', help='Keep valid beam measurements; SQLite filters before sampling')
    parser.add_argument('--min-beam-na', type=float, help='Keep beam strictly above this nA threshold; SQLite filters before sampling')
    parser.add_argument('--max-beam-na', type=float, help='Keep beam at or below this nA bound; SQLite filters before sampling')
    parser.add_argument('--beam-range-index', type=int, help='Select a zero-based hardware detector range index')
    parser.add_argument('--sheet', default='alpha data', help='Excel worksheet name')
    parser.add_argument('--beam-column', help='Measured output beam column, e.g. beam_nA or "Stop 2 uA"')
    parser.add_argument('--beam-unit', choices=['nA', 'uA', 'mA', 'A'], help='Required for custom beam columns whose name does not specify units')
    parser.add_argument('--magnet-column', default='Main Magnet')
    parser.add_argument('--magnet-unit', default='recorded units', help='Use A only after confirming the source units')
    if three_dimensional:
        parser.add_argument('--third-axis', choices=['main-magnet', 'umap'], default='main-magnet',
                            help='Use umap for a true three-dimensional embedding of trim coils only')
    if method in ('umap', 'pacmap'):
        parser.add_argument('--neighbors', type=int, default=10)
    if method == 'umap':
        parser.add_argument('--min-dist', type=float, default=.1)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--no-standardize', action='store_true', help=(
        'Display raw values instead of separate min-max axis scales' if method == 'parallel' else
        'Use raw currents rather than per-coil standardized values'))
    parser.add_argument('--require-beam', action='store_true', help='Fail instead of plotting missing beam measurements in gray')
    parser.add_argument('--save', type=Path, help='Save a PNG/PDF/SVG as well as opening the figure')
    parser.add_argument('--export', type=Path, help='Save coordinates, original settings, and normalized beam values as CSV')
    parser.add_argument('--no-show', action='store_true', help='Headless mode; combine with --save')
    parser.add_argument('--demo', action='store_true', help='Explicit synthetic ten-coil demonstration, not measured machine data')
    return parser


def dependencies():
    print('Loading visualization libraries...', flush=True)
    try:
        import numpy as np
        import pandas as pd
        import umap
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise ValueError('Missing dependency. Run: python -m pip install -r "' + str(HERE / 'requirements.txt') + '"') from exc
    return np, pd, umap, StandardScaler


def load_data(args, np, pd):
    if args.demo:
        rng = np.random.default_rng(args.seed)
        latent = rng.normal(size=(120, 2))
        currents = latent @ rng.normal(size=(2, 10)) + rng.normal(scale=.15, size=(120, 10))
        frame = pd.DataFrame(currents, columns=COILS)
        frame['Main Magnet'] = 1000 + 100 * latent[:, 0] + 25 * latent[:, 1]
        frame['beam_nA'] = 10 + 5 * np.exp(-np.sum((latent - .3)**2, axis=1)) + rng.normal(scale=.05, size=120)
        frame['source_row'] = np.arange(1, 121)
        return frame, 'SYNTHETIC DEMO · not measured cyclotron data'
    path = args.data.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f'Input file does not exist: {path}')
    if path.suffix.lower() == '.csv':
        frame = correct_cyclotron_mapping(pd.read_csv(path, encoding='utf-8-sig'))
    elif path.suffix.lower() in ('.db', '.sqlite', '.sqlite3'):
        from parse_cyclotron import read_cyclotron
        frame = pd.DataFrame(read_cyclotron(path, max_points=args.max_points,
                             coil_columns=args.coil_columns, beam_unit=args.beam_unit,
                             beam_calibration=args.beam_calibration, beam_only=args.beam_only,
                             min_beam_na=args.min_beam_na, max_beam_na=args.max_beam_na,
                             beam_range_index=args.beam_range_index))
        print(f'Loaded {len(frame)} time-ordered telemetry samples; coil mapping: {args.coil_columns}.')
        print('Coils and main magnet retain recorded values; calibration is not applied.')
        if not args.beam_unit and not args.beam_calibration:
            print('Beam units unverified: use --beam-unit only after confirming stored beam_current units.')
    elif path.suffix.lower() in ('.xlsx', '.xlsm'):
        try:
            frame = pd.read_excel(path, sheet_name=args.sheet, engine='openpyxl')
        except ImportError as exc:
            raise ValueError('Excel input requires openpyxl: python -m pip install openpyxl') from exc
    else:
        raise ValueError('Supported input formats are CSV, XLSX, XLSM, DB, SQLITE and SQLITE3')
    frame.columns = [str(c).strip() for c in frame.columns]
    if frame.columns.duplicated().any():
        raise ValueError('Duplicate column names after stripping whitespace')
    if 'source_row' not in frame:
        frame['source_row'] = np.arange(2, len(frame) + 2)
    return frame, path.name


def prepare(args, frame, np, pd):
    missing = [c for c in COILS if c not in frame]
    if missing:
        raise ValueError('Missing trim-coil columns: ' + ', '.join(missing))
    frame = frame.copy()
    currents = frame[COILS].apply(pd.to_numeric, errors='coerce')
    keep = np.isfinite(currents.to_numpy()).all(axis=1)
    dropped = int((~keep).sum())
    if dropped:
        print(f'Excluded {dropped} rows without ten finite trim currents. Blank currents are not zero-filled.')
    frame = frame.loc[keep].copy().reset_index(drop=True)
    currents = currents.loc[keep].to_numpy(dtype=float)
    if len(frame) < 3 or len(np.unique(currents, axis=0)) < 3:
        raise ValueError('UMAP requires at least three distinct complete trim-coil settings')
    beam_column = args.beam_column
    if beam_column:
        if beam_column not in frame:
            raise ValueError(f'Beam column not found: {beam_column}')
    else:
        # The normalized output column is authoritative in parsed run-sheet data.
        choices = (['output_beam_nA'] if 'output_beam_nA' in frame else
                   [c for c in ('beam_nA', 'mean_beam_nA', 'Stop 2 uA') if c in frame])
        if len(choices) > 1:
            raise ValueError('Multiple output beam columns found; select one with --beam-column')
        beam_column = choices[0] if choices else None
    beam = np.full(len(frame), np.nan)
    if beam_column:
        # Parser output is already normalized, regardless of the source unit.
        unit = 'nA' if beam_column == 'output_beam_nA' and not args.beam_column else args.beam_unit
        if unit is None:
            if beam_column.endswith('nA'):
                unit = 'nA'
            elif beam_column.endswith('uA'):
                unit = 'uA'
            elif beam_column.endswith('mA'):
                unit = 'mA'
            else:
                raise ValueError('Specify --beam-unit for the selected beam column')
        beam = pd.to_numeric(frame[beam_column], errors='coerce').to_numpy(dtype=float, copy=True)
        beam *= {'nA': 1., 'uA': 1000., 'mA': 1e6, 'A': 1e9}[unit]
        beam[~np.isfinite(beam)] = np.nan
        print(f'Color diagnostic: {beam_column}; displayed in nA. Polarity is preserved.')
    selection = np.ones(len(frame), dtype=bool)
    if args.min_beam_na is not None and args.max_beam_na is not None and args.min_beam_na >= args.max_beam_na:
        raise ValueError('Minimum beam must be less than maximum beam')
    if args.beam_only:
        selection &= np.isfinite(beam)
    if args.min_beam_na is not None:
        if not np.isfinite(args.min_beam_na):
            raise ValueError('Minimum beam must be finite')
        selection &= np.isfinite(beam) & (beam > args.min_beam_na)
    if args.max_beam_na is not None:
        if not np.isfinite(args.max_beam_na):
            raise ValueError('Maximum beam must be finite')
        selection &= np.isfinite(beam) & (beam <= args.max_beam_na)
    if args.beam_range_index is not None:
        if args.beam_range_index < 0 or 'beam_range_idx' not in frame:
            raise ValueError('Hardware range filtering needs a nonnegative index and beam_range_idx column')
        selection &= pd.to_numeric(frame['beam_range_idx'], errors='coerce').to_numpy() == args.beam_range_index
    if not selection.all():
        print(f'Beam filter excluded {int((~selection).sum())} input rows.')
        frame = frame.loc[selection].copy().reset_index(drop=True)
        currents, beam = currents[selection], beam[selection]
    if len(frame) < 3 or len(np.unique(currents, axis=0)) < 3:
        raise ValueError('Need at least three distinct complete trim-coil settings after beam filtering')
    count = int(np.isfinite(beam).sum())
    print(f'{len(frame)} complete settings; {count} measured beam values; {len(frame) - count} missing beam values.')
    if not count:
        if args.require_beam:
            raise ValueError('No measured output beam values. Supply a measured beam column; missing values are not zero.')
        print('No measured output beam is available. Points will be gray; no beam values are fabricated.')
    frame['measured_beam_nA'] = beam
    frame['output_beam_nA'] = beam
    frame['output_beam_status'] = np.where(np.isfinite(beam), 'measured', 'missing')
    if 'output_beam_source_column' not in frame or args.beam_column:
        frame['output_beam_source_column'] = beam_column or 'not recorded'
    if args.data.suffix.lower() in ('.xlsx', '.xlsm') and beam_column:
        column_index = frame.columns.get_loc(beam_column) + 1
        letters = ''
        while column_index:
            column_index, remainder = divmod(column_index - 1, 26)
            letters = chr(65 + remainder) + letters
        frame['output_beam_source_cell'] = frame['source_row'].map(lambda row: f'{args.sheet}!{letters}{row}')
    frame['main_magnet_value'] = (pd.to_numeric(frame[args.magnet_column], errors='coerce')
                                  if args.magnet_column in frame else np.nan)
    return frame, currents


def correct_cyclotron_mapping(frame):
    """Upgrade old parser CSVs while retaining raw channels and custom mappings."""
    if not {'coil_mapping', 'source_database', 'ch11', 'Trim Coil 8'}.issubset(frame.columns):
        return frame
    old = frame['coil_mapping'].eq(','.join(LEGACY_COILS))
    if 'coil_mapping_mode' in frame:
        old &= frame['coil_mapping_mode'].ne('custom')
    if not old.any():
        return frame
    frame = frame.copy()
    frame.loc[old, 'Trim Coil 8'] = frame.loc[old, 'ch11']
    frame.loc[old, 'coil_mapping'] = ','.join(DEFAULT_COILS)
    print(f'Corrected TC8 to recorded ch11 in {int(old.sum())} historical cyclotron rows.', flush=True)
    return frame


def coil_label(frame, index):
    if index == 7 and 'coil_mapping' in frame and frame['coil_mapping'].eq(','.join(DEFAULT_COILS)).all():
        return 'TC8 ← TC11'
    return f'TC{index + 1}'


def embed(args, currents, np, umap, StandardScaler, return_model=False):
    scaler = None if args.no_standardize else StandardScaler().fit(currents)
    values = currents if scaler is None else scaler.transform(currents)
    if not np.any(np.std(values, axis=0) > 0):
        raise ValueError('Trim-coil settings have no variation')
    neighbors = min(args.neighbors, len(values) - 1)
    dimensions = 3 if getattr(args, 'third_axis', None) == 'umap' else 2
    print(f'Fitting {dimensions}D UMAP from exactly ten trim currents: neighbors={neighbors}, min_dist={args.min_dist}, seed={args.seed}.', flush=True)
    # Random initialization also handles small datasets without spectral rank errors.
    model = umap.UMAP(n_components=dimensions, n_neighbors=neighbors, min_dist=args.min_dist,
        metric='euclidean', random_state=args.seed, n_jobs=1, init='random')
    coordinates = model.fit_transform(values)
    return (coordinates, model, scaler) if return_model else coordinates


def plot(args, frame, title, three_dimensional, np):
    import matplotlib
    if args.no_show:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    plt.style.use('dark_background')
    fig = plt.figure(figsize=(11, 8), facecolor='#15191f')
    ax = fig.add_subplot(111, projection='3d' if three_dimensional else None)
    ax.set_facecolor('#15191f')
    trim_3d = three_dimensional and getattr(args, 'third_axis', None) == 'umap'
    visible = np.ones(len(frame), dtype=bool)
    if three_dimensional and not trim_3d:
        visible = np.isfinite(frame['main_magnet_value'].to_numpy())
        if not visible.any():
            raise ValueError(f'No finite main magnet values in {args.magnet_column!r}')
        if not visible.all():
            print(f'3D view omits {int((~visible).sum())} settings with missing magnet values; UMAP fit is unchanged.')
    shown = frame.loc[visible]
    measured = np.isfinite(shown['measured_beam_nA'].to_numpy())
    def coordinates(rows):
        result = [rows['UMAP 1'], rows['UMAP 2']]
        if three_dimensional:
            result.append(rows['UMAP 3'] if trim_3d else rows['main_magnet_value'])
        return result
    artists = []
    range_groups = []
    if measured.any():
        known = shown.loc[measured]
        all_beams = frame['measured_beam_nA'].to_numpy()
        all_beams = all_beams[np.isfinite(all_beams)]
        from matplotlib.colors import Normalize
        from matplotlib.cm import ScalarMappable
        norm = Normalize(float(all_beams.min()), float(all_beams.max()))
        for label, mask in beam_bands(known['measured_beam_nA'].to_numpy()):
            rows = known.loc[mask]
            if label == 'Negative beam' and rows.empty:
                continue
            artist = None
            if not rows.empty:
                artist = ax.scatter(*coordinates(rows), c=rows['measured_beam_nA'], cmap='viridis',
                                    marker='o', norm=norm,
                                    s=55, alpha=.95, edgecolors='#17202d', linewidths=.4)
                artists.append((artist, rows))
            range_groups.append((label, artist, rows))
        color_ax = fig.add_axes([.81, .23, .025, .34])
        fig.colorbar(ScalarMappable(norm=norm, cmap='viridis'), cax=color_ax,
                     label='Measured output beam current (nA)')
    if (~measured).any():
        unknown = shown.loc[~measured]
        artist = ax.scatter(*coordinates(unknown), c='#c2ccd9', marker='o', s=54, alpha=1.,
                            edgecolors='#17202d', linewidths=.5)
        artists.append((artist, unknown))
        range_groups.append(('Missing beam', artist, unknown))
        ax.legend(handles=[Line2D([], [], color='#c2ccd9', marker='o', linestyle='None',
                  label=f'Beam measurement missing ({len(unknown)})')], loc='upper right')
    ax.set_xlabel('UMAP 1', labelpad=10)
    ax.set_ylabel('UMAP 2', labelpad=10)
    if three_dimensional:
        for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
            axis.set_pane_color((.08, .10, .13, 1.))
        ax.set_zlabel('UMAP 3' if trim_3d else f'Main magnet current ({args.magnet_unit})', labelpad=12)
        ax.view_init(elev=25, azim=-60)
    else:
        ax.grid(alpha=.15)
        ax.set_aspect('equal', adjustable='datalim')
    ax.set_title('Trim-coil UMAP' + (' · 3D trim settings' if trim_3d else ' · main magnet height' if three_dimensional else '') + '\n' + title, pad=20)
    footer = ('Embedding uses only TC1–TC10; beam color and magnet height do not influence UMAP.\n'
              'Standardized per coil' if not args.no_standardize else
              'Embedding uses only TC1–TC10; beam color and magnet height do not influence UMAP.\nRaw current distances')
    footer += f' · seed {args.seed} · {len(frame)} settings · click a point for its source values'
    if coil_label(frame, 7) != 'TC8':
        footer += '\nTC8 uses recorded TC11 (ch11).'
    filters = []
    if 'beam_filter' in frame and frame['beam_filter'].nunique() == 1:
        filters.append(str(frame['beam_filter'].iloc[0]))
    if args.min_beam_na is not None:
        filters.append(f'beam > {args.min_beam_na:g} nA')
    if args.max_beam_na is not None:
        filters.append(f'beam <= {args.max_beam_na:g} nA')
    if args.beam_range_index is not None:
        filters.append(f'hardware range index {args.beam_range_index}')
    if filters:
        footer += '\nFilter: ' + '; '.join(dict.fromkeys(filters))
    if not measured.any():
        footer += '\nNo measured output beam data: gray points show settings only.'
    fig.text(.5, .025, footer, ha='center', va='bottom', fontsize=9, color='#b5bdc9')
    fig.subplots_adjust(bottom=.19, top=.88, left=.08, right=.76 if measured.any() else .9)
    if measured.any():
        add_beam_range_controls(fig, range_groups)
    # Picking works in both views, including after rotating the 3D projection.
    for artist, _ in artists:
        artist.set_picker(5)
    def picked(event):
        for artist, rows in artists:
            if event.artist is artist and artist.get_visible() and len(event.ind):
                row = rows.iloc[int(event.ind[0])]
                beam = f"{row['measured_beam_nA']:.4g} nA" if np.isfinite(row['measured_beam_nA']) else 'missing'
                detail = f"Source row {row['source_row']} · beam {beam} · main magnet {row['main_magnet_value']:.6g} {args.magnet_unit}"
                print(detail + '\n' + ', '.join(f'{column}={row[column]}' for column in COILS))
                ax.set_title('Trim-coil UMAP\n' + detail, fontsize=10, pad=20)
                fig.canvas.draw_idle()
                break
    fig.canvas.mpl_connect('pick_event', picked)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.save, dpi=180, facecolor=fig.get_facecolor())
        print(f'Saved plot: {args.save.resolve()}')
    if not args.no_show:
        plt.show()
    plt.close(fig)


def run(three_dimensional=False, argv=None):
    parser = arguments(three_dimensional)
    args = parser.parse_args(argv)
    if args.neighbors < 2 or not 0 <= args.min_dist <= 1 or not 0 <= args.seed <= 2**32 - 1:
        parser.error('neighbors must be >=2, min-dist in [0,1], and seed in [0, 2**32-1]')
    # Keep the requested `python script.py` entry points convenient without
    # installing experimental dependencies into the application's environment.
    local_python = HERE / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if argv is None and importlib.util.find_spec('umap') is None and local_python.is_file() and Path(sys.executable).resolve() != local_python.resolve():
        return subprocess.call([str(local_python), str(Path(sys.argv[0]).resolve()), *sys.argv[1:]])
    try:
        np, pd, umap, scaler = dependencies()
        frame, title = load_data(args, np, pd)
        frame, currents = prepare(args, frame, np, pd)
        coordinates = embed(args, currents, np, umap, scaler)
        frame['UMAP 1'], frame['UMAP 2'] = coordinates[:, 0], coordinates[:, 1]
        if coordinates.shape[1] == 3:
            frame['UMAP 3'] = coordinates[:, 2]
        plot(args, frame, title, three_dimensional, np)
        if args.export:
            args.export.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(args.export, index=False)
            print(f'Saved coordinates and source values: {args.export.resolve()}')
        return 0
    except (ValueError, OSError, ImportError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
