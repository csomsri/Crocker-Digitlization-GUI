"""Retain an inspectable simulation recording from the real GUI acquisition path.

Run: python CrockerGUI/tests/AcquisitionPipelineProofTest.py -v
Never connects to facility hardware; every run gets its own output directory.
"""
import json
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
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from python.app.MainWindow import MainWindow


class AcquisitionPipelineProofTest(unittest.TestCase):
    def test_native_simulator_through_gui_to_telemetry_and_pid_sqlite(self):
        app = QApplication.instance() or QApplication([])
        output = ROOT / 'logs' / 'acquisition-proof' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8])
        output.mkdir(parents=True)
        settings = QSettings(str(output / 'settings.ini'), QSettings.IniFormat)
        with patch('python.app.MainWindow.QSettings', return_value=settings):
            window = MainWindow('zmq', 'tcp://127.0.0.1:5555', simulation_mode='first-order',
                                enable_data_pipeline=True, db_path=output / 'crocker_pipeline.sqlite3')
        page = window.pages['PID Control']
        page.run_metrics.directory = output / 'exports'
        page.log_path = output / 'commands.csv'

        def pump(seconds):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.005)

        try:
            deadline = time.monotonic() + 5
            while window.current_beam_state().get('quality') != 'ok' and time.monotonic() < deadline:
                pump(.05)
            pump(.5)
            self.assertTrue(window.database_a.started)
            self.assertFalse(window.database_b.writer.status()['started'])
            page.output_on_check.setChecked(True)
            page.control_enabled_check.setChecked(True)
            page.command_values[9] = 50
            self.assertTrue(page._apply_channel_command(9))
            pump(.2)
            page._tick_feedback()
            page.setpoint_input.setValue(.8)
            page.arm_button.setChecked(True)
            page.enable_button.setChecked(True)
            self.assertTrue(page.pid_enabled, page.last_safety_message)
            pump(1.5)
            self.assertGreater(page.backend.PidTrialStatus()['iterations'], 0)
            self.assertEqual(page._database_recorder.error, '')
            page._stop_pid('Acquisition proof completed')
        finally:
            window.close()
            deadline = time.monotonic() + 8
            while not window._recording_closed and time.monotonic() < deadline:
                pump(.02)
            self.assertTrue(window._recording_closed, 'Recording did not flush on shutdown')

        for writer in (window.database_a.writer, window.database_b.writer):
            self.assertEqual(writer.error, '')
            self.assertEqual(writer.rejected, 0)
            self.assertEqual(writer.pending, 0)
        a = sqlite3.connect((output / 'crocker_pipeline.sqlite3').as_uri() + '?mode=ro', uri=True)
        b = sqlite3.connect((output / 'crocker_pid.sqlite3').as_uri() + '?mode=ro', uri=True)
        try:
            self.assertEqual(a.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(b.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            readings = a.execute('SELECT COUNT(*) FROM readings').fetchone()[0]
            self.assertGreater(readings, 0)
            session = b.execute('SELECT id,a_session_id,environment,ended_at FROM pid_sessions').fetchone()
            self.assertEqual(session[1], window.database_a.session_id)
            self.assertEqual(session[2], 'simulation')
            self.assertIsNotNone(session[3])
            b.row_factory = sqlite3.Row
            rows = [dict(r) for r in b.execute('SELECT * FROM pid_samples ORDER BY id')]
            self.assertGreater(len(rows), 1)
            self.assertTrue(all(r['feedback_unit'] == 'nA' and r['tc_channel'] == 10 for r in rows))
            self.assertTrue(all(r['beam_target_na'] == .8 for r in rows))
            self.assertTrue(all(r['tc_actual_a'] is not None and r['tc_command_a'] is not None for r in rows))
            self.assertGreater(max(r['controller_iteration'] or 0 for r in rows), 0)
            a_snapshots = {r[0] for r in a.execute('SELECT DISTINCT snapshot_id FROM readings')}
            matched = sum(r['snapshot_id'] in a_snapshots for r in rows)
            # A and B publish on independent GUI timers. They share the run,
            # but need not capture exactly the same native snapshot.
            stamps = [r[0] for r in a.execute('SELECT DISTINCT timestamp FROM readings')]
            nearest = [min(abs(t - r['telemetry_timestamp']) for t in stamps) for r in rows]
            self.assertLess(max(nearest), 1.0, 'PID and telemetry recordings must overlap in time')
            self.assertEqual(a.execute('SELECT COUNT(*) FROM runs WHERE session_id=?',
                                      (session[1],)).fetchone()[0], 1)
            report = dict(environment='simulation', telemetry_readings=readings,
                          pid_samples=len(rows), exact_snapshot_matches=matched,
                          maximum_nearest_telemetry_seconds=max(nearest),
                          session_id=session[0], integrity='ok', rejected=0,
                          sample_preview=rows[:3], output=str(output))
            (output / 'proof.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            print('\nRETAINED ACQUISITION PROOF: ' + str(output), flush=True)
            print(json.dumps({k: v for k, v in report.items() if k != 'sample_preview'}), flush=True)
        finally:
            a.close()
            b.close()


if __name__ == '__main__':
    unittest.main()
