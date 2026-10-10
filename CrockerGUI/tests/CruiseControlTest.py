"""Cruise scheduling and C++ simulator handoff; never connects to real hardware."""
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT/'Debug', ROOT/'Release', ROOT/'build'/'Debug', ROOT/'build'/'Release'):
    sys.path.insert(0, str(folder))
from PySide6.QtWidgets import QApplication
from python.app.Automation.PidControlPage import PidControlPage
from source.Python.Automation.cruise_supervisor import CruiseSupervisor
from source.Python.Optimization.pid_gain_adapter import PidGainCandidate


class SchedulingTest(unittest.TestCase):
    def test_unlimited_session_cap_still_requires_persistent_error(self):
        s = CruiseSupervisor()
        s.start(0, 0)
        s.sessions = 99
        args = dict(error=1, ready=True, pending=False, automatic=True,
                    band=.3, persistence=3, maximum_sessions=0)
        self.assertFalse(s.should_tune(now=1, stamp=1, **args))
        self.assertTrue(s.should_tune(now=4, stamp=4, **args))

    def test_persistence_cooldown_repeated_samples_and_budget(self):
        s = CruiseSupervisor()
        s.start(0, 5)
        def poll(now, **kw):
            return s.should_tune(now=now, stamp=kw.pop('stamp', now), error=kw.pop('error', 1),
                                 ready=True, pending=kw.pop('pending', False), automatic=True,
                                 band=.3, persistence=3, maximum_sessions=1)
        self.assertFalse(poll(4))
        self.assertFalse(poll(5))
        self.assertFalse(poll(8, stamp=5))
        self.assertTrue(poll(8))
        self.assertFalse(poll(9, pending=True))
        self.assertFalse(poll(10))
        self.assertFalse(poll(11, error=0))
        self.assertFalse(poll(12))
        self.assertTrue(poll(15))
        s.sessions = 1
        self.assertFalse(poll(16))
        s.stop()
        self.assertFalse(poll(20))


class CruiseIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.page = PidControlPage(lambda: None, 'simulation',
            get_beam_state=lambda: dict(current_ua=.001, timestamp=time.time(), quality='ok'))
        self.page.setpoint_input.setValue(1)
        self.page.timer.stop()

    def tearDown(self):
        self.page.stop_backend()
        self.page.deleteLater()
        self.app.processEvents()

    def wait_until(self, predicate, seconds=60):
        deadline = time.monotonic()+seconds
        while not predicate() and time.monotonic() < deadline:
            self.page._tick_feedback()
            self.app.processEvents()
            time.sleep(.04)
        self.assertTrue(predicate(), self.page.cruise_workspace.status.text())

    def test_start_stop_and_watchdog_never_recover_fault(self):
        p = self.page
        p._start_cruise()
        self.assertTrue(p.pid_enabled)
        self.assertTrue(p.cruise.active)
        self.assertFalse(p.dry_run_check.isChecked())
        p.get_beam_state = lambda: dict(current_ua=.001, timestamp=time.time()-10, quality='ok')
        p._tick_feedback()
        self.assertFalse(p.cruise.active)
        self.assertFalse(p.pid_enabled)
        self.assertFalse(p.apply_tuned_gains_button.isEnabled())

    def test_automatic_budget_validation_apply_and_restore(self):
        p = self.page
        p.tuner_trials.setValue(3)
        p.tuner_duration.setValue(.6)
        p.validation_duration.setValue(1)
        p._start_cruise()
        previous = p._cruise_snapshot()
        p._begin_cruise_tuning()
        self.assertTrue(p.tuning_session_active)
        self.assertTrue(p.cruise_workspace.stop.isEnabled())
        self.wait_until(lambda: p._cruise_pending or not p.cruise.active)
        self.assertTrue(p._cruise_pending)
        self.assertEqual(len(p.tuning_results), 3)
        self.assertEqual(p.tuning_results[0].candidate.kp, previous.gains.kp)
        self.assertTrue(p.pid_enabled)  # Incumbent resumes while Apply waits.
        p._apply_cruise_gains()
        self.assertTrue(p.pid_enabled)
        self.assertFalse(p._cruise_pending)
        p._rollback_cruise()
        self.assertTrue(p.pid_enabled)
        self.assertEqual(p.kp_input.value(), previous.gains.kp)
        p._stop_cruise()
        self.assertFalse(p.pid_enabled)
        self.assertFalse(p.cruise.active)
        self.assertFalse(p.backend.PendingCommand()[p.selected_index]['on'])

    def test_stop_during_proposal_and_failed_stop_can_retry(self):
        p = self.page
        p._start_cruise()
        p._begin_cruise_tuning()
        p._stop_cruise()
        self.assertFalse(p._cruise_auto_validate)
        self.assertFalse(p.tuning_session_active)
        p._poll_tuning_workflow()
        self.assertFalse(p.pid_enabled)
        with patch.object(p, '_stop_tuning_session', side_effect=RuntimeError('transport down')):
            p._stop_cruise()
        self.assertTrue(p._cruise_stop_failed)
        self.assertTrue(p.cruise_workspace.stop.isEnabled())
        self.assertFalse(p.cruise_workspace.start.isEnabled())
        p._stop_cruise()
        self.assertFalse(p._cruise_stop_failed)

    def test_dialog_stop_and_responsive_layout(self):
        p = self.page
        self.assertEqual(p.cruise_workspace.max_sessions.value(), 0)
        self.assertEqual(p.cruise_workspace.cooldown.value(), 15)
        self.assertEqual(p.validation_duration.value(), 20)
        self.assertFalse(p.cruise_workspace.wait_for_ramp.isChecked())
        p.resize(1200, 1000)
        p.show()
        self.app.processEvents()
        p._start_cruise()
        p.cruise_workspace.show_settings()
        self.app.processEvents()
        from PySide6.QtWidgets import QPushButton
        button = p.cruise_workspace.settings.findChild(QPushButton, 'pidCruiseDialogStop')
        self.assertIsNotNone(button)
        self.assertTrue(button.isVisible())
        button.click()
        self.assertFalse(p.cruise.active)
        self.assertFalse(p.pid_enabled)
        p.resize(620, 900)
        self.app.processEvents()
        self.assertEqual(p.cruise_workspace.bottom.getItemPosition(1)[0], 1)
        p.hide()

    def test_navigation_keeps_live_control_reachable_without_starting_hardware(self):
        p = self.page
        nav = p.cruise_navigation
        for target in (p._advanced_control_page, p.tuner_page, p.results_page, p.cruise_workspace):
            nav.tabs.setCurrentIndex(nav.targets.index(target))
            self.assertIs(p.page_stack.currentWidget(), target)
            self.assertEqual(nav.tabs.currentIndex(), nav.targets.index(target))
            self.assertFalse(p.pid_enabled)
            self.assertFalse(p.tuning_session_active)
        p._start_cruise()
        nav.tabs.setCurrentIndex(nav.targets.index(p._advanced_control_page))
        self.assertTrue(p.pid_enabled)
        from PySide6.QtWidgets import QPushButton
        stop = next(b for b in nav.findChildren(QPushButton) if b.text() == 'Stop control')
        stop.click()
        self.assertFalse(p.pid_enabled)
        self.assertFalse(p.cruise.active)

    def test_validation_fault_does_not_resume_and_changed_context_blocks_apply(self):
        p = self.page
        p._start_cruise()
        with patch.object(p, '_resume_cruise') as resume:
            p._finish_cruise_validation(valid=False, safe=False)
            resume.assert_not_called()
        self.assertFalse(p.cruise.active)
        p._start_cruise()
        self.assertTrue(p.cruise.active, p.last_safety_message)
        p._cruise_context = p._cruise_fingerprint()
        p._cruise_pending = True
        p.apply_tuned_gains_button.setProperty('approvedCandidate', PidGainCandidate(1, 0, 0))
        p.apply_tuned_gains_button.setEnabled(True)
        p.setpoint_input.setValue(2)
        p._apply_cruise_gains()
        self.assertFalse(p._cruise_pending)
        self.assertIn('changed', p._cruise_message)
        self.assertTrue(p.pid_enabled)

    def test_search_time_plateau_and_ramp_gate(self):
        p = self.page
        p._start_cruise()
        self.assertTrue(p._cruise_ramp_settled())
        p.actual_values[p.selected_index] = 100
        self.assertFalse(p._cruise_ramp_settled())
        p.coil_session_started = time.perf_counter()-2000
        self.assertTrue(p._cruise_search_complete())
        p.coil_session_started = time.perf_counter()
        p.tuning_optimizer = SimpleNamespace(optimizer=SimpleNamespace(initial_safe_trials=6))
        p.tuning_results = [SimpleNamespace(score=1, safe=True, metrics=None)]*11
        self.assertTrue(p._cruise_search_complete())
        p.tuning_results = p.tuning_results[:6]
        self.assertFalse(p._cruise_search_complete())
        p.tuning_optimizer = None


if __name__ == '__main__':
    unittest.main()
