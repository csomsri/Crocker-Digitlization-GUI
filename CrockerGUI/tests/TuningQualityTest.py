"""Tuning-quality thresholds preserve fault handling and separate noise from oscillation."""
import math
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source.Python.Optimization.trial_metrics import TuningQuality, evaluate_trial


def wave(amplitude, duration, frequency=1, target=4):
    return [(i*.05, target + amplitude*math.sin(i*.05*math.tau*frequency),
             -amplitude*math.sin(i*.05*math.tau*frequency), 0, 100, 0)
            for i in range(round(duration/.05)+1)]


class QualityMetricsTest(unittest.TestCase):
    def test_small_ripple_is_not_rejected(self):
        rows = wave(.15, 20)
        self.assertTrue(evaluate_trial(rows, 4).sustained_oscillation)
        result = evaluate_trial(rows, 4, quality=TuningQuality())
        self.assertFalse(result.sustained_oscillation)
        self.assertTrue(result.settled)
        self.assertEqual(result.quality_settings['oscillation_min_cycles'], 4)

    def test_large_persistent_oscillation_still_rejected(self):
        self.assertTrue(evaluate_trial(wave(.3, 12), 4, quality=TuningQuality()).sustained_oscillation)
        self.assertFalse(evaluate_trial(wave(.3, 9), 4, quality=TuningQuality()).sustained_oscillation)
        self.assertFalse(evaluate_trial(wave(.3, 12, frequency=.25), 4, quality=TuningQuality()).sustained_oscillation)

    def test_amplitude_is_independent_of_settling_band(self):
        quality = replace(TuningQuality(), settling_tolerance=1)
        result = evaluate_trial(wave(.3, 20), 4, quality=quality)
        self.assertTrue(result.settled)
        self.assertTrue(result.sustained_oscillation)

    def test_continuous_hold_and_invalid_samples(self):
        rows = [(i*.1, 4.1, -.1, 0, 100, 0) for i in range(16)]
        self.assertFalse(evaluate_trial(rows, 4, quality=TuningQuality()).settled)
        rows += [(2.1, 4.1, -.1, 0, 100, 0)]
        self.assertTrue(evaluate_trial(rows, 4, quality=TuningQuality()).settled)
        with self.assertRaises(ValueError):
            evaluate_trial([(0, 4, 0, 0, 100, 0), (1, float('nan'), 0, 0, 100, 0)], 4, quality=TuningQuality())
        for invalid in (0, -1, float('nan')):
            with self.assertRaises(ValueError):
                TuningQuality(oscillation_amplitude=invalid)


class QualityPageTest(unittest.TestCase):
    def test_persistence_and_session_freeze(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        from python.app.Automation.PidControlPage import PidControlPage
        from python.app.Automation.TuningQualityDialog import TuningQualityDialog
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory)/'test.ini'), QSettings.IniFormat)
            with patch('python.app.Automation.TuningQualityDialog.QSettings', return_value=settings):
                page = PidControlPage(lambda: None, backend_mode='simulation')
                try:
                    page.tuning_quality_dialog.inputs['settling_tolerance'].setValue(.25)
                    reopened = TuningQualityDialog(page, 'nA')
                    self.assertEqual(reopened.snapshot().settling_tolerance, .25)
                    reopened.deleteLater()
                    with patch.object(page, '_request_tuning_candidate'):
                        page._prepare_tuning_session()
                    self.assertTrue(page.tuning_session_active)
                    self.assertEqual(page._tuning_quality_settings.settling_tolerance, .25)
                    self.assertTrue(all(not w.isEnabled() for w in page.tuning_quality_dialog.inputs.values()))
                    page.tuning_quality_dialog.inputs['settling_tolerance'].setValue(.3)
                    self.assertEqual(page._tuning_quality_settings.settling_tolerance, .25)
                    page._stop_tuning_session()
                    self.assertTrue(all(w.isEnabled() for w in page.tuning_quality_dialog.inputs.values()))
                finally:
                    page.stop_backend()
                    page.deleteLater()
                    app.processEvents()


if __name__ == '__main__':
    unittest.main()
