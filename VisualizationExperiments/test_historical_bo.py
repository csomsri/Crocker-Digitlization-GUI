import unittest

import numpy as np
import torch

from historical_bo import replay


class ReplayTest(unittest.TestCase):
    def test_first_proposal_cannot_see_unrevealed_labels(self):
        torch.set_num_threads(1)
        x = torch.linspace(0, 1, 16, dtype=torch.double).unsqueeze(1)
        y = (2 + torch.sin(x * 3)).clone()
        seed, initial = 7, 4
        starting = np.random.default_rng(seed).choice(len(x), initial, replace=False)
        hidden = np.setdiff1d(np.arange(len(x)), starting)
        changed = y.clone()
        changed[hidden] += 10
        first, _, final, seen, _, _ = replay(x, y, np.arange(16), initial=initial, steps=1, seed=seed)
        other, _, _, _, _, _ = replay(x, changed, np.arange(16), initial=initial, steps=1, seed=seed)
        self.assertEqual(first[0]['archive_index'], other[0]['archive_index'])
        self.assertAlmostEqual(first[0]['predicted_mean_nA'], other[0]['predicted_mean_nA'])
        self.assertEqual(len(set(seen)), initial + 1)
        self.assertTrue(np.all(final[2] >= final[1]))
        self.assertAlmostEqual(first[0]['revealed_archived_beam_nA'], float(y[first[0]['archive_index']].item()))


if __name__ == '__main__':
    unittest.main()
