"""Recovery policy tests use a fake backend; no hardware commands."""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source.Python.Automation.failure_recovery import FailureRecovery
from source.Python.Automation.reference_recovery import RecoveryConfig, RecoveryManager
from source.Python.Automation.ga_recovery import GARecoveryManager


class Backend:
    def __init__(self):
        self.target = self.actual = 200.
        self.on = self.enabled = True
        self.interlocked = False
        self.connection = 'Connected'
        self.stamp = time.time()
        self.writes = []
        self.reject = False

    def LatestSnapshot(self):
        return dict(timestamp=self.stamp, channels=[dict(actual=self.actual, on=self.on,
                    enabled=self.enabled, interlocked=self.interlocked, status='Idle')])

    def PendingCommand(self):
        return [dict(target=self.target, on=self.on, enabled=self.enabled)]

    def Health(self):
        return dict(connection=self.connection)

    def SetChannelCommand(self, index, target, on, enabled):
        self.target = target
        self.writes.append((target, on, enabled))

    def ApplyCommand(self):
        return not self.reject


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.recovery = FailureRecovery(self.backend)
        self.recovery.capture(0, 1., beam_required=True, limits=(0., 800.))

    def start(self):
        return self.recovery.start(authorized=True, dry_run=False, reason='Trial failed',
            config=RecoveryConfig(command_step_a=1, stable_hold_s=0))

    def poll(self, **kwargs):
        self.recovery.poll(authorized=True, beam=1., beam_valid=True,
                           beam_timestamp=self.backend.stamp, **kwargs)

    def test_ga_uses_shared_planner(self):
        self.assertIsInstance(self.recovery.planner, GARecoveryManager)

    def test_bounded_restore_and_verified_completion(self):
        self.backend.target = self.backend.actual = 201.
        self.assertTrue(self.start())
        self.poll()
        self.assertEqual(self.backend.target, 200.)
        self.assertTrue(self.recovery.active)  # Actual is still displaced.
        # Physical readback can remain displaced after the software target reset.
        self.backend.stamp = time.time()
        self.poll()
        self.assertFalse(self.recovery.active)
        self.assertIn('captured target restored', self.recovery.status)
        self.assertEqual(self.backend.writes, [(200., True, True)])

    def test_hardware_protection_blocks_without_writes(self):
        for attribute, value in [('enabled', False), ('interlocked', True),
                                 ('connection', 'Disconnected'), ('stamp', time.time()-10)]:
            with self.subTest(attribute=attribute):
                previous = getattr(self.backend, attribute)
                setattr(self.backend, attribute, value)
                self.assertFalse(self.start())
                self.assertEqual(self.backend.writes, [])
                setattr(self.backend, attribute, previous)

    def test_reset_does_not_require_beam_stability(self):
        self.backend.target = 500.
        self.assertTrue(self.start())
        self.recovery.poll(authorized=True, beam=float('nan'), beam_valid=False)
        self.assertEqual(self.backend.target, 200.)
        self.recovery.poll(authorized=True, beam=float('nan'), beam_valid=False)
        self.assertFalse(self.recovery.active)

    def test_authorization_stops_reset(self):
        self.backend.target = 500.
        self.assertTrue(self.start())
        self.recovery.poll(authorized=False, beam=1., beam_valid=True)
        self.assertFalse(self.recovery.active)
        self.assertEqual(self.backend.writes, [])

    def test_held_packet_does_not_repeat_step(self):
        self.backend.target = 500.
        self.assertTrue(self.start())
        self.poll()
        self.poll()
        self.assertEqual(len(self.backend.writes), 1)

    def test_rejected_command_stops_and_restores_pending_value(self):
        self.backend.target = 201.
        self.backend.reject = True
        self.assertTrue(self.start())
        self.poll()
        self.assertFalse(self.recovery.active)
        self.assertEqual(self.backend.target, 201.)

    def test_no_reference_dry_run_and_unarmed_never_write(self):
        for kwargs in [dict(authorized=False, dry_run=False), dict(authorized=True, dry_run=True)]:
            self.assertFalse(self.recovery.start(reason='Failure', **kwargs))
        self.recovery.reference = None
        self.assertFalse(self.start())
        self.assertEqual(self.backend.writes, [])


if __name__ == '__main__':
    unittest.main()
