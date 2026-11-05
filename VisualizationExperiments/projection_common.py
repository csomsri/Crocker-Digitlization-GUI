"""Design experiments sharing exactly the UMAP input and beam parsing rules."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

from umap_common import HERE, COILS, arguments, load_data, prepare, display_beam_bands, add_beam_range_controls, coil_label


def run(method, argv=None):
    parser = arguments(False, method=method)
    parser.description = {'pca': 'PCA of ten trim currents; color is measured output beam.',
        'pacmap': 'PaCMAP of ten trim currents; color is measured output beam.',
        'parallel': 'Parallel coordinates of ten trim currents and measured output beam.'}[method]
    args = parser.parse_args(argv)
    if (method == 'pacmap' and args.neighbors < 2) or not 0 <= args.seed <= 2**32 - 1:
        parser.error('neighbors must be >=2 and seed in [0, 2**32-1]')
    local_python = HERE / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    required = ['numpy', 'pandas', 'matplotlib', 'sklearn']
    if args.data.suffix.lower() in ('.xlsx', '.xlsm'):
        required.append('openpyxl')
    if method == 'pacmap':
        required.append('pacmap')
    if argv is None and any(importlib.util.find_spec(m) is None for m in required) and local_python.is_file() and Path(sys.executable).resolve() != local_python.resolve():
        return subprocess.call([str(local_python), str(Path(sys.argv[0]).resolve()), *sys.argv[1:]])
    try:
        print('Loading visualization libraries...', flush=True)
        import numpy as np
        import pandas as pd
        from sklearn.preprocessing import StandardScaler
        import matplotlib
        if args.no_show:
            matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
        from matplotlib.colors import Normalize

        frame, source = load_data(args, np, pd)
        frame, currents = prepare(args, frame, np, pd)
        beam = frame['output_beam_nA'].to_numpy()
        known = np.isfinite(beam)
        norm = Normalize(float(beam[known].min()), float(beam[known].max())) if known.any() else None
        cmap = plt.get_cmap('viridis')
        colors = [cmap(norm(v)) if valid else '#aebac9' for v, valid in zip(beam, known)]
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(14, 8) if method == 'parallel' else (11, 8), facecolor='#15191f')
        ax.set_facecolor('#15191f')
        range_groups = []

        if method == 'parallel':
            columns = [*COILS, 'output_beam_nA']
            values = frame[columns].apply(pd.to_numeric, errors='coerce').to_numpy(dtype=float, copy=True)
            values[~np.isfinite(values)] = np.nan
            shown = values.copy()
            labels = []
            for index, column in enumerate(columns):
                finite = np.isfinite(values[:, index])
                name = coil_label(frame, index) if index < 10 else 'Output beam\n(nA)'
                if finite.any():
                    low, high = float(values[finite, index].min()), float(values[finite, index].max())
                    if not args.no_standardize:
                        shown[finite, index] = ((values[finite, index] - low) / (high - low)
                                                if high > low else .5)
                    labels.append(f'{name}\n{low:.4g}\nto {high:.4g}')
                else:
                    labels.append(name + '\nnot recorded')
                frame['parallel_' + column] = shown[:, index]
            artists = []
            for index, row in enumerate(shown):
                line, = ax.plot(np.arange(len(columns)), row, color=colors[index], alpha=.65,
                                linewidth=1.2, marker='o', markersize=2.8, picker=4)
                artists.append((line, index))
            for label, mask in display_beam_bands(beam, np):
                indices = np.flatnonzero(mask)
                range_groups.append((label, [artists[i][0] for i in indices], frame.iloc[indices]))
            ax.set_xticks(np.arange(len(columns)), labels, fontsize=8)
            for index in range(len(columns)):
                ax.axvline(index, color='#8c96a5', alpha=.2, linewidth=.7)
            ax.set_xlim(-.2, len(columns) - .8)
            if not args.no_standardize:
                ax.set_ylim(-.04, 1.04)
            ax.set_ylabel('Raw recorded values' if args.no_standardize else 'Per-axis min–max scale (0–1)')
            ax.set_title('Parallel coordinates · trim coils and measured beam\n' + source, pad=20)
            footer = 'Each line is one acquisition; ranges beneath axes are original recorded values.\n'
            footer += 'Missing values break the line; no output-beam values are imputed. Constant axes map to 0.5.'
        else:
            values = currents if args.no_standardize else StandardScaler().fit_transform(currents)
            if method == 'pca':
                from sklearn.decomposition import PCA
                reducer = PCA(n_components=2, svd_solver='full')
                coordinates = reducer.fit_transform(values)
                variance = reducer.explained_variance_ratio_ * 100
                names = ['PC 1', 'PC 2']
                labels = [f'{name} ({v:.1f}% explained variance)' for name, v in zip(names, variance)]
                print(f'PCA explained variance: PC1={variance[0]:.2f}%, PC2={variance[1]:.2f}%, total={variance.sum():.2f}%.')
            else:
                from numba import set_num_threads
                set_num_threads(1)  # Small experimental datasets; avoid thread overhead.
                import pacmap
                # Far pairs need points outside each local neighborhood. Reserve
                # room for them explicitly on this small run-sheet sample.
                neighbors = min(args.neighbors, max(2, (len(frame) - 2) // 3))
                if len(frame) < 6:
                    raise ValueError('PaCMAP requires at least six complete settings in this experiment')
                reducer = pacmap.PaCMAP(n_components=2, n_neighbors=neighbors,
                    MN_ratio=.5, FP_ratio=2., random_state=args.seed, apply_pca=False)
                print(f'Fitting PaCMAP from ten trim currents; neighbors={neighbors}, seed={args.seed}.', flush=True)
                coordinates = reducer.fit_transform(values.astype(np.float32), init='pca')
                names = labels = ['PaCMAP 1', 'PaCMAP 2']
            for index, name in enumerate(names):
                frame[name] = coordinates[:, index]
            artists = []
            for label, mask in display_beam_bands(beam, np):
                color = '#aebac9' if label == 'Missing beam' else None
                artist = None
                if mask.any():
                    artist = ax.scatter(coordinates[mask, 0], coordinates[mask, 1],
                        c=beam[mask] if color is None else color,
                        **({'cmap': cmap, 'norm': norm} if color is None else {}),
                        marker='o', s=58, edgecolors='#17202d', linewidths=.5, picker=5)
                    artists.append((artist, np.flatnonzero(mask)))
                range_groups.append((label, artist, frame.loc[mask]))
            ax.set_xlabel(labels[0], labelpad=12)
            ax.set_ylabel(labels[1], labelpad=12)
            ax.set_aspect('equal', adjustable='datalim')
            ax.set_title(('PCA' if method == 'pca' else 'PaCMAP') + ' · ten trim-coil currents\n' + source, pad=20)
            footer = ('Only TC1–TC10 determine the coordinates; main magnet and beam are not projection inputs.\n'
                      + ('Raw currents' if args.no_standardize else 'Standardized per coil'))

        if known.any():
            fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), cax=fig.add_axes([.81, .25, .025, .32]),
                         label='Measured output beam current (nA)')
        if (~known).any():
            ax.legend(handles=[Line2D([], [], marker='o', color='#aebac9', linestyle='None',
                      label=f'Output beam missing ({int((~known).sum())})')], loc='upper right')
        ax.grid(axis='y' if method == 'parallel' else 'both', alpha=.15)
        footer += f' · {len(frame)} settings · click a point/line for its source values'
        if coil_label(frame, 7) != 'TC8':
            footer += '\nTC8 uses recorded TC11 (ch11).'
        if not known.any():
            footer += '\nNo output-beam values with confirmed units are available; points are gray.'
        fig.text(.5, .025, footer, ha='center', va='bottom', fontsize=9, color='#b5bdc9')
        fig.subplots_adjust(bottom=.22 if method == 'parallel' else .16, top=.88, left=.08, right=.75)
        add_beam_range_controls(fig, range_groups)

        def picked(event):
            for artist, index in artists:
                if event.artist is artist and artist.get_visible():
                    if method != 'parallel':
                        if not len(event.ind):
                            return
                        index = int(index[int(event.ind[0])])
                    row = frame.iloc[index]
                    print(f"Source row {row['source_row']}: " + ', '.join(f'{key}={row[key]}' for key in COILS)
                          + f"; output beam={row['output_beam_nA']} nA; main magnet={row['main_magnet_value']}")
                    break
        fig.canvas.mpl_connect('pick_event', picked)
        if args.save:
            args.save.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(args.save, dpi=180, facecolor=fig.get_facecolor())
            print(f'Saved plot: {args.save.resolve()}')
        if args.export:
            args.export.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(args.export, index=False)
            print(f'Saved data: {args.export.resolve()}')
        if not args.no_show:
            plt.show()
        plt.close(fig)
        return 0
    except (ValueError, OSError, ImportError) as exc:
        print(f'Error: {exc}\nInstall dependencies with: python -m pip install -r "{HERE / "requirements.txt"}"', file=sys.stderr)
        return 1
