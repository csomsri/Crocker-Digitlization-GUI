"""Beam feedback regression tests using the real C++ worker and simulated transport."""
import time
import unittest
from unittest.mock import Mock, patch
from CppNLAPIDIntegrationTest import CycloViz, config, wait_for, QApplication, PidControlPage
from python.app.Automation.PythonPIDPage import PythonPIDPage


class BeamServiceTest(unittest.TestCase):
    def setUp(self):
        self.service = CycloViz.ControlService()
        self.service.StartSimulator(100)
        self.service.SetChannelCommand(9, 50, True, True)
        self.service.ApplyCommand()
        self.settings = config(measurement_channel=9, setpoint=1.0, kp=1, ki=0,
                               allocation=[0.0]*9+[1.0]+[0.0]*4,
                               external_beam_measurement=True, continuous=True)

    def tearDown(self):
        self.service.Stop()

    def start(self, beam):
        self.service.SetPidBeamMeasurement(beam, time.time(), True)
        self.service.StartPidTrial(self.settings)
        time.sleep(.04)

    def sample(self, value):
        self.service.SetPidBeamMeasurement(value, time.time(), True)
        time.sleep(.04)

    def test_matching_beam_holds_tc_despite_different_coil_current(self):
        self.start(1.0)
        self.sample(1.0)
        status = self.service.PidTrialStatus()
        self.assertGreater(status['iterations'], 0)
        self.assertEqual(status['error'], 0)
        self.assertEqual(status['measured_field'], 1)
        self.assertEqual(self.service.PendingCommand()[9]['target'], 50)

    def test_beam_error_moves_only_selected_tc_and_held_sample_is_not_reused(self):
        self.start(.5)
        self.sample(.5)
        before = self.service.PidTrialStatus()
        self.assertAlmostEqual(before['error'], .5)
        self.assertGreater(before['command_target'], 50)
        time.sleep(.07)
        self.assertEqual(self.service.PidTrialStatus()['iterations'], before['iterations'])
        commands = self.service.PendingCommand()
        self.assertTrue(all(c['target'] == 0 for i,c in enumerate(commands) if i != 9))

    def test_stale_and_invalid_beam_fault_without_coil_feedback_fallback(self):
        for value, stamp, valid in ((1, time.time()-5, True), (float('nan'),time.time(),True),
                                    (1,time.time(),False), (1,time.time()+5,True)):
            with self.subTest(value=value, valid=valid):
                self.service.SetPidBeamMeasurement(value, stamp, valid)
                self.service.StartPidTrial(self.settings)
                wait_for(lambda: self.service.PidTrialStatus()['state'] == 'Faulted')
                self.assertEqual(self.service.PidTrialStatus()['iterations'], 0)

    def test_backward_sample_faults(self):
        self.start(.5)
        self.sample(.5)
        self.service.SetPidBeamMeasurement(.5, time.time()-.2, True)
        wait_for(lambda: self.service.PidTrialStatus()['state'] == 'Faulted')
        self.assertIn('out-of-order', self.service.PidTrialStatus()['message'])

    def test_external_ramping_retains_absolute_current_bounds(self):
        self.settings['maximum_slew_per_second'] = [0.0]*14
        self.settings['minimum_command'] = [0.0]*9+[50.0]+[0.0]*4
        self.settings['maximum_command'] = [100.0]*9+[50.05]+[100.0]*4
        self.start(.5)
        self.sample(.5)
        target = self.service.PendingCommand()[9]['target']
        self.assertGreater(target, 50.0)
        self.assertLessEqual(target, 50.05)
        self.service.StopPidTrial(False)
        self.settings['maximum_slew_per_second'][9] = -1
        with self.assertRaises(ValueError):
            self.service.StartPidTrial(self.settings)


class BeamPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_active_feedback_rejects_calibration_change_and_malformed_provider(self):
        state = dict(current_ua=.0003, timestamp=time.time(), quality='ok', calibration_revision=1)
        p = PidControlPage(lambda: None, 'simulation', get_beam_state=lambda: state)
        try:
            p._refresh_beam()
            self.assertTrue(p.beam_valid)
            p.pid_enabled = True
            state['calibration_revision'] = 2
            p._refresh_beam()
            self.assertFalse(p.beam_valid)
            p.pid_enabled = False
            p._refresh_beam()
            self.assertTrue(p.beam_valid)
            p.get_beam_state = lambda: None
            p._refresh_beam()
            self.assertFalse(p.beam_valid)
        finally:
            p.pid_enabled = False
            p.stop_backend()
            p.deleteLater()

    def test_units_conversion_missing_feedback_and_python_unchanged(self):
        p = PidControlPage(lambda: None, 'simulation',
                           get_beam_state=lambda: dict(current_ua=.002, timestamp=time.time(), quality='ok'))
        py = PythonPIDPage(lambda: None, 'simulation')
        try:
            p._tick_feedback()
            self.assertEqual(p._feedback_value(), 2)
            self.assertEqual(p.setpoint_input.suffix(), ' nA')
            self.assertEqual(p.tuner_target.suffix(), ' nA')
            self.assertEqual(p.max_output_input.suffix(), ' A')
            self.assertEqual(p.channel_select.count(), 12)
            self.assertEqual(py.setpoint_input.suffix(), ' A')
            p.setpoint_input.setValue(2)
            p._refresh_status()
            self.assertIn('+0.00 nA', p.pid_status_values['Error'].text())
            self.assertEqual(p.time_plot.beam.data[2][-1], 2)
            p.get_beam_state = None
            p._refresh_beam()
            with self.assertRaisesRegex(RuntimeError, 'fresh calibrated beam'):
                p._start_trial(config())
        finally:
            p.stop_backend()
            py.stop_backend()
            p.deleteLater()
            py.deleteLater()

    def test_long_status_is_not_clipped_at_desktop_and_compact_widths(self):
        p = PidControlPage(lambda: None, 'simulation')
        try:
            p.timer.stop()
            p.last_safety_message = ('No hardware profile for TC1. Open Edit Hardware Profile and '
                                     'configure/review this coil\'s limits. Existing profiles: TC10.')
            p._refresh_status()
            p.show()
            for width, height in ((1366, 768), (800, 600)):
                p.resize(width, height)
                for _ in range(12): self.app.processEvents()
                label = p.safety_label
                self.assertTrue(label.wordWrap())
                self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
                self.assertTrue(label.parentWidget().rect().contains(label.geometry()))
        finally:
            p.stop_backend()
            p.close()
            p.deleteLater()

    def test_hardware_profile_is_applied_before_backend_start(self):
        p = PidControlPage(lambda: None, 'simulation',
                           get_beam_state=lambda: dict(current_ua=.002, timestamp=time.time(), quality='ok'))
        original_backend = p.backend
        try:
            p.backend = Mock()
            p.backend_mode = 'hardware'
            settings = config(continuous=True)
            reviewed = dict(settings, allocation_calibrated=True, max_absolute_error=3)
            with patch('python.app.Automation.PidControlPage.apply_hardware_profile', return_value=reviewed) as loader:
                p._start_trial(settings)
                self.assertEqual(loader.call_args.args[1].name, 'pid_hardware_profile.json')
                sent = p.backend.StartPidTrial.call_args.args[0]
                self.assertTrue(sent['allocation_calibrated'])
                self.assertTrue(sent['external_beam_measurement'])
                self.assertEqual(sent['max_absolute_error'], 3)
            p.backend.reset_mock()
            with patch('python.app.Automation.PidControlPage.apply_hardware_profile', side_effect=ValueError('draft profile')):
                with self.assertRaisesRegex(ValueError, 'draft profile'):
                    p._start_trial(settings)
                p.backend.StartPidTrial.assert_not_called()
            p.backend_mode = 'simulation'
            with patch('python.app.Automation.PidControlPage.apply_hardware_profile') as loader:
                p._start_trial(settings)
                loader.assert_not_called()
        finally:
            p.backend = original_backend
            p.stop_backend()
            p.deleteLater()


if __name__ == '__main__':
    unittest.main()
