"""Dedicated LabVIEW beam field regression tests; no hardware connection."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from source.Python.Services.BeamCalibrationService import BeamCalibrationService


class BeamFeedbackMappingTest(unittest.TestCase):
    def setUp(self):
        self.service = BeamCalibrationService(ROOT / 'config/beam_cal.json')
        self.packet = dict(timestamp=100., beam_current=.06, beam_range_idx=0,
                           channels=[dict(raw=500., actual=500.) for _ in range(14)])

    def test_detector_is_independent_of_centering(self):
        state = self.service.update(self.packet)
        self.assertEqual(state.quality, 'ok')
        self.assertAlmostEqual(state.current_ua * 1000, .2)
        self.packet['channels'][13]['raw'] = 0.
        self.assertEqual(self.service.update(self.packet).current_ua, state.current_ua)

    def test_missing_field_does_not_reuse_measurement(self):
        self.service.update(self.packet)
        del self.packet['beam_current']
        self.packet['timestamp'] = 101.
        state = self.service.update(self.packet)
        self.assertEqual(state.quality, 'degraded')
        self.assertEqual(state.timestamp, 100.)

    def test_explicit_range_overrides_manual_like_experiment(self):
        self.packet.update(beam_current=.036, beam_range_idx=1)
        state = self.service.update(self.packet)
        self.assertEqual(state.range_index, 1)
        self.assertAlmostEqual(state.current_ua * 1000, .3)

    def test_invalid_values_are_not_live(self):
        for fields in (dict(beam_current=float('nan')), dict(beam_current='bad'),
                       dict(timestamp=0), dict(beam_range_idx=-1), dict(beam_range_idx=100)):
            with self.subTest(fields=fields):
                self.assertEqual(self.service.update(dict(self.packet, **fields)).quality, 'degraded')

    def test_legacy_alias_and_array(self):
        self.packet['beam_current'] = [.06]
        self.assertAlmostEqual(self.service.update(self.packet).current_ua * 1000, .2)
        del self.packet['beam_current']
        self.packet['beam_v_raw'] = .0879
        self.assertAlmostEqual(self.service.update(self.packet).current_ua * 1000, .3)


if __name__ == '__main__':
    unittest.main()
