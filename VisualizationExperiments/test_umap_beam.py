import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from umap_common import arguments, prepare, embed, COILS, beam_bands, add_beam_range_controls, correct_cyclotron_mapping


class BeamViewTest(unittest.TestCase):
    def test_old_cyclotron_csv_uses_ch11_for_tc8(self):
        from parse_cyclotron import DEFAULT_COILS, LEGACY_COILS
        frame = pd.DataFrame({'coil_mapping': [','.join(LEGACY_COILS), ','.join(DEFAULT_COILS)],
                              'source_database': ['cyclotron_data.db'] * 2,
                              'ch11': [11., 12.], 'Trim Coil 8': [0., 12.]})
        corrected = correct_cyclotron_mapping(frame)
        self.assertEqual(corrected['Trim Coil 8'].tolist(), [11., 12.])
        self.assertEqual(frame['Trim Coil 8'].tolist(), [0., 12.])
        custom = frame.copy()
        custom['coil_mapping'] = 'custom'
        self.assertEqual(correct_cyclotron_mapping(custom)['Trim Coil 8'].tolist(), [0., 12.])

    def test_interactive_bands_and_boundaries_in_both_dimensions(self):
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        values = np.array([0, 2.9, 3, 4.9, 5, 7.9, 8, 12.])
        bands = beam_bands(values)[:4]
        np.testing.assert_equal(np.sum([mask for _, mask in bands], axis=0), np.ones(8))
        for dimensions in (2, 3):
            fig = plt.figure()
            ax = fig.add_subplot(111, projection='3d' if dimensions == 3 else None)
            groups = []
            for label, mask in bands:
                coordinates = [values[mask]] * dimensions
                artist = ax.scatter(*coordinates)
                groups.append((label, artist, values[mask]))
            controls = add_beam_range_controls(fig, groups)
            limits = ax.get_xlim()
            controls.set_active(1)
            self.assertFalse(groups[1][1].get_visible())
            self.assertTrue(groups[0][1].get_visible())
            self.assertEqual(ax.get_xlim(), limits)
            controls.set_active(1)
            self.assertTrue(groups[1][1].get_visible())
            plt.close(fig)

    def test_threshold_keeps_settings_and_beam_aligned(self):
        args = arguments(False).parse_args(['--data', 'test.csv', '--min-beam-na', '3'])
        frame = pd.DataFrame({coil: np.arange(6, dtype=float) for coil in COILS})
        frame['output_beam_nA'] = [np.nan, 2, 3, 4, 5, 6]
        frame['source_row'] = np.arange(6)
        result, currents = prepare(args, frame, np, pd)
        self.assertEqual(result.source_row.tolist(), [3, 4, 5])
        self.assertEqual(result.output_beam_nA.tolist(), [4, 5, 6])
        np.testing.assert_equal(currents[:, 0], [3, 4, 5])

    def test_three_coil_components(self):
        args = arguments(True).parse_args(['--third-axis', 'umap'])
        class Reducer:
            def __init__(self, **kwargs):
                self.dimensions = kwargs['n_components']
            def fit_transform(self, values):
                return np.zeros((len(values), self.dimensions))
        coordinates = embed(args, np.arange(60).reshape(6, 10), np,
                            SimpleNamespace(UMAP=Reducer), StandardScaler)
        self.assertEqual(coordinates.shape, (6, 3))

    def test_csv_upper_bound_and_hardware_range(self):
        args = arguments(False).parse_args(['--data', 'test.csv', '--min-beam-na', '3',
                  '--max-beam-na', '5', '--beam-range-index', '2'])
        frame = pd.DataFrame({coil: np.arange(7, dtype=float) for coil in COILS})
        frame['output_beam_nA'] = [3, 3.5, 4, 5, 5.1, 4.5, 2]
        frame['beam_range_idx'] = [2, 2, 2, 2, 2, 1, 2]
        frame['source_row'] = np.arange(7)
        result, currents = prepare(args, frame, np, pd)
        self.assertEqual(result.output_beam_nA.tolist(), [3.5, 4, 5])
        np.testing.assert_equal(currents[:, 0], [1, 2, 3])

    def test_controls_toggle_multiple_artists_per_measurement_band(self):
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        first = ax.scatter([1], [2])
        second, = ax.plot([1, 2], [2, 3])
        controls = add_beam_range_controls(fig, [('3–5 nA', [first, second], [1]),
                                                ('8+ nA', [], [])])
        controls.set_active(0)
        self.assertFalse(first.get_visible())
        self.assertFalse(second.get_visible())
        controls.set_active(0)
        self.assertTrue(first.get_visible())
        self.assertTrue(second.get_visible())
        plt.close(fig)


if __name__ == '__main__':
    unittest.main()
