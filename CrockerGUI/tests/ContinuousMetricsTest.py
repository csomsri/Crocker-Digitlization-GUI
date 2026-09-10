import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from python.app.Automation.RunMetrics import RunMetrics, export_sample_range
from python.app.Automation.PidControlPage import PidControlPage
from python.app.Automation.PythonPIDPage import PythonPIDPage

app = QApplication.instance() or QApplication([])


class ContinuousMetricsTest(unittest.TestCase):
    def test_export_inclusive_points(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.csv'
            destination = Path(directory) / 'export.csv'
            source.write_text('time,value\n' + ''.join(f'{i},{i*2}\n' for i in range(1, 121)))
            self.assertEqual(export_sample_range(source, destination, 3, 100), 98)
            lines = destination.read_text().splitlines()
            self.assertEqual(lines[1], '3,6')
            self.assertEqual(lines[-1], '100,200')
            with self.assertRaises(ValueError):
                export_sample_range(source, source, 1, 3)

    def test_window_limit_and_live_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            widget = RunMetrics(Path(directory))
            widget.duration.setValue(10)
            with patch('python.app.Automation.RunMetrics.time.perf_counter', return_value=0):
                widget.start(dict(setpoint=10))
            with patch('python.app.Automation.RunMetrics.time.perf_counter', return_value=1):
                widget.sample(1, 9)
            csv_path = next(Path(directory).glob('*.csv'))
            self.assertIn('1,9,1', csv_path.read_text())
            with patch('python.app.Automation.RunMetrics.time.perf_counter', return_value=10):
                widget.sample(2, 10)
            self.assertFalse(widget.active)
            self.assertEqual(len(widget.samples), 1)
            self.assertTrue(widget.record_button.isEnabled())
            self.assertEqual(widget.records[-1]['reason'], 'Measurement window complete')
            widget.finish('PID stopped')
            self.assertFalse(widget.record_button.isEnabled())

    def test_fresh_samples_settling_and_saved_data(self):
        with tempfile.TemporaryDirectory() as directory:
            widget = RunMetrics(Path(directory))
            with patch('python.app.Automation.RunMetrics.time.perf_counter', return_value=0):
                widget.start(dict(setpoint=10, kp=1))
            for i, error in enumerate([2, 1, 0, 0, 0, 0, 0]):
                with patch('python.app.Automation.RunMetrics.time.perf_counter', return_value=i*.2):
                    widget.sample(i, 10-error)
                    widget.sample(i, 10-error)
            self.assertEqual(len(widget.samples), 7)
            self.assertTrue(widget.metrics().settled)
            with patch('python.app.Automation.RunMetrics.time.perf_counter', return_value=1.4):
                widget.sample(7, 8)
                self.assertFalse(widget.metrics().settled)
                widget.finish('Operator stop')
                widget.finish('Repeated stop')
            files = list(Path(directory).glob('*.json'))
            self.assertEqual(len(files), 1)
            record = json.loads(files[0].read_text())
            self.assertEqual(record['sample_count'], 8)
            self.assertEqual(record['method'], 'Manual / baseline')
            self.assertFalse(record['metrics']['settled'])
            self.assertTrue(files[0].with_suffix('.csv').exists())

    def test_both_pages_run_and_setpoint_boundary(self):
        for page_type in (PidControlPage, PythonPIDPage):
            with self.subTest(page=page_type.__name__), tempfile.TemporaryDirectory() as directory:
                page = page_type(lambda: None, 'simulation', manage_backend=False)
                page.timer.stop()
                if page_type is PidControlPage:
                    self.assertTrue(page._cpp_nla_selected())
                    page.controller_kind_input.setCurrentIndex(0)
                page.run_metrics.directory = Path(directory)
                page._is_safe_to_run = lambda: True
                page._tick_pid_controller = lambda: None
                page._apply_channel_command = lambda index: True
                try:
                    page._set_pid_enabled(True)
                    self.assertTrue(page.run_metrics.active)
                    page._tick_feedback()
                    page.setpoint_input.setValue(page.setpoint_input.value()+1)
                    page._tick_feedback()
                    self.assertEqual(len(page.run_metrics.records), 1)
                    self.assertEqual(page.run_metrics.config['setpoint'], page.setpoint_input.value())
                    page._stop_pid('Test stop')
                    self.assertFalse(page.run_metrics.active)
                    self.assertEqual(len(page.run_metrics.records), 2)
                finally:
                    page.stop_backend()


if __name__ == '__main__':
    unittest.main()
