"""Offline finite-archive noisy BO replay. Never sends machine commands."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
import torch
from botorch.acquisition.logei import qLogNoisyExpectedImprovement
from botorch.fit import fit_gpytorch_mll
from botorch.models import SingleTaskGP
from botorch.models.transforms import Standardize
from botorch.sampling.normal import SobolQMCNormalSampler
from gpytorch.mlls import ExactMarginalLogLikelihood
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from umap_common import BEAM_DATA, COILS, correct_cyclotron_mapping


def fit_model(x, y):
    model = SingleTaskGP(x, y, outcome_transform=Standardize(m=1))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        fit_gpytorch_mll(ExactMarginalLogLikelihood(model.likelihood, model),
                        optimizer_kwargs={'options': {'maxiter': 60}})
    model.eval()
    return model, [str(w.message) for w in caught]


def posterior(model, x):
    with torch.no_grad():
        latent = model.posterior(x)
        observed = model.posterior(x, observation_noise=True)
        return (latent.mean.squeeze(-1).cpu().numpy(),
                latent.variance.clamp_min(0).sqrt().squeeze(-1).cpu().numpy(),
                observed.variance.clamp_min(0).sqrt().squeeze(-1).cpu().numpy())


def propose(model, x, seen, seed):
    remaining = np.setdiff1d(np.arange(len(x)), seen)
    acquisition = qLogNoisyExpectedImprovement(model=model, X_baseline=x[seen],
        sampler=SobolQMCNormalSampler(sample_shape=torch.Size([64]), seed=seed), prune_baseline=True)
    with torch.no_grad():
        values = torch.cat([acquisition(x[batch].unsqueeze(1))
                            for batch in np.array_split(remaining, max(1, int(np.ceil(len(remaining) / 64))))])
    return int(remaining[int(values.argmax())]), float(values.max())


def replay(x, y, source_rows, initial=24, steps=20, seed=0):
    """Only revealed y values enter fitting/acquisition; labels stay hidden otherwise."""
    if len(x) < initial + steps + 1:
        raise ValueError('Archive must exceed initial points plus query budget')
    rng = np.random.default_rng(seed)
    seen = rng.choice(len(x), initial, replace=False).tolist()
    starting = seen.copy()
    random_order = rng.permutation(np.setdiff1d(np.arange(len(x)), seen))[:steps]
    initial_best = float(y[seen].max())
    records, messages = [], []
    with torch.random.fork_rng():
        torch.manual_seed(seed)
        for step in range(steps):
            model, notes = fit_model(x[seen], y[seen])
            messages.extend(notes)
            selected, acquisition = propose(model, x, seen, seed + step)
            mean, latent_std, obs_std = posterior(model, x[[selected]])
            # Reveal exactly one archived reading, not a model-generated response.
            seen.append(selected)
            records.append({'seed': seed, 'step': step + 1, 'source_row': int(source_rows[selected]),
                'archive_index': selected, 'predicted_mean_nA': float(mean[0]),
                'latent_std_nA': float(latent_std[0]), 'observation_std_nA': float(obs_std[0]),
                'mean_95_lower_nA': float(mean[0] - 1.96 * latent_std[0]),
                'mean_95_upper_nA': float(mean[0] + 1.96 * latent_std[0]),
                'reading_95_lower_nA': float(mean[0] - 1.96 * obs_std[0]),
                'reading_95_upper_nA': float(mean[0] + 1.96 * obs_std[0]),
                'revealed_archived_beam_nA': float(y[selected].item()),
                'bo_best_nA': float(y[seen].max()),
                'random_best_nA': max(initial_best, float(y[random_order[:step+1]].max())),
                'initial_best_nA': initial_best, 'log_nei': acquisition})
            print(f'Seed {seed}, query {step+1}/{steps}: recorded {y[selected].item():.3f} nA; best {y[seen].max().item():.3f} nA', flush=True)
        model, notes = fit_model(x[seen], y[seen])
        messages.extend(notes)
        next_index, log_nei = propose(model, x, seen, seed + steps)
        mean, latent_std, obs_std = posterior(model, x)
    recommendation = {'source_row': int(source_rows[next_index]), 'archive_index': next_index,
        'predicted_mean_nA': float(mean[next_index]), 'latent_std_nA': float(latent_std[next_index]),
        'observation_std_nA': float(obs_std[next_index]),
        'mean_95_interval_nA': [float(mean[next_index] - 1.96 * latent_std[next_index]), float(mean[next_index] + 1.96 * latent_std[next_index])],
        'reading_95_interval_nA': [float(mean[next_index] - 1.96 * obs_std[next_index]), float(mean[next_index] + 1.96 * obs_std[next_index])],
        'log_nei': log_nei, 'status': 'next archive query; not an optimized or verified machine setting'}
    return records, recommendation, (mean, latent_std, obs_std), seen, starting, messages


def draw(pool, normalized, runs, final, recommendation, seen, starting, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.style.use('dark_background')
    fig, axes = plt.subplots(2, 2, figsize=(15, 10), layout='constrained')
    colors = {'bo_best_nA': '#60c9ff', 'random_best_nA': '#ffb454'}
    ax = axes[0, 0]
    for name, color in colors.items():
        curves = np.array([[r['initial_best_nA'] for r in run[:1]] + [r[name] for r in run] for run in runs])
        positions = np.arange(curves.shape[1])
        ax.plot(positions, np.median(curves, axis=0), color=color, label='BO' if name.startswith('bo') else 'Random')
        ax.fill_between(positions, curves.min(axis=0), curves.max(axis=0), color=color, alpha=.15)
    ax.axhline(pool.output_beam_nA.max(), color='white', ls=':', label='Best archived reading')
    ax.set(xlabel='Revealed archive readings after shared initial data', ylabel='Best recorded beam (nA)', title=f'Retrospective search · median and min–max of {len(runs)} seeds')
    ax.legend(fontsize=8)
    ax = axes[0, 1]
    run = pd.DataFrame(runs[0])
    ax.errorbar(run.step, run.predicted_mean_nA, yerr=1.96 * run.observation_std_nA,
                fmt='none', ecolor='#a0b3cb', alpha=.45, label='Nominal 95% interval: individual reading')
    ax.errorbar(run.step, run.predicted_mean_nA, yerr=1.96 * run.latent_std_nA,
                fmt='o', color='#60c9ff', ms=3, label='GP mean and nominal 95% latent interval')
    ax.scatter(run.step, run.revealed_archived_beam_nA, color='#ffb454', s=18, zorder=4, label='Revealed historical reading')
    ax.set(xlabel='BO query (first seed)', ylabel='Beam (nA)', title='Uncertainty before revealing each reading')
    ax.legend(fontsize=7)
    ax = axes[1, 0]
    xy = PCA(n_components=2).fit_transform(StandardScaler().fit_transform(normalized))
    scatter = ax.scatter(*xy.T, c=final[0], s=12 + 25 * final[1], cmap='viridis', alpha=.8)
    ax.scatter(*xy[seen].T, s=45, facecolors='none', edgecolors='white', linewidths=.7, label='Revealed points')
    ni = recommendation['archive_index']
    ax.scatter(*xy[ni], marker='*', s=200, color='#ffb454', edgecolors='white', label='Next archive query')
    ax.set(xlabel='PC1 of coil settings', ylabel='PC2 of coil settings', title='Final GP · color: mean; size: latent uncertainty')
    fig.colorbar(scatter, ax=ax, label='Predicted mean beam (nA)', shrink=.8)
    ax.legend(fontsize=7)
    ax = axes[1, 1]
    best = seen[int(np.argmax(pool.output_beam_nA.to_numpy()[seen]))]
    for values, label, color in [(normalized[starting].mean(axis=0), 'Initial average', '#a0b3cb'),
                                  (normalized[best], 'Best revealed reading', '#60c9ff'),
                                  (normalized[ni], 'Next archive query', '#ffb454')]:
        ax.plot(np.arange(10), values, 'o-', color=color, label=label, ms=4)
    ax.set_xticks(np.arange(10), ['TC1','TC2','TC3','TC4','TC5','TC6','TC7','TC8←11','TC9','TC10'])
    ax.set(ylabel='Recorded coil value normalized to archive range', title='Setting comparison · recorded values, not hardware commands')
    ax.legend(fontsize=8)
    for ax in axes.flat:
        ax.grid(alpha=.15)
    all_records = pd.DataFrame([record for run in runs for record in run])
    coverage = ((all_records.revealed_archived_beam_nA >= all_records.reading_95_lower_nA) &
                (all_records.revealed_archived_beam_nA <= all_records.reading_95_upper_nA)).mean()
    fig.suptitle('Historical-data Bayesian optimization replay · qLogNoisyExpectedImprovement\n'
                 f'Archive search only · nominal 95% reading intervals covered {coverage:.0%} of revealed readings', fontsize=13)
    fig.savefig(path, dpi=170)
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=BEAM_DATA)
    parser.add_argument('--pool-size', type=int, default=600)
    parser.add_argument('--initial', type=int, default=24)
    parser.add_argument('--steps', type=int, default=20)
    parser.add_argument('--seeds', type=int, default=5)
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent / 'outputs/cyclotron/historical_bo')
    args = parser.parse_args(argv)
    if args.initial < 2 or args.steps < 1 or args.seeds < 1 or args.pool_size <= args.initial + args.steps:
        parser.error('Need initial >=2, steps/seeds >=1, and pool-size > initial + steps')
    torch.set_num_threads(1)
    frame = correct_cyclotron_mapping(pd.read_csv(args.data)).sort_values(['timestamp', 'source_row']).reset_index(drop=True)
    valid = np.isfinite(frame[[*COILS, 'output_beam_nA']].to_numpy(float)).all(axis=1)
    frame = frame.loc[valid].reset_index(drop=True)
    if len(frame) <= args.initial + args.steps:
        raise ValueError('Not enough complete archived readings for the requested replay')
    selected = np.unique(np.linspace(0, len(frame)-1, min(args.pool_size, len(frame))).round().astype(int))
    pool = frame.iloc[selected].reset_index(drop=True)
    values = pool[COILS].to_numpy(float)
    low, high = values.min(axis=0), values.max(axis=0)
    active = high > low
    if not active.any():
        raise ValueError('No varying trim-coil inputs')
    normalized = np.divide(values-low, high-low, out=np.zeros_like(values), where=active)
    x = torch.tensor(normalized[:, active], dtype=torch.double)
    y = torch.tensor(pool[['output_beam_nA']].to_numpy(float), dtype=torch.double)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    audit = pd.DataFrame({'coil': COILS, 'raw_min': low, 'raw_max': high,
                         'raw_std': values.std(axis=0), 'active_in_model': active,
                         'correlation_with_beam': [float(np.corrcoef(values[:, i], y[:, 0])[0, 1]) if active[i] else None for i in range(10)]})
    audit.to_csv(args.output_dir / 'scaling_audit.csv', index=False)
    pool.to_csv(args.output_dir / 'archive_pool.csv', index=False)
    runs, recommendations, warnings_seen = [], [], []
    with threadpool_limits(limits=1):
        for seed in range(args.seeds):
            records, recommendation, final, seen, starting, notes = replay(x, y, pool.source_row.to_numpy(), args.initial, args.steps, seed)
            runs.append(records)
            recommendations.append(recommendation)
            warnings_seen.extend(notes)
            pd.DataFrame([row for run in runs for row in run]).to_csv(args.output_dir / 'replay.csv', index=False)
            if seed == 0:
                first_final, first_seen, first_start = final, seen, starting
    summary = {'method': 'finite archived-candidate qLogNEI replay with learned homoskedastic noise',
        'data': str(args.data.resolve()), 'coil_mapping': pool.coil_mapping.iloc[0], 'pool_size': len(pool),
        'initial_readings_per_seed': args.initial, 'additional_queries_per_seed': args.steps, 'seeds': args.seeds,
        'constant_coils_excluded': [c for c, use in zip(COILS, active) if not use],
        'best_reading_in_archive_nA': float(y.max()),
        'bo_final_best_nA': [run[-1]['bo_best_nA'] for run in runs],
        'random_final_best_nA': [run[-1]['random_best_nA'] for run in runs],
        'initial_best_nA': [run[0]['initial_best_nA'] for run in runs],
        'next_archive_queries': recommendations, 'fit_warnings': sorted(set(warnings_seen)),
        'limitations': ['Historical readings are noisy, time-confounded observations, not repeatable evaluations of coil settings.',
                        'This is archive-search replay, not evidence of live-machine improvement.',
                        'Only observed candidate combinations are searched; there is no optimization outside archive support.',
                        'Intervals are conditional on the GP model and historical calibration, not guaranteed physical bounds.',
                        'The replay selects acquisition timestamps, not independently randomized experiments.']}
    for field in ('bo_final_best_nA', 'random_final_best_nA', 'initial_best_nA'):
        summary[field + '_mean'] = float(np.mean(summary[field]))
    summary['bo_wins_over_random'] = int(np.sum(np.array(summary['bo_final_best_nA']) > summary['random_final_best_nA']))
    records = pd.DataFrame([record for run in runs for record in run])
    summary['nominal_95_reading_interval_coverage'] = float(((records.revealed_archived_beam_nA >= records.reading_95_lower_nA) &
                                                          (records.revealed_archived_beam_nA <= records.reading_95_upper_nA)).mean())
    gains = np.array([1,1000,.01,10,2,100,.5,50,1e4,.1])
    standardized = StandardScaler().fit_transform(values)
    transformed = StandardScaler().fit_transform(values * gains + 10)
    summary['affine_scaling_invariance_max_difference'] = float(np.abs(standardized - transformed).max())
    summary['sampled_beam_lag1_correlation'] = float(frame.output_beam_nA.autocorr())
    (args.output_dir / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')
    write_report(summary, args.output_dir)
    next_rows = pool.iloc[[r['archive_index'] for r in recommendations]][COILS].copy()
    next_rows.insert(0, 'seed', np.arange(args.seeds))
    next_rows.to_csv(args.output_dir / 'next_archive_settings.csv', index=False)
    draw(pool, normalized, runs, first_final, recommendations[0], first_seen, first_start, args.output_dir / 'historical_bo.png')
    print(json.dumps(summary, indent=2), flush=True)
    return 0


def write_report(summary, output_dir):
    lines = ['# Historical-data Bayesian optimization', '',
        'This is a finite-archive replay, not a machine experiment. Corrected physical TC8 uses recorded ch11.', '',
        f'Archive pool: {summary["pool_size"]} readings; {summary["initial_readings_per_seed"]} initial observations; '
        f'{summary["additional_queries_per_seed"]} further selections; {summary["seeds"]} seeds.',
        'BO uses BoTorch qLogNoisyExpectedImprovement, with min–max normalized varying coils and standardized beam outcomes.',
        'GP fitting and acquisition see revealed labels only. Random selection starts from identical observations.', '',
        '| Seed | Initial best nA | BO final best nA | Random final best nA |', '|---|---:|---:|---:|']
    for i, (initial, bo, random) in enumerate(zip(summary['initial_best_nA'], summary['bo_final_best_nA'], summary['random_final_best_nA'])):
        lines.append(f'| {i} | {initial:.3f} | {bo:.3f} | {random:.3f} |')
    lines += ['', f'Mean final best: BO {summary["bo_final_best_nA_mean"]:.3f} nA; random {summary["random_final_best_nA_mean"]:.3f} nA.',
              f'BO wins: {summary["bo_wins_over_random"]}/{summary["seeds"]}. Five replay seeds are descriptive, not independent physical experiments.', '',
              f'Nominal 95% reading-interval coverage: {summary["nominal_95_reading_interval_coverage"]:.0%} of adaptive reveal events. '
              'Some archived rows recur across seeds. These intervals are not calibrated physical guarantees.', '',
              'Latent intervals describe estimated mean beam; observation intervals additionally include learned observation noise.',
              'The maximum individual reading is a noisy historical observation, not a verified steady-state optimum.', '',
              '## Scaling and prediction', '',
              f'Artificial per-channel gains/offsets changed standardized features by at most {summary["affine_scaling_invariance_max_difference"]:.3g}. '
              'Differences in numeric magnitude alone therefore do not explain the standardized model errors.',
              f'Sampled beam lag-1 correlation: {summary["sampled_beam_lag1_correlation"]:.3f}. Time dependence and narrow coil coverage limit interpretation.',
              'TC3 is constant and excluded. The configured TC11 raw-to-engineering conversion is identity; physical current calibration remains unverified.', '',
              '## Useful next data', '',
              '- Record commanded setpoints and settled readbacks separately.',
              '- Collect controlled scans of one or two coils with repeated beam measurement windows and a fixed reference setting.',
              '- Retain RF, vacuum, source and magnet context to distinguish drift from coil response.',
              '- Verify detector range calibration and coil engineering units independently.',
              '- Validate error and interval coverage on whole later time blocks or separate runs.', '',
              '[BoTorch noisy acquisition documentation](https://botorch.readthedocs.io/en/stable/acquisition.html)', '']
    (Path(output_dir) / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())
