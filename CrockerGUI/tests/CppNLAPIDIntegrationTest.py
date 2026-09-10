"""Real ControlService simulator and NLA Bayesian page integration tests."""
import os
import sys
import time
import unittest
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import CycloViz
from PySide6.QtWidgets import QApplication
from python.app.Automation.PidControlPage import PidControlPage


def config(**overrides):
    result = dict(controller_kind="nla", measurement_channel=0, setpoint=10.0,
                  kp=0.8, ki=0.05, kd=0.0, update_rate_hz=40.0, duration_seconds=0.4,
                  telemetry_timeout_seconds=0.5, allocation=[1.0] + [0.0] * 13,
                  command_bias=[0.0] * 14, minimum_command=[0.0] * 14,
                  maximum_command=[100.0] * 14, maximum_slew_per_second=[100.0] * 14,
                  allocation_calibrated=False, hardware_armed=True, dry_run=False,
                  nla_output_max=0.5)
    result.update(overrides)
    return result


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out")


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.service = CycloViz.ControlService()
        self.service.StartSimulator(100)

    def tearDown(self):
        self.service.Stop()

    def test_live_simulation_and_diagnostics(self):
        self.service.StartPidTrial(config())
        wait_for(lambda: self.service.PidTrialStatus()['state'] != 'Running')
        status = self.service.PidTrialStatus()
        self.assertEqual(status['state'], 'Completed')
        self.assertEqual(status['controller_kind'], 'nla')
        self.assertGreater(status['iterations'], 0)
        self.assertGreater(status['command_target'], 0)
        self.assertGreater(self.service.LatestSnapshot()['channels'][0]['actual'], 0)
        self.assertGreaterEqual(status['calculation_us'], 0)
        self.assertIn('direction', status['nla'])

    def test_dry_run_and_continuous_stop(self):
        sent_before = self.service.Health()['sent_packets']
        self.service.StartPidTrial(config(dry_run=True, continuous=True, duration_seconds=0.05))
        wait_for(lambda: self.service.PidTrialStatus()['iterations'] >= 5)
        status = self.service.PidTrialStatus()
        self.assertEqual(status['state'], 'Running')
        self.assertGreater(status['command_target'], 0)
        self.assertEqual(self.service.PendingCommand()[0]['target'], 0)
        self.assertEqual(self.service.LatestSnapshot()['channels'][0]['actual'], 0)
        self.service.StopPidTrial(True)
        self.assertEqual(self.service.PidTrialStatus()['state'], 'Stopped')
        self.assertEqual(self.service.Health()['sent_packets'], sent_before)

    def test_no_repeated_sample_and_validation(self):
        self.service.StartSimulator(5)
        self.service.StartPidTrial(config(update_rate_hz=100, duration_seconds=0.6))
        wait_for(lambda: self.service.PidTrialStatus()['state'] != 'Running')
        self.assertLessEqual(self.service.PidTrialStatus()['iterations'], 4)
        with self.assertRaises(ValueError):
            self.service.StartPidTrial(config(allocation=[0.5, 0.5] + [0.0] * 12))
        with self.assertRaises(ValueError):
            self.service.StartPidTrial(config(nla_max_control_dt=float('nan')))
        self.service.StartPidTrial(config(telemetry_timeout_seconds=1e-9, dry_run=True))
        wait_for(lambda: self.service.PidTrialStatus()['state'] != 'Running')
        self.assertEqual(self.service.PidTrialStatus()['state'], 'Faulted')


class PageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.page = PidControlPage(lambda: None, 'simulation')
        self.page.timer.stop()
        self.page._log_command = lambda *args: None
        self.page.controller_kind_input.setCurrentIndex(1)

    def tearDown(self):
        self.page.stop_backend()
        self.page.deleteLater()

    def test_continuous_page_uses_service(self):
        p = self.page
        p.channel_on[0] = p.channel_enabled[0] = True
        p.setpoint_input.setValue(10)
        p.arm_button.setChecked(True)
        p.enable_button.setChecked(True)
        self.assertTrue(p._service_pid_active)
        wait_for(lambda: p.backend.PidTrialStatus()['iterations'] >= 3)
        p._tick_pid_controller()
        self.assertGreater(p.command_values[0], 0)
        self.assertEqual(p.backend.PendingCommand()[0]['target'], 0)  # default dry run
        p.enable_button.setChecked(False)
        self.assertFalse(p._service_pid_active)
        self.assertEqual(p.backend.PidTrialStatus()['state'], 'Stopped')

    def test_seven_bayesian_nla_trials(self):
        p = self.page
        p.tuner_trials.setValue(7)
        p.tuner_duration.setValue(0.5)
        p.tuner_target.setValue(10)
        p._start_auto_tuning()
        deadline = time.monotonic() + 120
        observed = 0
        while p.tuning_session_active and time.monotonic() < deadline:
            self.app.processEvents()
            p._poll_tuning_workflow()
            if len(p.tuning_results) != observed:
                observed = len(p.tuning_results)
                print(f"NLA trial {observed}: {p.tuning_results[-1].score:.4f}", flush=True)
            time.sleep(0.02)
        self.assertEqual(len(p.tuning_results), 7, p.tuner_status.text())
        self.assertTrue(all(r.safe and r.controller_kind == 'nla' for r in p.tuning_results))
        self.assertTrue(p.tuning_optimizer.optimizer._botorch_ready)  # passed Sobol initialization
        self.assertEqual(p.backend.PidTrialStatus()['controller_kind'], 'nla')
        self.assertFalse(p.pid_enabled)
        p._validate_best_gains()
        p._apply_tuned_gains()
        self.assertEqual(p.controller_kind_input.currentData(), 'nla')
        self.assertFalse(p.pid_enabled)


if __name__ == '__main__':
    unittest.main()
