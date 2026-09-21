"""Hybrid state-machine and real C++ beam-PID/recovery tests; no hardware."""
import os
import sys
import time
import unittest
import math
from dataclasses import replace
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from source.Python.Optimization.hybrid_pid_optimizer import HybridPIDOptimizer, HybridConfig
from source.Python.Optimization.pid_gain_adapter import PidGainCandidate, PidTrialResult
from source.Python.Optimization.trial_metrics import evaluate_trial, trial_cost


def result(candidate,cost=10,safe=True,settled=True,beam_mae=None):
    error = cost*.001 if beam_mae is None else beam_mae
    metrics = evaluate_trial([(0,1-error,error,0,50,0),(1,1-error,error,0,50,0)],1)
    metrics = replace(metrics,settled=settled)
    return PidTrialResult(candidate,cost,0,0,0,0,safe,metrics=metrics)


class PolicyTest(unittest.TestCase):
    def test_mae_is_time_weighted_and_not_integrated_error(self):
        m = evaluate_trial([(0,0,0,0,50,0),(1,0,4,0,50,0),(3,0,1,0,50,0)],1)
        self.assertEqual(m.tracking_error, 6)
        self.assertEqual(m.mean_absolute_error, 2)

    def test_lower_cost_with_equal_or_worse_beam_error_cannot_confirm(self):
        for error in (.01, .02, .0099):
            with self.subTest(error=error):
                o=self.make()
                self.warm(o)
                self.feed(o,1,beam_mae=error)
                self.assertEqual(o.phase,'GA')
                self.assertFalse(o.records[-1]['beam_error_gate']['passed'])

    def test_beam_noise_can_reject_challenger_despite_clear_cost_improvement(self):
        o=self.make()
        self.feed(o,10,beam_mae=.005)
        self.feed(o,10,beam_mae=.015)
        for _ in range(4):
            self.feed(o,10,beam_mae=.01)
        self.feed(o,1,beam_mae=.001)
        self.assertEqual(o.phase,'GA')
        self.assertGreater(o.records[-1]['beam_error_gate']['required_nA'], .009)

    def test_confirmation_rejects_error_regression_and_inconsistent_improvement(self):
        for errors in ((.02,.02,.02),(.009,.009,0)):
            with self.subTest(errors=errors):
                o=self.make()
                self.warm(o)
                self.feed(o,5,beam_mae=.005)
                self.assertEqual(o.phase,'Confirmation')
                index=0
                for _ in range(6):
                    c=o.propose_batch(1)[0]
                    is_bo=o.pending_source=='Confirm BO'
                    error=errors[index] if is_bo else .01
                    index += int(is_bo)
                    o.record_results([result(c,5 if is_bo else 10,beam_mae=error)])
                self.assertEqual(o.phase,'GA')
                self.assertFalse(o.records[-1]['beam_error_gate']['passed'])

    def test_missing_error_metric_cannot_confirm(self):
        o=self.make()
        self.warm(o)
        c=o.propose_batch(1)[0]
        r=result(c,1)
        o.record_results([replace(r,metrics=replace(r.metrics,mean_absolute_error=None))])
        self.assertEqual(o.phase,'GA')
        self.assertIsNone(o.records[-1]['beam_error_gate']['improvement_nA'])

    def make(self, **overrides):
        config=HybridConfig(population=4,baseline_repeats=2,minimum_distinct=4,coverage=.05,
                            plateau_trials=2,budget=40,**overrides)
        return HybridPIDOptimizer([(0,2)]*3,PidGainCandidate(.5,.5,.5),config,
            proposer=lambda:(PidGainCandidate(.2,.2,.2),5,.1))

    def feed(self,o,cost=10,**kwargs):
        c=o.propose_batch(1)[0]
        source=o.pending_source
        o.record_results([result(c,cost,**kwargs)])
        return source

    def warm(self,o):
        for _ in range(6):
            self.feed(o)
        self.assertEqual(o.phase,'GA')
        self.assertTrue(o.readiness()[0])

    def promote(self,o):
        self.warm(o)
        self.assertEqual(self.feed(o,5),'BO challenger')
        self.assertEqual(o.phase,'Confirmation')
        for _ in range(6):
            c=o.propose_batch(1)[0]
            o.record_results([result(c,5 if o.pending_source == 'Confirm BO' else 10)])
        self.assertEqual(o.phase,'BO')

    def test_ga_seeds_bo_without_any_sobol_proposals(self):
        o=self.make()
        o.optimizer._propose_sobol_batch=lambda _:self.fail('Hybrid must not ask BO for seed points')
        self.warm(o)
        self.assertEqual(len(o.optimizer.safe_observations),6)
        c=o.propose_batch(1)[0]
        self.assertEqual(o.pending_source,'BO challenger')
        self.assertEqual(o.phase,'BO challenger')
        self.assertNotEqual(o.phase,'BO')
        o.record_results([result(c,12)])
        self.assertEqual(o.phase,'GA')

    def test_measured_paired_handover_and_plateau_fallback(self):
        o=self.make()
        self.promote(o)
        self.feed(o,8)
        self.feed(o,8)
        self.assertEqual(o.phase,'GA')
        self.assertEqual(self.feed(o),'GA')

    def test_unsettled_challenger_never_takes_over(self):
        o=self.make()
        self.warm(o)
        self.feed(o,1,settled=False)
        self.assertEqual(o.phase,'GA')

    def test_noise_and_uncertainty_prevent_challenger_trial(self):
        o=self.make()
        self.feed(o,1)
        self.feed(o,19)
        for _ in range(4):
            self.feed(o,10)
        self.assertEqual(self.feed(o,10),'GA')
        o=self.make()
        self.warm(o)
        o._proposer=lambda:(PidGainCandidate(.2,.2,.2),1,20)
        self.assertEqual(self.feed(o),'GA')

    def test_fault_stops_and_is_excluded_from_training(self):
        o=self.make()
        self.feed(o,safe=False)
        self.assertEqual(o.phase,'Stopped')
        self.assertEqual(len(o.safe_results),0)
        self.assertIsNone(o.records[0]['cost'])
        with self.assertRaises(RuntimeError):
            o.propose_batch(1)

    def test_confirmation_budget_cannot_promote_on_partial_evidence(self):
        o=self.make()
        o.config=replace(o.config,budget=8)
        self.warm(o)
        self.feed(o,5)
        self.feed(o,10)
        with self.assertRaises(RuntimeError):
            o.propose_batch(1)
        self.assertEqual(o.phase,'Confirmation')

    def test_unstable_confirmation_and_mismatched_result(self):
        o=self.make()
        self.warm(o)
        self.feed(o,5)
        for i in range(6):
            c=o.propose_batch(1)[0]
            o.record_results([result(c,5 if o.pending_source=='Confirm BO' else 10,settled=i!=5)])
        self.assertEqual(o.phase,'GA')
        o.propose_batch(1)
        with self.assertRaises(ValueError):
            o.record_results([result(PidGainCandidate(99,99,99))])

    def test_real_botorch_proposal_uses_ga_observations_and_cost_units(self):
        o=self.make()
        for _ in range(6):
            c=o.propose_batch(1)[0]
            cost=1+sum((v-.25)**2 for v in (c.kp,c.ki,c.kd))
            o.record_results([result(c,cost)])
        o.optimizer.mc_samples=16
        o.optimizer.num_restarts=2
        o.optimizer.raw_samples=32
        c,mu,sigma=o._model_proposal()
        self.assertTrue(all(0<=v<=2 for v in (c.kp,c.ki,c.kd)))
        self.assertTrue(math.isfinite(mu) and math.isfinite(sigma) and sigma>=0)
        self.assertTrue(o.optimizer._botorch_ready)


class PageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from python.app.Automation.HybridPIDPage import HybridPIDPage
        self.p=HybridPIDPage(lambda:None,'simulation')
        p=self.p
        p.timer.stop()
        p.backend.SetChannelCommand(0,50,True,True)
        p.backend.ApplyCommand()
        self.revision=1
        def beam():
            s=p.backend.LatestSnapshot()
            # Test-only coupled plant: beam(nA) = 1 + .2*(TC actual - 50 A).
            return dict(current_ua=(1+.2*(s['channels'][0]['actual']-50))/1000,
                        timestamp=s['timestamp'],quality='ok',range_index=0,calibration_revision=self.revision)
        p.get_beam_state=beam
        deadline=time.monotonic()+3
        while abs(p.backend.LatestSnapshot()['channels'][0]['actual']-50)>.005 and time.monotonic()<deadline:
            time.sleep(.02)
        p._tick_feedback()
        p.hybrid_fields['warmup'].setValue(0)
        p.hybrid_fields['baseline_repeats'].setValue(2)
        p.hybrid_fields['population'].setValue(4)
        p.hybrid_fields['recovery_hold'].setValue(.1)
        p.hybrid_fields['recovery_step'].setValue(.1)
        p.hybrid_fields['beam_tolerance'].setValue(.01)
        p.hybrid_fields['actual_tolerance'].setValue(.03)
        p.tuner_duration.setValue(1)
        p.tuner_target.setValue(1.08)
        p.dry_run_check.setChecked(False)
        p.arm_button.setChecked(True)

    def tearDown(self):
        self.p.stop_backend()
        self.p.deleteLater()

    def tick_until(self,predicate,timeout=8):
        end=time.monotonic()+timeout
        while not predicate() and time.monotonic()<end:
            self.app.processEvents()
            self.p._tick_feedback()
            time.sleep(.03)
        self.assertTrue(predicate(),self.p.tuner_status.text())

    def test_real_cpp_trials_share_cost_and_restore_before_next(self):
        p=self.p
        p._start_auto_tuning()
        self.assertTrue(p.tuning_session_active,p.tuner_status.text())
        self.tick_until(lambda:len(p.tuning_results)>=1)
        self.assertTrue(p.tuning_results[0].safe,p.tuner_status.text())
        self.assertEqual(p.hybrid.records[0]['source'],'Baseline')
        self.assertAlmostEqual(p.tuning_results[0].score,trial_cost(p.tuning_results[0].metrics,p.tuner_profile.currentText()))
        self.assertTrue(p.recovering)
        p.tuning_auto_run=False
        self.tick_until(lambda:p.tuning_candidate is not None)
        self.assertAlmostEqual(p.backend.PendingCommand()[0]['target'],50,places=2)
        self.assertLess(abs(p._feedback_value()-p.reference.beam_nA),.01)
        self.assertTrue((p._session_path/'session.json').exists())
        self.assertEqual(p.backend.PidTrialStatus()['controller_kind'],'nla')

    def test_calibration_change_stops_without_fallback(self):
        p=self.p
        p._start_auto_tuning()
        self.assertTrue(p.tuning_session_active,p.tuner_status.text())
        self.revision=2
        p._tick_feedback()
        self.assertFalse(p.tuning_session_active)
        self.assertFalse(p.backend.PendingCommand()[0]['enabled'])
        self.assertIn('calibration changed',p.tuner_status.text())

    def test_stale_feedback_stops_and_settings_frozen(self):
        p=self.p
        p._start_auto_tuning()
        self.assertFalse(p.hybrid_fields['population'].isEnabled())
        self.assertFalse(p.tuner_profile.isEnabled())
        p.get_beam_state=lambda:dict(current_ua=.001,timestamp=time.time()-5,quality='ok')
        p._tick_feedback()
        self.assertFalse(p.tuning_session_active)
        self.assertFalse(p.backend.PendingCommand()[0]['enabled'])

    def test_standalone_pid_still_works_without_hybrid_reference(self):
        p=self.p
        p.setpoint_input.setValue(1.08)
        p.enable_button.setChecked(True)
        self.assertTrue(p._service_pid_active,p.last_safety_message)
        self.tick_until(lambda:p.backend.PidTrialStatus()['iterations']>0)

    def test_recovery_timeout_never_starts_next_candidate(self):
        p=self.p
        p._start_auto_tuning()
        self.assertTrue(p.recovering)
        p.recovery.start_time-=30
        p._tick_feedback()
        self.assertFalse(p.tuning_session_active)
        self.assertEqual(len(p.tuning_results),0)
        self.assertFalse(p.backend.PendingCommand()[0]['enabled'])

    def test_abort_and_restore_keeps_partial_result_out_of_training(self):
        p=self.p
        p.tuner_duration.setValue(5)
        p._start_auto_tuning()
        self.tick_until(lambda:p.tuning_trial_candidate is not None)
        p._abort_restore()
        self.tick_until(lambda:not p.tuning_session_active)
        self.assertAlmostEqual(p.backend.PendingCommand()[0]['target'],50,places=2)
        self.assertFalse(p.backend.PendingCommand()[0]['enabled'])
        self.assertEqual(len(p.hybrid.safe_results),0)
        self.assertEqual(len(p.hybrid.results),1)
        self.assertFalse(p.hybrid.results[0].safe)

    def test_fifth_page_registration(self):
        from python.app.PageRegistry import DETAIL_BUILDERS
        from python.app.Automation.AutomationPage import AUTOMATION_PAGES
        self.assertEqual(len(AUTOMATION_PAGES),5)
        self.assertIs(DETAIL_BUILDERS['Hybrid GA + BO PID'][1],type(self.p))

    def test_final_validation_requires_full_trial_and_recovery_before_apply(self):
        p=self.p
        p._start_auto_tuning()
        self.tick_until(lambda:len(p.tuning_results)==1)
        p.tuning_auto_run=False
        self.tick_until(lambda:p.tuning_candidate is not None)
        p._stop_tuning_session()
        p._enable_selected_tc()
        self.tick_until(lambda:p.backend.LatestSnapshot()['channels'][0]['enabled'])
        p._validate_best_gains()
        self.assertTrue(p._validating_gains,p.tuner_status.text())
        self.assertFalse(p.apply_tuned_gains_button.isEnabled())
        self.tick_until(lambda:not p._validating_gains,timeout=70)
        self.assertTrue(p.apply_tuned_gains_button.isEnabled(),p.tuner_status.text())
        self.assertGreaterEqual(p.tuning_samples[-1][0],59.5)
        self.assertAlmostEqual(p.backend.PendingCommand()[0]['target'],50,places=2)
        self.assertFalse(p.backend.PendingCommand()[0]['enabled'])
        p._apply_tuned_gains()
        self.assertFalse(p.pid_enabled)
        self.assertFalse(p.backend.PendingCommand()[0]['enabled'])


class CalibrationTest(unittest.TestCase):
    def test_reload_changes_revision_even_when_range_is_unchanged(self):
        from source.Python.Services.BeamCalibrationService import BeamCalibrationService
        service=BeamCalibrationService(Path(__file__).resolve().parents[1]/'config'/'beam_cal.json')
        snapshot=dict(timestamp=time.time(),channels=[dict(raw=0,actual=0)]*14)
        a=service.update(snapshot)
        service.reload()
        b=service.update(snapshot)
        self.assertEqual(a.range_index,b.range_index)
        self.assertGreater(b.calibration_revision,a.calibration_revision)


if __name__ == '__main__':
    unittest.main()
