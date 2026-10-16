"""Exercise the public Start/Stop path from a disabled first-order output."""
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import zmq
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from python.app.MainWindow import MainWindow


class FirstOrderStartTest(unittest.TestCase):
    def test_public_start_stop_restart_from_disabled_output(self):
        app = QApplication.instance() or QApplication([])
        output = ROOT / 'logs' / 'first-order-start' / uuid4().hex
        output.mkdir(parents=True)
        settings = QSettings(str(output / 'settings.ini'), QSettings.IniFormat)
        with patch('python.app.MainWindow.QSettings', return_value=settings):
            window = MainWindow('zmq', 'tcp://127.0.0.1:5555', simulation_mode='first-order',
                                db_path=output / 'telemetry.sqlite3')
        page = window.pages['PID Control']
        page.log_path = output / 'commands.csv'
        page.run_metrics.directory = output / 'exports'

        def wait(predicate):
            deadline = time.monotonic() + 6
            while not predicate() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            self.assertTrue(predicate(), page.last_safety_message)

        try:
            wait(lambda: window.current_beam_state().get('quality') == 'ok')
            page.backend.SetChannelCommand(9, 0, False, False)
            page.backend.ApplyCommand()
            wait(lambda: not page.backend.LatestSnapshot()['channels'][9]['enabled'])
            for _ in range(3):
                page._start_cruise()
                wait(lambda: page.pid_enabled and page.cruise.active)
                self.assertIsNotNone(page._failure_recovery.reference)
                self.assertEqual(page.backend.PidTrialStatus()['state'], 'Running')
                page._stop_cruise()
                wait(lambda: not page.backend.LatestSnapshot()['channels'][9]['enabled'])
                self.assertFalse(page.pid_enabled)
                self.assertFalse(page.cruise.active)
            # A Stop during the acknowledgement wait invalidates delayed Starts.
            page._start_cruise()
            page._stop_cruise()
            deadline = time.monotonic() + .3
            while time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            self.assertFalse(page.pid_enabled)
            self.assertFalse(page.backend.PendingCommand()[9]['enabled'])
        finally:
            window.close()
            wait(lambda: window._recording_closed)


if __name__ == '__main__':
    unittest.main()
