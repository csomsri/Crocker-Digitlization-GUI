"""Circle two UMAP clusters and project next-setting regression predictions."""
from pathlib import Path
import importlib.util
import json
import os
import subprocess
import sys

from umap_common import HERE, BEAM_DATA, COILS, arguments, dependencies, load_data, prepare, embed, display_beam_bands, add_beam_range_controls

COLORS = {'A': '#4bb8ff', 'B': '#ffb454', 'C': '#e783ff'}


def next_setting(currents, np):
    """Multi-output linear trend over within-dataset run-sheet position."""
    from sklearn.linear_model import LinearRegression

    if len(currents) < 3:
        raise ValueError('Each group requires at least three settings for regression')
    position = np.arange(len(currents), dtype=float).reshape(-1, 1)
    model = LinearRegression().fit(position, currents)
    prediction = model.predict([[len(currents)]])[0]
    # A forward holdout evaluates prediction rather than reporting training fit.
    split = max(2, int(.8 * len(currents)))
    validation = LinearRegression().fit(position[:split], currents[:split])
    error = validation.predict(position[split:]) - currents[split:]
    metrics = {
        'rows': len(currents), 'validation_training_rows': split,
        'validation_rows': len(currents) - split,
        'holdout_mae_per_coil': dict(zip(COILS, np.mean(np.abs(error), axis=0).tolist())),
        'slope_per_position': dict(zip(COILS, model.coef_[:, 0].tolist())),
        'intercept': dict(zip(COILS, model.intercept_.tolist())),
    }
    return prediction, metrics


def next_setting_gp(currents, np, seed=42):
    """Independent normalized GP per coil; tune kernels using training rows only."""
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, RBF, WhiteKernel
    from sklearn.preprocessing import StandardScaler

    if len(currents) < 3:
        raise ValueError('Each group requires at least three settings for regression')
    n = len(currents)
    split = max(2, int(.8 * n))
    position = np.arange(n, dtype=float).reshape(-1, 1)
    def fit(y, t):
        scale = StandardScaler().fit(t)
        kernel = ConstantKernel(1., (.01, 100.)) * RBF(1., (.05, 20.)) + WhiteKernel(.1, (1e-5, 10.))
        model = GaussianProcessRegressor(kernel=kernel, normalize_y=True,
                    n_restarts_optimizer=2, random_state=seed, alpha=1e-8)
        model.fit(scale.transform(t), y)
        return model, scale
    predictions, errors, stds, details = [], [], [], {}
    for i, coil in enumerate(COILS):
        validation, vs = fit(currents[:split, i], position[:split])
        error = validation.predict(vs.transform(position[split:])) - currents[split:, i]
        errors.append(float(np.abs(error).mean()))
        model, scale = fit(currents[:, i], position)
        mean, std = model.predict(scale.transform([[n]]), return_std=True)
        predictions.append(float(mean[0]))
        stds.append(float(std[0]))
        details[coil] = {'kernel': str(model.kernel_), 'input_mean': float(scale.mean_[0]),
            'input_scale': float(scale.scale_[0]), 'target_mean': float(np.mean(currents[:, i])),
            'target_scale': float(np.std(currents[:, i])) or 1.,
            'dual_weights': model.alpha_.tolist(), 'prediction_std': float(std[0]),
            'prediction_95_lower': float(mean[0] - 1.96 * std[0]),
            'prediction_95_upper': float(mean[0] + 1.96 * std[0])}
    return np.asarray(predictions), {'rows': n, 'validation_training_rows': split,
        'validation_rows': n - split, 'holdout_mae_per_coil': dict(zip(COILS, errors)),
        'prediction_std_per_coil': dict(zip(COILS, stds)), 'coils': details}


def run(argv=None):
    parser = arguments(False)
    parser.description = __doc__
    parser.add_argument('--model', choices=['linear', 'gp'], default='linear')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--hide-regression', action='store_true', help='Start with prediction stars hidden')
    args = parser.parse_args(argv)
    output_root = HERE / 'outputs' / 'cyclotron' if args.data.resolve() == BEAM_DATA.resolve() else HERE / 'outputs'
    args.output_dir = args.output_dir or output_root / ('group_gp' if args.model == 'gp' else 'group_regression')
    local_python = HERE / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if argv is None and importlib.util.find_spec('umap') is None and local_python.is_file():
        return subprocess.call([str(local_python), str(Path(__file__).resolve()), *sys.argv[1:]])
    if args.neighbors < 2 or not 0 <= args.min_dist <= 1 or not 0 <= args.seed <= 2**32 - 1:
        parser.error('neighbors must be >=2, min-dist in [0,1], seed in [0, 2**32-1]')
    try:
        np, pd, umap, scaler_type = dependencies()
        from sklearn.cluster import KMeans
        frame, title = load_data(args, np, pd)
        frame, currents = prepare(args, frame, np, pd)
        coordinates, reducer, scaler = embed(args, currents, np, umap, scaler_type, return_model=True)
        clusters = KMeans(n_clusters=2, random_state=args.seed, n_init=20).fit(coordinates)
        # Stable labels: A is the leftmost centroid in this embedding.
        left = int(np.argmin(clusters.cluster_centers_[:, 0]))
        labels = np.where(clusters.labels_ == left, 'A', 'B')
        frame['group'] = labels
        frame['UMAP 1'], frame['UMAP 2'] = coordinates.T
        frame['sequence_position'] = np.arange(len(frame))
        predictions, reports = [], {}
        for group in ('A', 'B', 'C'):
            mask = np.ones(len(frame), dtype=bool) if group == 'C' else labels == group
            prediction, reports[group] = (next_setting_gp(currents[mask], np, args.seed)
                if args.model == 'gp' else next_setting(currents[mask], np))
            predictions.append(prediction)
        predicted = np.asarray(predictions)
        transformed = reducer.transform(predicted if scaler is None else scaler.transform(predicted))
        result = pd.DataFrame(predicted, columns=COILS)
        result.insert(0, 'model', ['A', 'B', 'C'])
        result['UMAP 1'], result['UMAP 2'] = transformed.T
        result['point_type'] = 'predicted next setting; not measured'
        if args.model == 'gp':
            for coil in COILS:
                result[coil + ' std'] = [reports[g]['prediction_std_per_coil'][coil] for g in ('A', 'B', 'C')]
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for group in ('A', 'B'):
            frame.loc[labels == group].to_csv(args.output_dir / f'group_{group}.csv', index=False)
        frame.to_csv(args.export or args.output_dir / 'all_settings.csv', index=False)
        result.to_csv(args.output_dir / 'predictions.csv', index=False)
        reports['method'] = ('KMeans on 2D UMAP; ' + ('independent per-coil Gaussian processes (constant * RBF + white noise), normalized targets and standardized row positions; ' if args.model == 'gp' else 'multi-output ordinary least squares; ') + 'regression versus '
                             'within-dataset row position; predict position n after positions 0..n-1. '
                             'Input order is preserved, not sorted by date. C uses all rows. '
                             'Predictions use the original fitted scaler and UMAP transform.')
        (args.output_dir / 'regression_report.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
        equations = gp_text(reports) if args.model == 'gp' else equation_text(reports)
        (args.output_dir / ('gp_details.txt' if args.model == 'gp' else 'linear_equations.txt')).write_text(equations, encoding='utf-8')
        print(equations)
        draw(args, frame, result, title, np, equations)
        print(result.to_string(index=False))
        print(f'Wrote datasets, predictions, report and figure to {args.output_dir.resolve()}')
        return 0
    except (ValueError, OSError, ImportError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1


def equation_text(reports):
    lines = ['Linear combination: predicted coil vector = intercept vector + t * slope vector.',
             't is position within each dataset (0-based), not time or another coil current.',
             'Each coil has its own equation; the UMAP projection is nonlinear.', '']
    for group in ('A', 'B', 'C'):
        report = reports[group]
        n = report['rows']
        lines.append(f'Model {group}' + (' (all data)' if group == 'C' else '') + f': next t = {n}')
        for i, coil in enumerate(COILS, 1):
            intercept, slope = report['intercept'][coil], report['slope_per_position'][coil]
            lines.append(f'TC{i:2d} = {intercept:12.6f} {slope:+12.6f} * t   => {intercept + n * slope:12.6f}')
        lines.append('')
    return '\n'.join(lines)


def gp_text(reports):
    lines = ['GP mean = target_mean + target_scale * sum_i k_signal(z, z_i) * weight_i',
             'z = standardized row position. Learned kernels and weights are in regression_report.json.',
             'Intervals: marginal predictive mean +/- 1.96 std, including fitted white noise.',
             'These are coil-space intervals, not UMAP confidence regions.', '']
    for group in ('A', 'B', 'C'):
        lines.append(f'Model {group}: next row position t = {reports[group]["rows"]}')
        for i, coil in enumerate(COILS, 1):
            d = reports[group]['coils'][coil]
            lines.append(f'TC{i:2d}: 95% [{d["prediction_95_lower"]:10.3f}, {d["prediction_95_upper"]:10.3f}]  std={d["prediction_std"]:.3f}')
        lines.append('')
    return '\n'.join(lines)


def draw(args, frame, predictions, title, np, equations):
    import matplotlib
    if args.no_show:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    from matplotlib.cm import ScalarMappable
    from matplotlib.lines import Line2D
    from matplotlib.patches import Circle
    from matplotlib.widgets import CheckButtons, Button
    is_gp = getattr(args, 'model', 'linear') == 'gp'
    model_label = 'Gaussian process' if is_gp else 'Linear'
    detail_label = 'GP details' if is_gp else 'linear equations'
    detail_file = 'gp_details.png' if is_gp else 'linear_equations.png'

    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(12, 9), facecolor='#15191f')
    ax.set_facecolor('#15191f')
    beam = frame['output_beam_nA'].to_numpy()
    finite = np.isfinite(beam)
    norm = Normalize(float(beam[finite].min()), float(beam[finite].max())) if finite.any() else None
    bands = display_beam_bands(beam, np)
    range_groups = [(label, [], frame.loc[mask]) for label, mask in bands]
    group_handles = []
    for group in ('A', 'B'):
        group_mask = frame['group'].to_numpy() == group
        points = frame.loc[group_mask, ['UMAP 1', 'UMAP 2']].to_numpy()
        center = points.mean(axis=0)
        radius = max(float(np.linalg.norm(points - center, axis=1).max()) * 1.10, .2)
        for band_group, (label, band_mask) in zip(range_groups, bands):
            mask = group_mask & band_mask
            if mask.any():
                rows = frame.loc[mask]
                band_group[1].append(ax.scatter(rows['UMAP 1'], rows['UMAP 2'],
                    c=beam[mask] if label != 'Missing beam' else '#aebac9',
                    **({'cmap': 'viridis', 'norm': norm} if label != 'Missing beam' else {}),
                    edgecolors=COLORS[group], linewidths=.4, s=48, alpha=.8))
        group_handles.append(Line2D([], [], color=COLORS[group], marker='o', linestyle='None',
                                   label=f'Group {group} ({len(points)} settings)'))
        ax.add_patch(Circle(center, radius, fill=False, color=COLORS[group], linewidth=2))
        ax.annotate(f'Group {group}', center + [0, radius], xytext=(0, 8),
                    textcoords='offset points', ha='center', color=COLORS[group], weight='bold')
    prediction_artists = []
    for _, row in predictions.iterrows():
        group = row['model']
        xy = (row['UMAP 1'], row['UMAP 2'])
        prediction_artists.append(ax.scatter(*xy, c=COLORS[group], s=260, marker='*', edgecolors='white', linewidths=1,
                   zorder=5, label=f'{group}: next prediction' + (' (all data)' if group == 'C' else '')))
        offset = {'A': (12, 15), 'B': (12, -22), 'C': (-100, 22)}[group]
        if is_gp and group == 'A':
            offset = (12, -25)
        prediction_artists.append(ax.annotate(f'{group} prediction', xy, xytext=offset, textcoords='offset points',
                    color=COLORS[group], arrowprops={'arrowstyle': '-', 'color': COLORS[group]}))
    ax.set(xlabel='UMAP 1', ylabel='UMAP 2', title=f'Trim-coil groups and next-setting regression\n{title}')
    ax.set_aspect('equal', adjustable='datalim')
    ax.margins(.18)
    ax.grid(alpha=.15)
    def set_predictions(visible):
        for artist in prediction_artists:
            artist.set_visible(visible)
        handles = group_handles + (prediction_artists[::2] if visible else [])
        ax.legend(handles=handles, loc='best', fontsize=9)
        ax.set_title(f'Trim-coil groups' + (f' and {model_label.lower()} predictions' if visible else '') + f'\n{title}')
        fig.canvas.draw_idle()

    set_predictions(True)
    fig.text(.5, .025, model_label + ' regression of TC1–TC10 versus within-dataset row position. Input order retained.\n'
             'Stars are predicted settings, not measurements or optimized machine recommendations.\n'
             'Range toggles filter measurements only; models, cluster circles and unmeasured predictions stay fixed.',
             ha='center', fontsize=9, color='#b5bdc9')
    fig.subplots_adjust(bottom=.20, top=.89, right=.75)
    add_beam_range_controls(fig, range_groups)
    if finite.any():
        fig.colorbar(ScalarMappable(norm=norm, cmap='viridis'), cax=fig.add_axes([.81,.23,.025,.34]), label='Measured beam (nA)')
    path = args.save or args.output_dir / 'umap_group_regression.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, facecolor=fig.get_facecolor())
    set_predictions(False)
    fig.savefig(path.with_name(path.stem + '_without_regression' + path.suffix), dpi=180, facecolor=fig.get_facecolor())
    set_predictions(not args.hide_regression)
    equation_fig = plt.figure(figsize=(12, 11), facecolor='#15191f')
    equation_fig.text(.04, .97, equations, va='top', fontfamily='monospace', fontsize=10, color='white')
    equation_fig.savefig(args.output_dir / detail_file, dpi=160, facecolor=equation_fig.get_facecolor())
    if not args.no_show:
        plt.close(equation_fig)
        controls = CheckButtons(fig.add_axes([.08, .105, .25, .04]), ['Show regression'], [not args.hide_regression])
        controls.on_clicked(lambda _: set_predictions(controls.get_status()[0]))
        button = Button(fig.add_axes([.64, .105, .27, .04]), 'Show ' + detail_label)
        def show_equations(_):
            detail = plt.figure(figsize=(12, 11), facecolor='#15191f')
            detail.text(.04, .97, equations, va='top', fontfamily='monospace', fontsize=10, color='white')
            detail.show()
        button.on_clicked(show_equations)
        plt.show()
    plt.close(equation_fig)
    plt.close(fig)


if __name__ == '__main__':
    raise SystemExit(run())
