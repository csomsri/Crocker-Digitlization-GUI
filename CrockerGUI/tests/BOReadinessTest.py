"""Retained seven-trial GUI/ZeroMQ/October PID/BoTorch recording smoke test.

Short simulation trials test the workflow, not gain quality or machine safety.
Run: python CrockerGUI/tests/BOReadinessTest.py -v
"""
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import zmq  # Load before Qt's import hooks.
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from python.app.MainWindow import MainWindow


class BOReadinessTest(unittest.TestCase):
    def test_seven_trials_model_proposal_validation_cancel_and_recording(self):
        app = QApplication.instance() or QApplication([])
        output = ROOT / 'logs' / 'bo-readiness' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8])
        output.mkdir(parents=True)
        settings = QSettings(str(output / 'settings.ini'), QSettings.IniFormat)
        with patch('python.app.MainWindow.QSettings', return_value=settings):
            window = MainWindow('zmq', 'tcp://127.0.0.1:5555', simulation_mode='first-order',
                                enable_data_pipeline=True, db_path=output / 'crocker_pipeline.sqlite3')
        page = window.pages['PID Control']
        page.run_metrics.directory = output / 'exports'
        page.log_path = output / 'commands.csv'

        def until(predicate, seconds):
            deadline = time.monotonic() + seconds
            while not predicate() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            self.assertTrue(predicate(), page.tuner_status.text())

        try:
            until(lambda: window.current_beam_state().get('quality') == 'ok', 8)
            page.output_on_check.setChecked(True)
            page.control_enabled_check.setChecked(True)
            self.assertTrue(page._apply_channel_command(9))
            page.nla_window_input.setValue(.1)
            page._show_tuner()
            page.tuner_trials.setValue(7)
            page.tuner_duration.setValue(2)
            page.tuner_target.setValue(.8)
            for _ in range(3):
                page._start_auto_tuning()
                until(lambda: page.tuning_trial_candidate is not None, 60)
                page._stop_tuning_session()
                self.assertFalse(page.tuning_session_active)
                self.assertTrue(page.auto_tuning_button.isEnabled())
            page._start_auto_tuning()
            self.assertTrue(page.tuning_session_active, page.tuner_status.text())
            # Actual GP/acquisition optimization, with a smaller smoke-test budget.
            page.tuning_optimizer.optimizer.mc_samples = 16
            page.tuning_optimizer.optimizer.num_restarts = 2
            page.tuning_optimizer.optimizer.raw_samples = 32
            until(lambda: not page.tuning_session_active, 180)
            self.assertEqual(len(page.tuning_results), 7, page.tuner_status.text())
            self.assertTrue(page.tuning_optimizer.optimizer._botorch_ready)
            self.assertTrue(all(r.safe and math.isfinite(r.score) for r in page.tuning_results))
            self.assertTrue(all(r.controller_kind == 'nla' for r in page.tuning_results))
            self.assertFalse(page.apply_tuned_gains_button.isEnabled())
            page._validate_best_gains()
            self.assertTrue(page._validating_gains, page.tuner_status.text())
            page._stop_tuning_session()
            self.assertFalse(page._validating_gains)
            self.assertFalse(page.apply_tuned_gains_button.isEnabled())
            self.assertEqual(page._database_recorder.error, '')
            report = dict(scope='Local first-order plant; seven short workflow trials, not convergence or hardware validation',
                          controller='October PID (C++)', botorch_ready=True,
                          scores=[r.score for r in page.tuning_results],
                          best_cost=page.tuning_optimizer.best_result.score,
                          validation_started_and_cancelled=True)
        finally:
            window.close()
            until(lambda: window._recording_closed, 10)
        for writer in (window.database_a.writer, window.database_b.writer):
            self.assertEqual(writer.error, '')
            self.assertEqual(writer.rejected, 0)
            self.assertEqual(writer.pending, 0)
        with sqlite3.connect(output / 'crocker_pid.sqlite3') as connection:
            trials = connection.execute('SELECT COUNT(*) FROM pid_trials').fetchone()[0]
            samples = connection.execute('SELECT COUNT(*) FROM pid_samples').fetchone()[0]
            self.assertEqual(trials, 7)
            self.assertGreater(samples, 7)
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            report.update(recorded_trials=trials, recorded_samples=samples, output=str(output))
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print('\nBO READINESS: ' + json.dumps(report), flush=True)


if __name__ == '__main__':
    unittest.main()
