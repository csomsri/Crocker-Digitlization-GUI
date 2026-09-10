"""GP slice geometry, posterior intervals, and plot rendering."""
import os
import sys
import math
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source.Python.Optimization.pid_gain_adapter import BotorchPidOptimizer, PidGainCandidate, PidTrialResult


class SliceTest(unittest.TestCase):
    def optimizer(self):
        opt = BotorchPidOptimizer((0, 10), (0, 1), (0, 1), use_cuda=False)
        for x in (2.4, 3.6, 4.5, 5.0, 8.2, 9.3):
            value = x * math.sin(x)
            opt.record_results([PidTrialResult(PidGainCandidate(x, .4, .2), value, 0, 0, 0, 0, True)])
        return opt

    def test_full_dimensional_slice_and_cost_interval(self):
        opt = self.optimizer()
        def predict(**kwargs):
            rows = kwargs['query_x'].tolist()
            self.assertEqual(len(rows), 5)
            self.assertTrue(all(row[0] == opt.best_result.candidate.kp and row[2] == .2 for row in rows))
            self.assertEqual([row[1] for row in rows], [0, .25, .5, .75, 1])
            return [2.0]*5, [4.0]*5
        with patch('source.Python.Optimization.bayesian_optimizer.fit_single_task_gp', return_value=object()), patch(
                'source.Python.Optimization.bayesian_optimizer.predict_posterior_mean_variance', side_effect=predict):
            data = opt.surrogate_slice(axis_x='ki', point_count=5)
        self.assertEqual(data['mean'], [-2]*5)
        self.assertEqual(data['stddev'], [2]*5)
        self.assertAlmostEqual(data['lower'][0], -5.92)
        self.assertAlmostEqual(data['upper'][0], 1.92)
        with self.assertRaises(ValueError): opt.surrogate_slice(axis_x='invalid')

    def test_real_gp_and_render(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFont, QFontDatabase
        from python.app.Automation.SurrogatePlotWidget import SurrogatePlotWidget
        app = QApplication.instance() or QApplication([])
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
        app.setFont(QFont('Segoe UI', 10))
        opt = self.optimizer()
        data = opt.surrogate_slice(point_count=160)
        self.assertTrue(data['ready'])
        self.assertTrue(all(lo <= mean <= hi for lo, mean, hi in zip(data['lower'], data['mean'], data['upper'])))
        widget = SurrogatePlotWidget()
        widget.resize(950, 490)
        widget.set_state(grid=data, results=opt.results, candidate=None, best=opt.best_result)
        self.assertTrue(widget._on_slice(opt.results[0].candidate))
        self.assertFalse(widget._on_slice(PidGainCandidate(3, .7, .2)))
        widget.show()
        app.processEvents()
        output = Path(__file__).resolve().parents[1] / 'build' / 'gp-slice-preview.png'
        self.assertTrue(widget.grab().save(str(output)))
        widget.set_state(grid=data, results=opt.results, candidate=None, best=None, axis_x='ki')
        self.assertIsNone(widget._grid)  # never display a response for the wrong axis
        widget.close()


if __name__ == '__main__':
    unittest.main()
