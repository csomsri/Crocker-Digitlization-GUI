"""Shared response scoring and actual Python NLAPID Bayesian trials."""
import os
import sys
import time
import math
import unittest
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source.Python.Optimization.trial_metrics import evaluate_trial, trial_cost


class MetricsTest(unittest.TestCase):
    def test_five_term_cost_and_actual_movement(self):
        # A large constant command costs no movement; only changes count.
        rows = [(0, 8, 2, 100, 100, False),
                (1, 9, 1, 100, 103, True),
                (3, 10, 0, 100, 101, False)]
        m = evaluate_trial(rows, 10)
        self.assertEqual(m.tracking_error, 1)
        self.assertEqual(m.command_movement, 5)
        self.assertEqual(m.saturation_time, 1)
        self.assertEqual(m.steady_state_error, 0)
        self.assertAlmostEqual(trial_cost(m), 11.05)
        self.assertAlmostEqual(trial_cost(m, 'Fast response'), 13.05)
        self.assertAlmostEqual(trial_cost(m, 'Low control movement'), 11.4)

    def test_missing_actuator_data_cannot_be_scored(self):
        m = evaluate_trial([(0, 10, 0, 0), (1, 10, 0, 0)], 10)
        with self.assertRaises(ValueError):
            trial_cost(m)

    def test_no_extra_unsettled_penalty(self):
        from dataclasses import replace
        m = evaluate_trial([(0, 10, 0, 0, 100, False), (1, 10, 0, 0, 100, False)], 10)
        self.assertEqual(trial_cost(m), 0)
        self.assertEqual(trial_cost(replace(m, settled=False)), 0)

    def test_settling_and_first_entry_are_distinct(self):
        errors = [2,1,.05,1,.05,.04,.03,.02,.01,0]
        rows = [(i*.2, 10-e, e, 0) for i,e in enumerate(errors)]
        m = evaluate_trial(rows, 10)
        self.assertAlmostEqual(m.transient_time,.4)
        self.assertAlmostEqual(m.settling_time,.8)
        self.assertTrue(m.settled)
        self.assertFalse(m.sustained_oscillation)

    def test_oscillation_penalized_including_offset(self):
        rows = [(i*.05, 10-(2+math.sin(i*.05*math.tau*2)), 2+math.sin(i*.05*math.tau*2), 0, 0, False) for i in range(100)]
        m = evaluate_trial(rows, 10)
        self.assertTrue(m.sustained_oscillation)
        self.assertGreater(m.oscillation_cycles, 2)
        self.assertGreater(m.oscillation_penalty, 100)
        flat = evaluate_trial([(i*.05,8,2,0,0,False) for i in range(100)],10)
        self.assertGreater(trial_cost(m),trial_cost(flat))

    def test_noise_and_insufficient_data(self):
        m=evaluate_trial([(i*.1,10+(.02 if i%2 else -.02),(.02 if i%2 else -.02),0) for i in range(30)],10)
        self.assertEqual(m.oscillation_penalty,0)
        self.assertTrue(m.settled)
        with self.assertRaises(ValueError): evaluate_trial([(0,0,0,0)],10)

    def test_overshoot_is_diagnostic_only(self):
        from dataclasses import replace
        m=evaluate_trial([(i*.1,10,0,0,0,False) for i in range(30)],10)
        self.assertEqual(trial_cost(m),trial_cost(replace(m,overshoot=100)))


class PythonBOTest(unittest.TestCase):
    def test_same_ui_seven_python_trials(self):
        import torch
        torch.set_num_threads(1)
        from PySide6.QtWidgets import QApplication, QTableWidget
        from python.app.Automation.PythonPIDPage import PythonPIDPage
        from python.app.Automation.PidControlPage import PidControlPage
        app=QApplication.instance() or QApplication([])
        p=PythonPIDPage(lambda:None,'simulation')
        p.timer.stop()
        p._log_command=lambda *args:None
        native=p.backend
        class TransportOnly:
            def __getattr__(self,name): return getattr(native,name)
            def StartPidTrial(self,*args): raise AssertionError('Python trials must not run the C++ PID')
        p.backend=TransportOnly()
        try:
            self.assertEqual(p.page_stack.count(),2)
            p._show_tuner()
            self.assertIn('Python',p.tuner_engine_label.text())
            p.tuner_trials.setValue(7)
            p.tuner_duration.setValue(.5)
            p.tuner_target.setValue(10)
            p._start_auto_tuning()
            p.tuning_optimizer.optimizer.mc_samples=32
            p.tuning_optimizer.optimizer.num_restarts=2
            p.tuning_optimizer.optimizer.raw_samples=32
            deadline=time.monotonic()+100
            while p.tuning_session_active and time.monotonic()<deadline:
                app.processEvents()
                p._poll_tuning_workflow()
                time.sleep(.015)
            self.assertEqual(len(p.tuning_results),7,p.tuner_status.text())
            self.assertTrue(all(r.safe and r.controller_kind=='python_nla' and r.metrics for r in p.tuning_results))
            self.assertTrue(p.tuning_optimizer.optimizer._botorch_ready)
            self.assertEqual(native.PidTrialStatus()['state'],'Idle')
            dialog=p._build_metrics_dialog()
            self.assertEqual(dialog.findChild(QTableWidget,'pidResponseMetrics').rowCount(),7)
            dialog.close()
            p._validate_best_gains()
            self.assertFalse(p.apply_tuned_gains_button.isEnabled())
            self.assertTrue(p._validating_gains)
            p._stop_tuning_session()
            p._apply_tuned_gains()
            self.assertFalse(p.pid_enabled)
            other=PidControlPage(lambda:None,'simulation',manage_backend=False)
            other.timer.stop()
            other.tuning_results=list(p.tuning_results)
            dialog=other._build_metrics_dialog()
            self.assertEqual(dialog.findChild(QTableWidget,'pidResponseMetrics').columnCount(),14)
            dialog.close()
            other.stop_backend()
            # A persistent response is stopped while running, not just scored
            # after completion. Preserve the observation for BO's penalty.
            p.tuning_samples=[(i*.05, 10-(2+math.sin(i*.05*math.tau*2)),
                               2+math.sin(i*.05*math.tau*2), 0, 0, False) for i in range(100)]
            p.tuning_session_active=True
            p.tuning_trial_candidate=p.tuning_results[0].candidate
            p._trial_status=lambda:dict(state='Running',elapsed_seconds=4.95,
                measured_field=8,error=2,control_output=0,control_rate=0,iterations=99)
            stopped=[]
            p._complete_tuning_trial=lambda safe:stopped.append(safe)
            p._poll_tuning_workflow()
            self.assertEqual(stopped,[True])
            self.assertTrue(p._oscillation_stopped)
        finally:
            p.stop_backend()


if __name__=='__main__': unittest.main()
