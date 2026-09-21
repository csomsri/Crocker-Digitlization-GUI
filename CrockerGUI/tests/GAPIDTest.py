"""GA evolution, scoring, recovery and both PID page integration paths."""
import os
import sys
import time
import unittest
import tempfile
from pathlib import Path
from dataclasses import replace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, QEvent
from PySide6.QtWidgets import QAbstractSpinBox, QPushButton
from source.Python.Control.NLAPID import NLAPID, PIDGains
from source.Python.Control.CppPIDAdapter import CppPIDAdapter
from source.Python.Optimization.genetic_optimizer import GAPIDTuner, GainBounds, GATuningConfig
from source.Python.Automation.ga_evaluation import GACandidateEvaluator, GAEvaluationConfig, append_summary_csv, write_evaluation_csv
from source.Python.Automation.ga_backend_adapter import GABackendAdapter
from source.Python.Automation.ga_recovery import GARecoveryManager, GARecoveryConfig
from python.app.Automation.GAPIDPage import GAPIDPage, PythonGAPIDPage


class Backend:
    def __init__(self):
        self.stamp = time.time()
        self.commands = [dict(target=10.,on=True,enabled=True) for _ in range(14)]
        self.writes = 0
        self.accept = True

    def Health(self): return dict(connection='Connected')
    def LatestSnapshot(self):
        return dict(timestamp=self.stamp,channels=[dict(actual=c['target'],on=c['on'],enabled=c['enabled'],status='Ready',interlocked=False) for c in self.commands])
    def PendingCommand(self): return [dict(c) for c in self.commands]
    def SetChannelCommand(self,index,target,on,enabled): self.commands[index] = dict(target=target,on=on,enabled=enabled)
    def ApplyCommand(self):
        self.writes += 1
        return self.accept
    def beam(self): return dict(timestamp=self.stamp,quality='ok',current_ua=.001)


class GATest(unittest.TestCase):
    def test_evolution_is_bounded_and_reproducible(self):
        def run():
            ga=GAPIDTuner(GainBounds((0,1),(0,.1),(0,.01)),GATuningConfig(6,3))
            candidate=ga.initialize(PIDGains(.5,.05,.005))
            while candidate:
                self.assertTrue(0 <= candidate.gains.kp <= 1)
                self.assertTrue(0 <= candidate.gains.ki <= .1)
                self.assertTrue(0 <= candidate.gains.kd <= .01)
                candidate=ga.submit_fitness(candidate.gains.kp)
            self.assertEqual(len(ga.history),18)
            self.assertLessEqual(ga.best_candidate().fitness,.5)
            return ga.history
        self.assertEqual(run(),run())

    def test_evaluation_duplicate_and_safety(self):
        e=GACandidateEvaluator(GAEvaluationConfig(warmup_s=0,evaluation_s=1,minimum_scored_samples=2))
        e.start(candidate_number=1,generation_number=1,gains=PIDGains(),setpoint_nA=1,baseline_target_a=10,baseline_actual_a=10,timestamp_s=0)
        sample=dict(beam_nA=.9,tc_target_a=10,tc_actual_a=10,pid_delta_a=0,saturated=False)
        e.observe(timestamp_s=.5,**sample)
        e.observe(timestamp_s=.5,**sample)
        self.assertEqual(e.scored_samples,1)
        result=e.observe(timestamp_s=1,**sample).result
        self.assertFalse(result.safety_violation)
        self.assertAlmostEqual(result.terms.tracking,.1)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            write_evaluation_csv(result,path/'samples.csv')
            append_summary_csv(result,path/'summary.csv')
            append_summary_csv(result,path/'summary.csv')
            self.assertEqual(len((path/'samples.csv').read_text().splitlines()),3)
            self.assertEqual(len((path/'summary.csv').read_text().splitlines()),3)
        e.start(candidate_number=2,generation_number=1,gains=PIDGains(),setpoint_nA=1,baseline_target_a=10,baseline_actual_a=10,timestamp_s=0)
        result=e.observe(timestamp_s=.5,**dict(sample,beam_nA=0)).result
        self.assertTrue(result.safety_violation)
        self.assertGreaterEqual(result.score,1000000)

    def test_recovery_requires_measured_stability(self):
        r=GARecoveryManager()
        reference=r.capture(targets_a=[10],actual_values_a=[10],beam_nA=1,channel_indices=[0],timestamp_s=0)
        r.start(reference=reference,config=GARecoveryConfig(stable_hold_s=1),timestamp_s=0)
        self.assertAlmostEqual(r.next_command([11]).delta_a,-.02)
        sample=dict(current_targets_a=[10],actual_values_a=[10],beam_nA=1)
        self.assertFalse(r.observe(timestamp_s=1,**sample).complete)
        self.assertFalse(r.observe(timestamp_s=1.5,**dict(sample,beam_nA=float('nan'))).complete)
        self.assertFalse(r.observe(timestamp_s=2,**sample).complete)
        self.assertTrue(r.observe(timestamp_s=3,**sample).complete)


class GAPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def make_page(self,kind=PythonGAPIDPage,backend=None):
        b=backend or Backend()
        p=kind(lambda:None,'simulation',shared_backend=b,get_beam_state=b.beam)
        self.addCleanup(p.deleteLater)
        self.addCleanup(p.stop_backend)
        p.timer.stop()
        p.workspace._display_timer.stop()
        return p,b

    def test_cpp_editors_are_never_shown_as_windows(self):
        class ShowObserver(QObject):
            def __init__(self):
                super().__init__()
                self.unparented = []

            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.Show and isinstance(obj, (QAbstractSpinBox, QPushButton)) and obj.isWindow():
                    self.unparented.append(type(obj).__name__)
                return False

        observer = ShowObserver()
        self.app.installEventFilter(observer)
        try:
            page,_ = self.make_page(GAPIDPage)
            page.show()
            page.workspace.open_tuner_button.click()
            self.app.processEvents()
            self.assertEqual(observer.unparented, [])
            self.assertTrue(page.workspace.ga_target_input.isVisible())
            self.assertTrue(page.workspace.start_ga_button.isVisible())
            page.workspace.ga_settings_button.click()
            self.app.processEvents()
            self.assertTrue(page.workspace.ga_warmup_spin.isVisible())
            self.assertFalse(page.workspace.ga_warmup_spin.isWindow())
            page.close()
        finally:
            self.app.removeEventFilter(observer)

    def test_matching_frontends_and_real_engines(self):
        python,_=self.make_page()
        cpp,_=self.make_page(GAPIDPage)
        self.assertEqual(python.workspace.control_tabs.count(),2)
        self.assertEqual(cpp.workspace.control_tabs.count(),2)
        self.assertFalse(hasattr(python.workspace,'open_tuner_button'))
        self.assertTrue(cpp.workspace.control_tabs.tabBar().isHidden())
        cpp.workspace.open_tuner_button.click()
        self.assertEqual(cpp.workspace.control_tabs.currentIndex(),1)
        cpp.workspace.ga_target_input.setValue(1.25)
        self.assertEqual(cpp.workspace.setpoint_spin.value(),1.25)
        cpp.workspace.back_to_pid_button.click()
        self.assertEqual(cpp.workspace.control_tabs.currentIndex(),0)
        self.assertIsInstance(python.workspace.pid,NLAPID)
        if cpp.engine_error:
            self.skipTest(cpp.engine_error)
        self.assertIsInstance(cpp.workspace.pid,CppPIDAdapter)
        gains=PIDGains(.1,.001,.002)
        for engine in (python.workspace.pid,cpp.workspace.pid):
            engine.set_gains(gains)
            engine.reset(setpoint=2,measurement=1)
        for n in range(20):
            a=python.workspace.pid.update(2,1+n*.01,.1)
            b=cpp.workspace.pid.update(2,1+n*.01,.1)
            self.assertAlmostEqual(a.output,b.output,places=10)

    def test_preview_rejection_and_owner(self):
        p,b=self.make_page()
        w=p.workspace
        w.setpoint_spin.setValue(1.2)
        w.start_pid()
        self.assertTrue(w._pid_running)
        b.stamp=time.time()
        w._pid_step()
        self.assertEqual(b.writes,0)
        other,_=self.make_page(backend=b)
        other.workspace.start_pid()
        self.assertFalse(other.workspace._pid_running)
        w.arm_output_check.setChecked(True)
        b.accept=False
        before=b.PendingCommand()[9]['target']
        self.assertFalse(p.apply_delta(9,.01,None))
        self.assertEqual(b.PendingCommand()[9]['target'],before)
        p.stop_backend()
        self.assertFalse(w._pid_timer.isActive())

    def test_command_stale_duplicate_and_disarmed(self):
        b=Backend()
        adapter=GABackendAdapter(b)
        args=dict(authorized=True,max_age_s=2)
        self.assertTrue(adapter.apply_delta(9,.01,(0,100),**args))
        self.assertTrue(adapter.apply_delta(9,.01,(0,100),**args))
        self.assertEqual(b.writes,1)

        b.stamp -= 10
        self.assertFalse(adapter.apply_delta(9,.01,(0,100),**args))
        b.stamp=time.time()
        self.assertFalse(adapter.apply_delta(9,.01,(0,100),authorized=False,max_age_s=2))
        self.assertFalse(adapter.apply_delta(9,100,(0,100),**args))
        self.assertEqual(b.writes,1)

    def test_enable_selected_coil_preserves_targets_and_other_channels(self):
        b=Backend()
        b.commands[9].update(on=False,enabled=False)
        before=b.PendingCommand()
        p,_=self.make_page(GAPIDPage,backend=b)
        self.assertTrue(p.workspace.enable_channel_button.isEnabled())
        p.workspace.enable_channel_button.click()
        self.assertEqual(b.commands[9],dict(target=before[9]['target'],on=True,enabled=True))
        self.assertEqual(b.commands[:9]+b.commands[10:],before[:9]+before[10:])
        self.assertEqual(b.writes,1)
        self.assertIn('on / enabled',p.workspace.channel_state_label.text())
        self.assertFalse(p.pid_enabled)
        self.assertFalse(p.tuning_session_active)

    def test_enable_rejection_and_stale_readback(self):
        b=Backend()
        b.commands[9].update(on=False,enabled=False)
        adapter=GABackendAdapter(b)
        b.accept=False
        with self.assertRaisesRegex(ValueError,'rejected'):
            adapter.enable_channel(9,(0,100),authorized=True,max_age_s=2)
        self.assertFalse(b.commands[9]['on'])
        self.assertFalse(b.commands[9]['enabled'])
        b.stamp-=10
        with self.assertRaisesRegex(ValueError,'Fresh'):
            adapter.enable_channel(9,(0,100),authorized=True,max_age_s=2)
        self.assertEqual(b.writes,1)

    def test_ga_page_resizing(self):
        p,_=self.make_page()
        p.show()
        for width,height in ((1280,820),(1440,900),(1920,1080)):
            p.resize(width,height)
            for index in (0,1):
                p.workspace.control_tabs.setCurrentIndex(index)
                self.app.processEvents()
                self.assertEqual((p.width(),p.height()),(width,height))
                self.assertEqual(p.scroll_area.horizontalScrollBar().maximum(),0)
        p.close()

    def test_complete_automatic_generation_both_engines(self):
        for kind in (PythonGAPIDPage,GAPIDPage):
            p,b=self.make_page(kind)
            if p.engine_error:
                continue
            w=p.workspace
            w._create_ga_run_directory=lambda *args:None
            w.setpoint_spin.setValue(1.2)
            w.tc_min_spin.setValue(0)
            w.tc_max_spin.setValue(100)
            for name,high in [('kp',.05),('ki',.001),('kd',.001)]:
                getattr(w,name+'_min_spin').setValue(0)
                getattr(w,name+'_max_spin').setValue(high)
                getattr(w,name+'_spin').setValue(high/2)
            w.ga_warmup_spin.setValue(0)
            w.ga_evaluation_spin.setValue(.1)
            w.ga_restore_hold_spin.setValue(0)
            w.generations_spin.setValue(1)
            w.arm_output_check.setChecked(True)
            w.auto_ga_arm_check.setChecked(True)
            w.start_ga()
            self.assertTrue(w._ga_auto_active,w.ga_status_label.text())
            w.ga_evaluator.config=replace(w.ga_evaluator.config,minimum_scored_samples=1)
            for n in range(160):
                # Advance the simulated telemetry clock with a matching wall clock.
                b.stamp=time.time()
                if w._ga_sequence_state=='EVALUATING':
                    w.ga_evaluator.start_time -= .2
                    w.ga_evaluator.last_time -= .2
                    w._last_processed_beam_timestamp=0
                    w._last_pid_time=time.monotonic()-.02
                    w._pid_step()
                elif w._ga_sequence_state=='RESTORING':
                    w._ga_restore_tick(time.monotonic())
                if not w._ga_auto_active: break
            self.assertEqual(w._ga_sequence_state,'COMPLETE',w.ga_status_label.text())
            self.assertEqual(len(w.ga_tuner.history),4)
            self.assertGreater(b.writes,0)
            self.assertAlmostEqual(b.commands[9]['target'],10,delta=.005)
            p.stop_backend()


if __name__=='__main__': unittest.main()
