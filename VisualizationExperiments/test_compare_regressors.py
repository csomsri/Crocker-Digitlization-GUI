import unittest

import numpy as np
import pandas as pd

from compare_regressors import benchmark, scores
from umap_common import COILS


class ComparisonTest(unittest.TestCase):
    def test_chronological_holdout_does_not_enter_model_fit(self):
        frame = pd.DataFrame({coil: np.arange(30, dtype=float) for coil in COILS})
        frame['output_beam_nA'] = 2 * frame[COILS[0]] + 1
        frame['source_row'] = np.arange(30)
        frame['timestamp_utc'] = 'test'
        report, first = benchmark(frame, 'beam', max_train=10)
        self.assertEqual(report['training_rows_used_by_both_models'], 10)
        self.assertEqual(report['test_rows'], 6)
        self.assertEqual(first.source_row.tolist(), list(range(24, 30)))
        self.assertAlmostEqual(report['models']['linear']['metrics']['beam_nA']['r2'], 1)
        frame.loc[24:, 'output_beam_nA'] += 1000
        _, second = benchmark(frame, 'beam', max_train=10)
        for model in ('linear', 'gp', 'training_mean', 'last_training_value'):
            np.testing.assert_allclose(first['beam_nA_' + model], second['beam_nA_' + model])

    def test_constant_target_has_no_r_squared(self):
        result = scores(np.zeros(4), np.zeros(4), ['constant'])['constant']
        self.assertEqual(result['mae'], 0)
        self.assertIsNone(result['r2'])

    def test_constant_coils_are_not_reported_as_perfect_r_squared(self):
        frame = pd.DataFrame({coil: np.full(30, i, dtype=float) for i, coil in enumerate(COILS)})
        frame['source_row'] = np.arange(30)
        frame['timestamp_utc'] = 'test'
        report, output = benchmark(frame, 'next-settings', max_train=10)
        self.assertEqual(len(output), 6)
        for model in ('linear', 'gp'):
            for values in report['models'][model]['metrics'].values():
                self.assertAlmostEqual(values['mae'], 0)
                self.assertIsNone(values['r2'])


if __name__ == '__main__':
    unittest.main()
