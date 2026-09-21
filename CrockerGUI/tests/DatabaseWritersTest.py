"""Real SQLite contention tests; all databases live in temporary directories."""
import os
from contextlib import closing
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source.Python.Data.pid_database import PIDDatabase
from source.Python.Data.telemetry_database import TelemetryDatabase
from source.Python.Data.async_writer import AsyncSQLiteWriter, Statement
from python.app.Automation.PIDRecording import PagePIDRecorder


def wait_for(test, timeout=4):
    until = time.monotonic()+timeout
    while time.monotonic() < until:
        if test():
            return
        time.sleep(.01)
    raise AssertionError('Timed out')


class DatabaseWritersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.a = TelemetryDatabase(self.root/'a.db', 'simulation')
        self.b = PIDDatabase(self.root/'b.db')

    def tearDown(self):
        self.a.stop()
        self.b.writer.close()
        self.a.writer.done.wait(3)
        self.b.writer.done.wait(3)
        self.tmp.cleanup()

    def test_idle_pages_and_arming_do_not_create_b(self):
        p = SimpleNamespace(pid_enabled=False, tuning_session_active=True)
        recorder = PagePIDRecorder(p, self.b, self.a, None)
        recorder.poll()
        recorder.poll(reason='Cancelled before first PID')
        recorder.close()
        self.assertFalse(self.b.writer.status()['started'])
        self.assertFalse((self.root/'b.db').exists())

    def test_session_stops_but_keeps_recovery_events(self):
        p = SimpleNamespace(pid_enabled=True, tuning_session_active=True, backend=None,
                            backend_mode='simulation', workspace=object())
        recorder = PagePIDRecorder(p, self.b, self.a, None)
        recorder.started(dict(setpoint=100))
        session = recorder.session
        p.pid_enabled = False
        recorder.poll(reason='Trial complete')
        self.assertEqual(recorder.session, session)
        recorder.event('recovery', {'tc_channel': 10})
        p.tuning_session_active = False
        recorder.poll(reason='Finished recovery')
        self.assertIsNone(recorder.session)
        self.b.writer.close()
        self.assertTrue(self.b.writer.done.wait(3))
        with closing(sqlite3.connect(self.root/'b.db')) as c:
            self.assertIsNotNone(c.execute('SELECT ended_at FROM pid_sessions').fetchone()[0])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM pid_events WHERE event='recovery'").fetchone()[0], 1)

    def test_locked_a_does_not_block_b_or_producers_and_retries_without_duplicates(self):
        self.a.start()
        wait_for(lambda: self.a.writer.written == 1)
        lock = sqlite3.connect(self.root/'a.db')
        lock.execute('BEGIN IMMEDIATE')
        try:
            started = time.monotonic()
            for i in range(40):
                self.a.snapshot(dict(timestamp=time.time()+i, sequence_number=i,
                    channels=[dict(actual=50, raw=50)],
                    beam=dict(current_ua=.1, display_ua=.09, quality='ok')))
            session = self.b.start(page='test', engine='cpp', feedback_source='calibrated_beam',
                                   environment='simulation', configuration={})
            self.b.sample(session, timestamp=time.time(), tc_channel=10, tc_actual_a=800,
                          tc_command_a=801, beam_na=100, beam_target_na=101, sample_kind='controller_update')
            self.assertLess(time.monotonic()-started, .5)
            wait_for(lambda: self.b.writer.written == 2)
            self.assertEqual(self.a.writer.written, 1)
        finally:
            lock.rollback()
            lock.close()
        wait_for(lambda: self.a.writer.written == 41)
        with closing(sqlite3.connect(self.root/'a.db')) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM readings WHERE channel='ch1'").fetchone()[0], 40)
            self.assertEqual(c.execute("SELECT engineering_value FROM readings WHERE channel='beam_control_current' LIMIT 1").fetchone()[0], .1)

    def test_full_queue_reserves_stop_event_and_reports_gaps(self):
        writer = AsyncSQLiteWriter(self.root/'limited.db',
            lambda c: c.execute('CREATE TABLE IF NOT EXISTS sample (value INTEGER)'),
            name='test', capacity=8, reserve=2)
        writer.submit([Statement('INSERT INTO sample VALUES (?)', ((-1,),))])
        wait_for(lambda: writer.written == 1)
        lock = sqlite3.connect(self.root/'limited.db')
        lock.execute('BEGIN IMMEDIATE')
        try:
            for i in range(100):
                writer.submit([Statement('INSERT INTO sample VALUES (?)', ((i,),))])
            self.assertGreater(writer.rejected, 0)
            self.assertTrue(writer.submit([Statement('INSERT INTO sample VALUES (?)', ((999,),))], critical=True))
            started = time.monotonic()
            writer.close()
            self.assertLess(time.monotonic()-started, .05)
        finally:
            lock.rollback()
            lock.close()
        self.assertTrue(writer.done.wait(3))
        with closing(sqlite3.connect(self.root/'limited.db')) as c:
            self.assertEqual(c.execute('SELECT value FROM sample ORDER BY rowid DESC LIMIT 1').fetchone()[0],999)
            self.assertEqual(c.execute('SELECT SUM(rejected_messages) FROM recording_gaps').fetchone()[0],writer.rejected)

    def test_unwritable_path_reports_fault_and_shutdown_is_bounded(self):
        bad = self.root/'not-a-directory'
        bad.write_text('file')
        b = PIDDatabase(bad/'pid.db')
        b.start(page='test', configuration={})
        wait_for(lambda: bool(b.writer.error))
        b.writer.close(timeout=.15)
        self.assertTrue(b.writer.done.wait(1))
        self.assertGreater(b.writer.pending, 0)
        self.assertIn('uncommitted', b.writer.error)


class PageRecordingTest(unittest.TestCase):
    setUp = DatabaseWritersTest.setUp
    tearDown = DatabaseWritersTest.tearDown
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_ga_cpp_and_python_capture_real_step_and_stop(self):
        from GAPIDTest import Backend
        from python.app.Automation.GAPIDPage import GAPIDPage, PythonGAPIDPage
        for cls in (GAPIDPage, PythonGAPIDPage):
            backend = Backend()
            page = cls(lambda: None, 'simulation', shared_backend=backend,
                       get_beam_state=backend.beam)
            page._database_recorder = PagePIDRecorder(page, self.b, self.a, backend.beam)
            try:
                page.workspace.setpoint_spin.setValue(1.2)
                backend.stamp = time.time()
                page.workspace.start_pid()
                self.assertTrue(page.pid_enabled, page.workspace.pid_status_label.text())
                backend.stamp = time.time()
                page.workspace._pid_step()
                page.workspace.stop_pid(reason='Test completed')
                self.assertEqual(page._database_recorder.error, '')
                self.assertIsNone(page._database_recorder.session)
            finally:
                page.stop_backend()
                page.deleteLater()
        self.b.writer.close()
        self.assertTrue(self.b.writer.done.wait(3))
        with closing(sqlite3.connect(self.root/'b.db')) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM pid_sessions').fetchone()[0], 2)
            rows = c.execute('SELECT beam_na,beam_target_na,tc_channel,feedback_unit,sample_kind FROM pid_samples').fetchall()
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(r == (1,1.2,10,'nA','controller_update') for r in rows), rows)

    def test_history_loads_from_worker_during_a_write_lock(self):
        from python.app.Monitoring.DatabaseHistoryPage import DatabaseHistoryPage
        self.a.snapshot(dict(timestamp=time.time(), channels=[dict(actual=50, raw=50)]))
        wait_for(lambda: self.a.writer.written == 2)
        lock = sqlite3.connect(self.root/'a.db')
        lock.execute('BEGIN IMMEDIATE')
        page = DatabaseHistoryPage(lambda: None, db_path=self.root/'a.db')
        try:
            end = time.monotonic()+3
            while not page.last_rows and time.monotonic() < end:
                self.app.processEvents()
                time.sleep(.01)
            self.assertTrue(page.last_rows, page.status_label.text())
            self.assertIn((50.0, 'engineering'), [(r[2],r[3]) for r in page.last_rows])
        finally:
            lock.rollback()
            lock.close()
            page.close()
            page.deleteLater()

    def test_python_continuous_keeps_coil_and_beam_units_separate(self):
        from PythonPIDPageTest import Backend
        from python.app.Automation.PythonPIDPage import PythonPIDPage
        backend = Backend()
        page = PythonPIDPage(lambda: None, 'simulation', shared_backend=backend)
        page.timer.stop()
        page.run_metrics.directory = self.root/'exports'
        page.log_path = self.root/'commands.csv'
        page._database_recorder = PagePIDRecorder(page, self.b, self.a,
            lambda: dict(timestamp=backend.timestamp, current_ua=.1, quality='ok'))
        try:
            page.channel_on[0] = page.channel_enabled[0] = True
            page.setpoint_input.setValue(10)
            page.arm_button.setChecked(True)
            page.enable_button.setChecked(True)
            self.assertTrue(page.pid_enabled)
            page._tick_pid_controller()
            backend.timestamp += .1
            page._tick_pid_controller()
            page._stop_pid('Test stop')
            self.assertEqual(page._database_recorder.error, '')
        finally:
            page.stop_backend()
            page.deleteLater()
        self.b.writer.close()
        self.assertTrue(self.b.writer.done.wait(3))
        with closing(sqlite3.connect(self.root/'b.db')) as c:
            row = c.execute("SELECT beam_na,beam_target_na,feedback,target,feedback_unit FROM pid_samples WHERE sample_kind='controller_update'").fetchone()
            self.assertEqual(row, (100,None,1,10,'A'))
        from source.Python.Data.file_writer import file_writer
        file_writer.submit(lambda: None).result(3)

    def test_hybrid_records_trial_cost_and_recovery_after_actual_start(self):
        from HybridPIDTest import PageTest
        fixture = PageTest('test_real_cpp_trials_share_cost_and_restore_before_next')
        fixture.app = self.app
        fixture.setUp()
        page = fixture.p
        page._database_recorder = PagePIDRecorder(page, self.b, self.a, page.get_beam_state)
        try:
            page._start_auto_tuning()
            self.assertTrue(page.recovering)
            self.assertFalse(self.b.writer.status()['started'])
            fixture.tick_until(lambda: len(page.tuning_results) >= 1)
            self.assertEqual(page._database_recorder.error, '')
            page._stop_tuning_session()
            self.assertIsNone(page._database_recorder.session)
        finally:
            fixture.tearDown()
        self.b.writer.close()
        self.assertTrue(self.b.writer.done.wait(3))
        with closing(sqlite3.connect(self.root/'b.db')) as c:
            row = c.execute('SELECT source,result FROM pid_trials ORDER BY timestamp LIMIT 1').fetchone()
            self.assertEqual(row[0], 'Baseline')
            self.assertIn('score', row[1])
            self.assertGreater(c.execute("SELECT COUNT(*) FROM pid_events WHERE details LIKE '%recovery%'").fetchone()[0], 0)


    def test_native_cpp_continues_while_b_locked_and_gui_heartbeat_runs(self):
        from PySide6.QtCore import QTimer
        from python.app.Automation.PidControlPage import PidControlPage
        page = PidControlPage(lambda: None, 'simulation',
            get_beam_state=lambda: dict(timestamp=time.time(), current_ua=.001, quality='ok'))
        page.run_metrics.directory = self.root/'exports'
        page.log_path = self.root/'commands.csv'
        page._database_recorder = PagePIDRecorder(page, self.b, self.a, page.get_beam_state)
        lock = None
        heartbeat = []
        timer = QTimer()
        timer.timeout.connect(lambda: heartbeat.append(time.monotonic()))
        timer.start(10)
        try:
            page.backend.SetChannelCommand(0, 50, True, True)
            page.backend.ApplyCommand()
            time.sleep(.08)
            page._tick_feedback()
            page.setpoint_input.setValue(1.1)
            page.arm_button.setChecked(True)
            page.enable_button.setChecked(True)
            self.assertTrue(page.pid_enabled, page.last_safety_message)
            wait_for(lambda: self.b.writer.written > 0)
            lock = sqlite3.connect(self.root/'b.db')
            lock.execute('BEGIN IMMEDIATE')
            before = page.backend.PidTrialStatus()['iterations']
            end = time.monotonic()+.6
            while time.monotonic() < end:
                self.app.processEvents()
                time.sleep(.005)
            self.assertGreater(len(heartbeat), 5)
            self.assertGreater(page.backend.PidTrialStatus()['iterations'], before)
            self.assertTrue(page.pid_enabled)
            page._stop_pid('Test stop')
            self.assertEqual(page._database_recorder.error, '')
        finally:
            timer.stop()
            if lock:
                lock.rollback()
                lock.close()
            page.stop_backend()
            page.deleteLater()
        self.b.writer.close()
        self.assertTrue(self.b.writer.done.wait(3))
        with closing(sqlite3.connect(self.root/'b.db')) as c:
            self.assertGreater(c.execute('SELECT COUNT(*) FROM pid_samples').fetchone()[0], 0)
        from source.Python.Data.file_writer import file_writer
        file_writer.submit(lambda: None).result(3)


class ZWindowRecordingTest(unittest.TestCase):
    def test_all_pages_attached_idle_and_async_close(self):
        from PySide6.QtWidgets import QApplication
        from python.app.MainWindow import MainWindow
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'a.db'
            window = MainWindow('simulation', 'tcp://127.0.0.1:5599', db_path=path,
                                enable_data_pipeline=True)
            try:
                for name in ('PID Control', 'PythonPID', 'GA + C++ PID', 'GA + Python PID', 'Hybrid GA + BO PID'):
                    self.assertIsNotNone(window.pages[name]._database_recorder)
                self.assertFalse(window.database_b.writer.status()['started'])
                end = time.monotonic()+.3
                while time.monotonic() < end:
                    app.processEvents()
                    time.sleep(.01)
                window.close()
                end = time.monotonic()+5
                while not window._recording_closed and time.monotonic() < end:
                    app.processEvents()
                    time.sleep(.01)
                self.assertTrue(window._recording_closed)
                self.assertEqual(window.database_a.writer.error, '')
                self.assertFalse(path.with_name('crocker_pid.sqlite3').exists())
                self.assertGreater(window.database_a.writer.written, 1)
            finally:
                window.close()
                for page in window.pages.values():
                    if hasattr(page, 'stop_backend'):
                        page.stop_backend()
                window.deleteLater()
                app.processEvents()



if __name__ == '__main__':
    unittest.main()
