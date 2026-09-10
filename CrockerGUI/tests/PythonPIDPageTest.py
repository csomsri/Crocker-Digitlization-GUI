"""Headless Python NLA page integration checks; no hardware or C++ build required."""
import os
import sys
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from python.app.Automation.PidControlPage import PidControlPage
from python.app.Automation.PythonPIDPage import PythonPIDPage
from python.app.PageRegistry import DETAIL_BUILDERS


class Backend:
    def __init__(self):
        self.timestamp = time.time()
        self.accept = True
        self.writes = 0

    def Health(self):
        return dict(connection="Connected", endpoint="test", received_packets=1)

    def LatestSnapshot(self):
        return dict(timestamp=self.timestamp, channels=[dict(actual=1.0)])

    def PendingCommand(self):
        return [dict(target=2.0)]

    def SetChannelCommand(self, *args):
        self.writes += 1

    def ApplyCommand(self):
        return self.accept


class PythonPIDPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.backend = Backend()
        self.page = PythonPIDPage(lambda: None, "simulation", shared_backend=self.backend)
        self.page.timer.stop()
        self.page._log_command = lambda *args: None
        self.page.channel_on[0] = self.page.channel_enabled[0] = True
        self.page.setpoint_input.setValue(10)
        self.page.arm_button.setChecked(True)
        self.page.enable_button.setChecked(True)

    def tearDown(self):
        self.page.stop_backend()
        self.page.deleteLater()

    def test_increment_and_duplicate_sample(self):
        p = self.page
        self.assertIs(DETAIL_BUILDERS["PythonPID"][1], PythonPIDPage)
        self.assertEqual(p.page_stack.count(), 2)
        self.assertEqual(p.command_values[0], 2.0)
        p._tick_pid_controller()
        self.backend.timestamp += 0.1
        p._tick_pid_controller()
        self.assertAlmostEqual(p.command_values[0], 2.0 + p.pid.last_result.output)
        self.assertGreater(p.pid.last_result.output, 0)
        previous = p.command_values[0]
        p._tick_pid_controller()
        self.assertEqual(previous, p.command_values[0])

    def test_rejection_stops_without_retry(self):
        p = self.page
        p.dry_run_check.setChecked(False)
        p._tick_pid_controller()
        self.backend.timestamp += 0.1
        self.backend.accept = False
        p._tick_pid_controller()
        self.assertFalse(p.pid_enabled)
        self.assertEqual(self.backend.writes, 1)
        self.assertEqual(p.command_values[0], 2.0)

    def test_deadband_and_stale_telemetry(self):
        p = self.page
        p.setpoint_input.setValue(1)
        p._tick_pid_controller()
        self.backend.timestamp += 0.1
        p._tick_pid_controller()
        self.assertTrue(p.pid.last_result.in_deadband)
        self.assertEqual(p.command_values[0], 2.0)
        self.backend.timestamp = time.time() - 3
        p._tick_pid_controller()
        self.assertFalse(p.pid_enabled)

    def test_original_page_cannot_run_concurrently(self):
        other = PidControlPage(lambda: None, "simulation", shared_backend=self.backend)
        other.timer.stop()
        try:
            other.channel_on[0] = other.channel_enabled[0] = True
            other.arm_button.setChecked(True)
            other.enable_button.setChecked(True)
            self.assertFalse(other.pid_enabled)
            self.assertIn("Another PID", other.last_safety_message)
        finally:
            other.stop_backend()
            other.deleteLater()


if __name__ == "__main__":
    unittest.main()
