"""Show measured beam versus each of the ten recorded trim-coil settings."""
from pathlib import Path
import sys

from umap_common import arguments, load_data, prepare, COILS, display_beam_bands, add_beam_range_controls, coil_label


def run(argv=None):
    parser = arguments(False, method='scatter')
    parser.description = __doc__
    args = parser.parse_args(argv)
    try:
        import numpy as np
        import pandas as pd
        import matplotlib
        if args.no_show:
            matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        args.require_beam = True
        frame, source = load_data(args, np, pd)
        frame, currents = prepare(args, frame, np, pd)
        beam = frame['output_beam_nA'].to_numpy()
        valid = np.isfinite(beam)
        plt.style.use('dark_background')
        fig, axes = plt.subplots(2, 5, figsize=(17, 8), sharey=True, facecolor='#15191f')
        from matplotlib.colors import Normalize
        from matplotlib.cm import ScalarMappable
        norm = Normalize(float(beam[valid].min()), float(beam[valid].max()))
        bands = [(label, mask) for label, mask in display_beam_bands(beam, np) if label != 'Missing beam']
        groups = [(label, [], frame.loc[mask]) for label, mask in bands]
        for i, ax in enumerate(axes.flat):
            ax.set_facecolor('#15191f')
            for group, (_, mask) in zip(groups, bands):
                mask = mask & valid
                if mask.any():
                    group[1].append(ax.scatter(currents[mask, i], beam[mask], c=beam[mask],
                                 norm=norm, cmap='viridis', s=8, alpha=.55, linewidths=0))
            ax.set_xlabel(f'{coil_label(frame, i)} (recorded units)')
            ax.grid(alpha=.15)
            if i in (0, 5):
                ax.set_ylabel('Calibrated beam (nA)')
        fig.subplots_adjust(left=.06, right=.75, bottom=.10, top=.82, wspace=.25, hspace=.30)
        fig.colorbar(ScalarMappable(norm=norm, cmap='viridis'), cax=fig.add_axes([.81,.23,.025,.34]), label='Calibrated beam (nA)')
        add_beam_range_controls(fig, groups)
        description = f'{len(frame)} sampled acquisitions; other coils vary simultaneously'
        if 'beam_filter' in frame and frame['beam_filter'].nunique() == 1:
            description += ' · ' + str(frame['beam_filter'].iloc[0])
        fig.suptitle('Beam distribution versus trim-coil settings\n' + source + '\n' + description)
        if args.save:
            args.save.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(args.save, dpi=180)
            print(f'Saved plot: {args.save.resolve()}')
        if args.export:
            args.export.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(args.export, index=False)
        if not args.no_show:
            plt.show()
        plt.close(fig)
        return 0
    except (ValueError, OSError, ImportError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(run())
