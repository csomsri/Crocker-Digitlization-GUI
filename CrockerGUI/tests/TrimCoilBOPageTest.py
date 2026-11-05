"""Offscreen GUI smoke test using the actual simulator child process."""
import os
from pathlib import Path
import sys
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from python.app.Automation.TrimCoilBOPage import TrimCoilBOPage
from python.app.theme import load_app_font, load_stylesheet


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(load_stylesheet(load_app_font()))

    def test_simulator_process_and_table(self):
        page = TrimCoilBOPage(lambda: None)
        page.resize(1100, 760)
        page.show()
        page.trials.setValue(1)
        page.start_simulation()
        deadline = time.monotonic() + 90
        try:
            while page.run_active and time.monotonic() < deadline:
                QTest.qWait(50)
            self.assertFalse(page.run_active, 'Simulator process timed out')
            self.assertIsNotNone(page.summary, page.status.text())
            self.assertEqual(page.summary['state'], 'completed')
            self.assertTrue(page.summary['reference_restored'])
            self.assertEqual(page.table.rowCount(), page.summary['measurement_windows'])
            self.assertEqual(len(page.plot_data.windows), page.summary['measurement_windows'])
            self.assertAlmostEqual(page.plot_data.reference, page.summary['baseline_nA'])
            self.assertTrue(page.plot_data.telemetry)
            self.assertTrue(page.plots['signals'].hits)
            self.assertEqual(page.plot_tabs.tabText(0), 'Trim coils + beam')
            self.assertTrue(page.audit_path.is_file())
            self.assertTrue(page.start_button.isEnabled())
            page.grab().save(str(ROOT / 'logs' / 'trim_coil_bo_page.png'))
        finally:
            if page.run_active:
                page.process.kill()
                page.process.waitForFinished(5000)
            page.close()

    def test_visualization_layers_and_confirmed_incumbent(self):
        page = TrimCoilBOPage(lambda: None)
        page.resize(1100, 820)
        page.show()
        for index in range(40):
            target = .2 if 10 <= index < 28 else 0.
            actual = target * .8
            page._message({'progress': {'event': 'telemetry', 'time_s': index / 10,
                'targets_a': {'TC1': target, 'TC2': -target},
                'readbacks_a': {'TC1': actual, 'TC2': -actual},
                'beam_nA': 10 + actual, 'valid': True}})
        def measurement(kind, point, mean):
            page._message({'progress': {'event': 'measurement', 'kind': kind, 'point': point,
                          'mean_nA': mean, 'stddev_nA': .02, 'sample_count': 10}})
        measurement('baseline', {'TC1': 0., 'TC2': 0.}, 10.)
        measurement('candidate', {'TC1': .1, 'TC2': .2}, 10.4)
        # A larger single result must not move the confirmed-best layer.
        self.assertEqual(page.plot_data.incumbent, {'TC1': 0., 'TC2': 0.})
        for value in (10.29, 10.3, 10.31):
            measurement('confirm_candidate', {'TC1': .1, 'TC2': .2}, value)
        page._message({'progress': {'event': 'confirmation', 'promoted': True,
                      'incumbent': {'TC1': .1, 'TC2': .2}, 'gain_nA': .3,
                      'lower_bound_nA': .25, 'standard_error_nA': .0167}})
        self.assertEqual(page.plot_data.incumbent, {'TC1': .1, 'TC2': .2})
        self.assertAlmostEqual(page.plot_data.best[-1][1], 10.3)
        for index, name in enumerate(('signals', 'beam', 'search', 'confirmation')):
            page.plot_tabs.setCurrentIndex(index)
            self.app.processEvents()
            self.assertTrue(page.plots[name].hits)
            self.assertTrue(page.grab().save(str(ROOT / 'logs' / f'trim_coil_bo_{name}.png')))
        page.layer_checks['Reference'].setChecked(False)
        self.assertTrue(all(not plot.layers['Reference'] for plot in page.plots.values()))
        page.plot_data.reset()
        self.assertFalse(page.plot_data.windows)
        self.assertFalse(page.plot_data.confirmations)
        self.assertFalse(page.plot_data.best)
        self.assertFalse(page.plot_data.telemetry)
        page.close()

    def test_captured_reference_and_new_views(self):
        page = TrimCoilBOPage(lambda: None)
        page.resize(1200, 1000)
        page.show()
        page._message({'progress': {'event': 'start',
            'reference_targets_a': {'TC1': .2, 'TC2': -.1},
            'reference_readbacks_a': {'TC1': .201, 'TC2': -.101},
            'parameters': [{'name': 'TC1', 'bounds': [-.3, .7]},
                           {'name': 'TC2', 'bounds': [-.6, .4]}]}})
        page._message({'progress': {'event': 'telemetry', 'time_s': 1,
            'targets_a': {'TC1': .3, 'TC2': -.1}, 'readbacks_a': {'TC1': .29, 'TC2': -.1},
            'beam_nA': 10.2, 'valid': True}})
        page._message({'progress': {'event': 'measurement', 'kind': 'baseline',
            'point': {'TC1': .2, 'TC2': -.1}, 'mean_nA': 10., 'stddev_nA': .02}})
        self.assertIn('+0.2000 A', page.coil_cards['TC1'].text())
        self.assertIn('+0.2900 A', page.coil_cards['TC1'].text())
        self.assertEqual(page.plot_data.incumbent, {'TC1': .2, 'TC2': -.1})
        self.assertEqual(page.metrics['cost'].text(), '-10.000')
        for name in ('cost', 'parallel'):
            page.plot_tabs.setCurrentWidget(page.plots[name])
            self.app.processEvents()
            self.assertTrue(page.plots[name].hits)
            page.grab().save(str(ROOT / 'logs' / f'trim_coil_bo_{name}.png'))
        page.close()

    def test_abort_process_restores_reference(self):
        page = TrimCoilBOPage(lambda: None)
        page.trials.setValue(100)
        page.start_simulation()
        # Queue the request even while Python and Torch are starting.
        self.assertTrue(page.process.waitForStarted(5000))
        page.stop_backend()
        deadline = time.monotonic() + 90
        try:
            while page.run_active and time.monotonic() < deadline:
                QTest.qWait(50)
            self.assertFalse(page.run_active)
            self.assertIsNotNone(page.summary, page.status.text())
            self.assertEqual(page.summary['state'], 'stopped')
            self.assertTrue(page.summary['reference_restored'])
            self.assertEqual(page.summary['candidate_trials'], 0)
        finally:
            if page.run_active:
                page.process.kill()
                page.process.waitForFinished(5000)
            page.close()


if __name__ == '__main__':
    unittest.main()
