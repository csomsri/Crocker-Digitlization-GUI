"""Profile editor persistence, review, and running-session regression tests."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import time
import threading
from unittest.mock import patch
from PySide6.QtCore import QTimer

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtWidgets import QApplication, QSizeGrip
from python.app.Automation.HardwareProfileDialog import HardwareProfileDialog, PROFILE_PATH
from python.app.widgets.MagneticFieldWidgets import CHANNEL_NAMES
from source.Python.Automation.hardware_profile import HardwareProfile


class EditorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'profile.json'
        # Independent fixture: operator edits to the real JSON must not affect tests.
        profile = dict(profile_name='Test draft', approval_status='draft', setup_notes={},
                       provenance={key: 'pending' for key in ('measurement_date', 'machine_configuration',
                                   'units', 'operator', 'reviewer', 'source_dataset', 'uncertainty', 'valid_until')},
                       measurement_channels={'TC10': dict(
                           allocation={'TC10': 1.0}, ramp_control='labview',
                           minimum_command={c: 0.0 for c in CHANNEL_NAMES},
                           maximum_command={c: float(c == 'TC10') for c in CHANNEL_NAMES},
                           abort_limits=dict(max_absolute_error=1, max_overshoot=.5,
                                             max_control_output=.05, max_saturation_seconds=2))})
        profile['provenance'].update(machine_configuration='Test fixture', units='A; nA; s')
        self.path.write_text(json.dumps(profile), encoding='utf-8')
        self.dialog = HardwareProfileDialog(None, CHANNEL_NAMES, path=self.path)

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.directory.cleanup()

    def save(self):
        self.dialog.save_profile()
        deadline = time.monotonic() + 5
        while self.dialog._save_future is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertIsNone(self.dialog._save_future)

    def read(self):
        return json.loads(self.path.read_text())

    def test_draft_edits_persist_without_approving(self):
        self.dialog.inputs['maximum_command'].setValue(0.8)
        self.save()
        saved = self.read()
        self.assertEqual(saved['approval_status'], 'draft')
        self.assertEqual(saved['measurement_channels']['TC10']['maximum_command']['TC10'], .8)
        self.assertIn('setup_notes', saved)
        with self.assertRaisesRegex(ValueError, 'reviewer approval'):
            HardwareProfile(self.path, CHANNEL_NAMES)

    def test_invalid_bounds_leave_file_unchanged(self):
        original = self.path.read_bytes()
        self.dialog.inputs['minimum_command'].setValue(2)
        self.save()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertIn('unordered', self.dialog.status.text())

    def test_review_requires_completed_provenance_and_clears_on_edit(self):
        self.dialog.reviewed.setChecked(True)
        self.save()
        self.assertIn('Not saved', self.dialog.status.text())
        values = dict(measurement_date='2026-01-01', valid_until='2099-01-01',
                      operator='Test operator', reviewer='Test reviewer',
                      source_dataset='Test fixture only', uncertainty='Test fixture only')
        for key, value in values.items():
            self.dialog.provenance[key].setText(value)
        self.dialog.reviewed.setChecked(True)
        self.save()
        HardwareProfile(self.path, CHANNEL_NAMES)
        self.assertEqual(self.read()['approval_status'], 'approved')
        self.dialog.inputs['maximum_command'].setValue(.9)
        self.assertFalse(self.dialog.reviewed.isChecked())
        self.save()
        self.assertEqual(self.read()['approval_status'], 'draft')

    def test_running_session_and_external_edits_block_save(self):
        original = self.path.read_bytes()
        self.dialog.can_save = lambda: False
        self.save()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertIn('Stop PID', self.dialog.status.text())
        self.dialog.can_save = lambda: True
        self.path.write_bytes(original + b'\n')
        self.save()
        self.assertEqual(self.path.read_bytes(), original + b'\n')
        self.assertIn('changed elsewhere', self.dialog.status.text())

    def test_channel_switch_preserves_edits_and_sets_identity_allocation(self):
        self.dialog.inputs['maximum_command'].setValue(.7)
        self.dialog.channel.setCurrentText('TC1')
        self.dialog.inputs['maximum_command'].setValue(.6)
        self.dialog.channel.setCurrentText('TC10')
        self.assertEqual(self.dialog.inputs['maximum_command'].value(), .7)
        self.save()
        entries = self.read()['measurement_channels']
        self.assertEqual(entries['TC1']['allocation'], {'TC1': 1.0})
        self.assertEqual(entries['TC1']['maximum_command']['TC1'], .6)

    def test_selected_coil_opens_without_changing_file_and_no_resize_grip(self):
        original = self.path.read_bytes()
        dialog = HardwareProfileDialog(None, CHANNEL_NAMES, path=self.path, initial_channel='TC1')
        try:
            self.assertEqual(dialog.channel.currentText(), 'TC1')
            self.assertIn('no saved profile', dialog.status.text())
            self.assertFalse(dialog.findChildren(QSizeGrip))
            self.assertEqual(self.path.read_bytes(), original)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_slow_save_does_not_block_event_loop_and_survives_close(self):
        from python.app.Automation.HardwareProfileDialog import _write_profile
        started, release = threading.Event(), threading.Event()
        def slow_write(*args):
            started.set()
            if not release.wait(5):
                raise TimeoutError('Test worker not released')
            return _write_profile(*args)
        ticks = []
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        try:
            with patch('python.app.Automation.HardwareProfileDialog._write_profile', side_effect=slow_write):
                before = time.monotonic()
                self.dialog.save_profile()
                self.assertLess(time.monotonic()-before, .2)
                self.assertTrue(started.wait(1))
                self.dialog.close()
                for _ in range(10):
                    self.app.processEvents()
                    time.sleep(.01)
                self.assertGreater(len(ticks), 2)
                release.set()
                self.save()
                self.assertIn('Saved draft', self.dialog.status.text())
        finally:
            release.set()
            timer.stop()

    def test_write_failure_preserves_file_and_allows_retry(self):
        original = self.path.read_bytes()
        with patch('python.app.Automation.HardwareProfileDialog._write_profile', side_effect=OSError('disk full')):
            self.save()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertIn('disk full', self.dialog.status.text())
        self.assertTrue(self.dialog.save_button.isEnabled())
        self.save()
        self.assertIn('Saved draft', self.dialog.status.text())


if __name__ == '__main__':
    unittest.main()
