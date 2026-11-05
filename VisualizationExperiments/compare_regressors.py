"""Chronological holdout comparison of GP, linear regression and baselines."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import warnings

import numpy as np
import pandas as pd
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, RBF, WhiteKernel
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from umap_common import BEAM_DATA, COILS, correct_cyclotron_mapping


def scores(actual, predicted, names):
    actual = np.asarray(actual).reshape(len(actual), -1)
    predicted = np.asarray(predicted).reshape(actual.shape)
    result = {}
    for i, name in enumerate(names):
        a, p = actual[:, i], predicted[:, i]
        result[name] = {'mae': float(mean_absolute_error(a, p)),
                        'rmse': float(np.sqrt(mean_squared_error(a, p))),
                        'r2': float(r2_score(a, p)) if np.ptp(a) > 0 else None}
    return result


def benchmark(frame, task, max_train=600, seed=42):
    """Fit preprocessing on the selected training rows, never the holdout."""
    if len(frame) < 20 or max_train < 10:
        raise ValueError('Need at least 20 data rows and a training cap of at least 10')
    split = int(.8 * len(frame))
    selected = np.unique(np.linspace(0, split - 1, min(split, max_train)).round().astype(int))
    if task == 'beam':
        x = frame[COILS].to_numpy(float)
        y = frame[['output_beam_nA']].to_numpy(float)
        names = ['beam_nA']
    else:
        # Match the existing next-setting regression: within-dataset row position.
        x = np.arange(len(frame), dtype=float).reshape(-1, 1)
        y = frame[COILS].to_numpy(float)
        names = COILS
    x_train, y_train = x[selected], y[selected]
    x_test, y_test = x[split:], y[split:]
    scaler = StandardScaler().fit(x_train)
    train, test = scaler.transform(x_train), scaler.transform(x_test)
    report = {'task': task, 'input': 'TC1..TC10' if task == 'beam' else 'row position',
              'target': names, 'eligible_rows': len(frame), 'training_pool_rows': split,
              'training_rows_used_by_both_models': len(selected), 'test_rows': len(y_test),
              'training_selection': 'evenly spaced indices from the first 80%; shared by both models',
              'test_selection': 'final 20%, in timestamp order; no shuffling',
              'training_source_rows': frame.iloc[selected]['source_row'].tolist(),
              'test_start_utc': frame.iloc[split]['timestamp_utc'],
              'test_end_utc': frame.iloc[-1]['timestamp_utc'],
              'models': {}}
    output = frame.iloc[split:][['source_row', 'timestamp_utc']].copy().reset_index(drop=True)
    for i, name in enumerate(names):
        output[name + '_actual'] = y_test[:, i]
    predictions = {}
    predictions['training_mean'] = np.tile(y_train.mean(axis=0), (len(y_test), 1))
    predictions['last_training_value'] = np.tile(y_train[-1], (len(y_test), 1))
    started = time.perf_counter()
    linear = LinearRegression().fit(train, y_train)
    predictions['linear'] = linear.predict(test)
    report['models']['linear'] = {'fit_predict_seconds': time.perf_counter() - started}
    started = time.perf_counter()
    means, deviations, kernels = [], [], {}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        for i, name in enumerate(names):
            if np.ptp(y_train[:, i]) == 0:
                means.append(np.full(len(test), y_train[0, i]))
                deviations.append(np.zeros(len(test)))
                kernels[name] = 'constant training target; deterministic constant predictor'
                continue
            kernel = ConstantKernel(1., (.01, 100.)) * RBF(1., (.05, 20.)) + WhiteKernel(.1, (1e-5, 10.))
            gp = GaussianProcessRegressor(kernel=kernel, normalize_y=True, n_restarts_optimizer=2,
                                          random_state=seed, alpha=1e-8)
            gp.fit(train, y_train[:, i])
            mean, std = gp.predict(test, return_std=True)
            means.append(mean)
            deviations.append(std)
            kernels[name] = str(gp.kernel_)
    predictions['gp'] = np.column_stack(means)
    std = np.column_stack(deviations)
    report['models']['gp'] = {'fit_predict_seconds': time.perf_counter() - started,
                              'kernels': kernels, 'optimizer_restarts': 2,
                              'architecture': 'independent normalized GP per target, matching the visualization model family',
                              'warnings': [str(w.message) for w in caught],
                              'marginal_95pct_coverage': {name: float(np.mean(
                                  np.abs(y_test[:, i] - predictions['gp'][:, i]) <= 1.96 * std[:, i]))
                                  for i, name in enumerate(names)}}
    for model, predicted in predictions.items():
        report['models'].setdefault(model, {})['metrics'] = scores(y_test, predicted, names)
        for i, name in enumerate(names):
            output[f'{name}_{model}'] = predicted[:, i]
    for i, name in enumerate(names):
        output[f'{name}_gp_std'] = std[:, i]
    return report, output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=BEAM_DATA)
    parser.add_argument('--task', choices=['beam', 'next-settings', 'both'], default='beam')
    parser.add_argument('--max-train', type=int, default=600,
                        help='Same training cap for both models; exact GP has cubic training cost')
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent / 'outputs/cyclotron/model_comparison')
    args = parser.parse_args(argv)
    frame = correct_cyclotron_mapping(pd.read_csv(args.data)).sort_values(['timestamp', 'source_row'], kind='stable')
    required = [*COILS, 'output_beam_nA', 'timestamp']
    good = np.isfinite(frame[required].to_numpy(float)).all(axis=1)
    excluded = int((~good).sum())
    frame = frame.loc[good].reset_index(drop=True)
    reports = {'data': str(args.data.resolve()), 'excluded_nonfinite_rows': excluded,
               'coil_mapping': frame['coil_mapping'].iloc[0] if len(frame) and 'coil_mapping' in frame else 'input aliases',
               'calibration': frame['beam_calibration_file'].iloc[0] if len(frame) and 'beam_calibration_file' in frame else 'unspecified',
               'limitations': ['One chronological holdout from one recording, not independent machine runs.',
                               'Beam nA values depend on the selected historical calibration.',
                               'Beam models use recorded coils; next-setting models use row position. UMAP is not a model input.',
                               'R2 is explained variance, not a percentage accuracy.'], 'tasks': {}}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with threadpool_limits(limits=1):
        for task in (['beam', 'next-settings'] if args.task == 'both' else [args.task]):
            print(f'Fitting {task}: {len(frame)} rows, max training rows {args.max_train}.', flush=True)
            report, predictions = benchmark(frame, task, args.max_train)
            reports['tasks'][task] = report
            predictions.to_csv(args.output_dir / f'{task}_holdout.csv', index=False)
            for model, details in report['models'].items():
                print(model, json.dumps(details['metrics']), flush=True)
    (args.output_dir / 'comparison.json').write_text(json.dumps(reports, indent=2, allow_nan=False), encoding='utf-8')
    metrics = []
    lines = ['# GP and linear regression holdout comparison', '',
             'Both models train on the same capped selection from the first 80% of the recording.',
             'The final 20% is held out. Beam errors are in calibrated nA; coil errors are in recorded units.',
             'R² is explained variance, not percentage accuracy. Constant coil targets have no R².', '']
    for task, report in reports['tasks'].items():
        lines += [f'## {task}', '', f'Training rows: {report["training_rows_used_by_both_models"]}; test rows: {report["test_rows"]}.', '',
                  '| Model | Target | MAE | RMSE | R² |', '|---|---|---:|---:|---:|']
        for model, details in report['models'].items():
            valid = [m for m in details['metrics'].values() if m['r2'] is not None]
            details['mean_metrics_over_nonconstant_targets'] = {
                key: float(np.mean([m[key] for m in valid])) if valid else None
                for key in ('mae', 'rmse', 'r2')}
            for target, values in details['metrics'].items():
                metrics.append({'task': task, 'model': model, 'target': target, **values})
                r2 = f'{values["r2"]:.4f}' if values['r2'] is not None else 'N/A (constant)'
                lines.append(f'| {model} | {target} | {values["mae"]:.6g} | {values["rmse"]:.6g} | {r2} |')
        lines.append('')
    # Save again after adding per-task nonconstant-target summaries.
    (args.output_dir / 'comparison.json').write_text(json.dumps(reports, indent=2, allow_nan=False), encoding='utf-8')
    pd.DataFrame(metrics).to_csv(args.output_dir / 'metrics.csv', index=False)
    (args.output_dir / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f'Saved comparison: {args.output_dir.resolve()}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
