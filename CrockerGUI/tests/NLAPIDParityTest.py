"""Compare the actual bound C++ engine to the standalone Python reference."""
import math
import sys
import unittest
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import CycloViz
from source.Python.Control.NLAPID import NLAPID, PIDGains, PIDLimits, AdaptiveDirectionSettings


def cpp_struct(name, values):
    obj = getattr(CycloViz, name)()
    for key, value in values.items():
        if hasattr(obj, key):
            setattr(obj, key, value)
    return obj


class ParityTest(unittest.TestCase):
    def test_replay_all_result_fields(self):
        reversals = deadbands = saturations = 0
        for scenario in range(4):
            gains = PIDGains(0.2, 0.1, 0.03)
            limits = PIDLimits(output_min=0, output_max=0.05 if scenario == 1 else 100,
                               integral_max=0.01 if scenario == 2 else 100,
                               derivative_filter_tau=0 if scenario == 3 else 0.05)
            settings = AdaptiveDirectionSettings(
                deadband=0.05, direction_check_interval=0.3,
                integral_memory_s=0 if scenario == 3 else 2.15,
                initial_direction=-1 if scenario == 2 else 1,
                reset_integral_in_deadband=scenario == 2,
            )
            py = NLAPID(gains, limits, settings)
            cpp = CycloViz.NLAPID(cpp_struct('NLAPIDGains', asdict(gains)),
                                 cpp_struct('NLAPIDLimits', asdict(limits)),
                                 cpp_struct('NLAPIDSettings', asdict(settings)))
            for i in range(2500):
                if i == 1200:
                    py.reset(setpoint=11, measurement=8, direction=-1)
                    cpp.reset(setpoint=11, measurement=8, direction=-1)
                if i == 1800:
                    py.set_gains(PIDGains(0.3, 0.05, 0.02))
                    cpp.set_gains(cpp_struct('NLAPIDGains', dict(kp=0.3, ki=0.05, kd=0.02)))
                target = 10.0 if i < 1500 else 12.0
                measurement = target if i % 100 < 5 else 8 + 3 * math.sin(i / 40)
                dt = 0.8 if i % 79 == 0 else (0.09 if i % 2 else 0.11)
                hold = i % 23 == 0
                expected = asdict(py.update(target, measurement, dt, hold_integrator=hold))
                actual = cpp.update(target, measurement, dt, hold)
                for key, value in expected.items():
                    if isinstance(value, float):
                        self.assertTrue(math.isclose(value, actual[key], rel_tol=1e-10, abs_tol=1e-11),
                                        (scenario, i, key, value, actual[key]))
                    else:
                        self.assertEqual(value, actual[key], (scenario, i, key))
                reversals += actual['direction_changed']
                deadbands += actual['in_deadband']
                saturations += actual['saturated']
            self.assertEqual(cpp.last_result, actual)
        self.assertGreater(reversals, 0)
        self.assertGreater(deadbands, 0)
        self.assertGreater(saturations, 0)

    def test_invalid_inputs(self):
        cpp = CycloViz.NLAPID()
        for inputs in ((1, 0, 0), (1, 0, -1), (float('nan'), 0, .1), (1, float('inf'), .1)):
            with self.assertRaises(ValueError):
                cpp.update(*inputs)
        with self.assertRaises(ValueError):
            cpp.set_gains(cpp_struct('NLAPIDGains', dict(kp=-1)))


if __name__ == '__main__':
    unittest.main()
