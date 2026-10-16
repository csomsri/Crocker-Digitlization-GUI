"""A deliberate Stop must allow a fresh BO session without reopening the page."""
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from python.app.Automation.PidControlPage import PidControlPage
from source.Python.Optimization.pid_gain_adapter import PidGainCandidate


class Optimizer:
    def __init__(self, *args, **kwargs):
        self.safe_results = []
        from types import SimpleNamespace
        self.optimizer = SimpleNamespace(initial_safe_trials=6)
        self.best_result = None
        self.rejected_validation_candidates = set()

    def propose_batch(self, count):
        return [PidGainCandidate(.5, .1, 0)]


class BORestartTest(unittest.TestCase):
    def test_stop_and_restart_three_times_with_verified_reference(self):
        app = QApplication.instance() or QApplication([])
        p = PidControlPage(lambda: None, 'simulation',
            get_beam_state=lambda: dict(timestamp=time.time(), current_ua=.001, quality='ok'))
        native = p.backend

        class VerifiedTransport:
            def __getattr__(self, name):
                return getattr(native, name)

            def LatestSnapshot(self):
                # Use the actual native simulator, but require the same verified
                # reference capture as first-order ZMQ/hardware transports.
                return dict(native.LatestSnapshot(), simulated=False)

        p.backend = VerifiedTransport()
        p._log_command = lambda *args: None
        p._request_surrogate_grid = lambda: None
        p.nla_window_input.setValue(.05)
        p.tuner_duration.setValue(10)

        def pump_until(predicate):
            deadline = time.monotonic() + 5
            while not predicate() and time.monotonic() < deadline:
                app.processEvents()
                p._tick_feedback()
                time.sleep(.01)
            self.assertTrue(predicate(), p.tuner_status.text())

        try:
            native.SetChannelCommand(0, 50, True, True)
            native.ApplyCommand()
            pump_until(lambda: native.LatestSnapshot()['channels'][0]['enabled'])
            with patch('python.app.Automation.PidControlPage.BotorchPidOptimizer', Optimizer):
                for attempt in range(3):
                    p.auto_tuning_button.click()
                    pump_until(lambda: p.tuning_trial_candidate is not None)
                    self.assertEqual(native.PidTrialStatus()['state'], 'Running')
                    if attempt == 1:
                        p.cruise_navigation.stop_button.click()
                    else:
                        p.stop_tuning_button.click()
                    self.assertFalse(p.tuning_session_active)
                    self.assertTrue(p.auto_tuning_button.isEnabled())
                    self.assertFalse(native.PendingCommand()[0]['enabled'])
                # Stop while the enable acknowledgement is pending; its delayed
                # callback must never restart a trial or re-enable the output.
                p.tuning_session_active = True
                p.tuning_candidate = PidGainCandidate(.5, .1, 0)
                p._run_tuning_trial()
                self.assertIsNotNone(p._tuning_enable_pending)
                p._stop_tuning_session()
                for _ in range(15):
                    app.processEvents()
                    time.sleep(.01)
                self.assertIsNone(p.tuning_trial_candidate)
                self.assertFalse(p.tuning_session_active)
                self.assertFalse(native.PendingCommand()[0]['enabled'])
                from types import SimpleNamespace
                p.tuning_optimizer.best_result = SimpleNamespace(candidate=PidGainCandidate(.5, .1, 0), score=1.0)
                p._validate_best_gains()
                self.assertTrue(p._validating_gains)
                pump_until(lambda: p.tuning_trial_candidate is not None)
                self.assertEqual(native.PidTrialStatus()['state'], 'Running')
                p._stop_tuning_session()
        finally:
            p.stop_backend()
            p.deleteLater()


if __name__ == '__main__':
    unittest.main()
