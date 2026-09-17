"""Approval requires a long measured response; gain transfer preserves precision."""
import os, sys, unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from python.app.Automation.PidControlPage import PidControlPage
from source.Python.Optimization.pid_gain_adapter import PidGainCandidate
from source.Python.Optimization.trial_metrics import evaluate_trial
app = QApplication.instance() or QApplication([])

class ValidationTest(unittest.TestCase):
    def setUp(self):
        self.p = PidControlPage(lambda: None, 'simulation', manage_backend=False)
        self.p.timer.stop()
        self.p._stop_trial = lambda disable: None
        self.p._finish_tuning_session = lambda: None
        self.p._oscillation_stopped = False
        self.p._tuning_controller_config = self.p._controller_config()
        self.c = PidGainCandidate(1.23456789123, .00012345678, .00098765432)
    def tearDown(self):
        self.p.stop_backend()
    def finish(self, duration, error=0, oscillating=False):
        p = self.p
        p.tuning_samples = [(0, 10-error, error, 0, 10, False), (duration, 10-error, error, 0, 10, False)]
        p._oscillation_stopped = oscillating
        p._finish_gain_validation(self.c, evaluate_trial(p.tuning_samples, 10), True)
    def test_reject_short_unsettled_and_oscillating(self):
        for duration,error,osc in [(10,0,False),(60,5,False),(60,0,True)]:
            self.finish(duration,error,osc)
            self.assertFalse(self.p.apply_tuned_gains_button.isEnabled())
            self.assertIsNone(self.p.apply_tuned_gains_button.property('approvedCandidate'))
    def test_validated_gain_precision_and_frozen_target(self):
        self.p.tuner_target.setValue(10)
        self.finish(60)
        self.assertTrue(self.p.apply_tuned_gains_button.isEnabled())
        self.p.tuner_target.setValue(99)
        self.p._apply_tuned_gains()
        self.assertEqual(self.p.setpoint_input.value(),10)
        for widget,expected in [(self.p.kp_input,self.c.kp),(self.p.ki_input,self.c.ki),(self.p.kd_input,self.c.kd)]:
            self.assertAlmostEqual(widget.value(),expected,places=11)
        self.assertFalse(self.p.pid_enabled)

if __name__ == '__main__': unittest.main()
