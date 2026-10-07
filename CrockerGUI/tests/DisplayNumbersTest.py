"""Tiny telemetry tails must not expand into unbounded decimal labels."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from python.app.widgets.DisplayNumbers import display_number


class DisplayNumbersTest(unittest.TestCase):
    def test_tiny_values_have_bounded_display(self):
        for value in (3.76008e-60, -3.76008e-60, 5e-324):
            self.assertEqual(display_number(value), '≈ 0')

    def test_current_values_and_gain_precision(self):
        self.assertEqual(display_number(0), '0')
        self.assertEqual(display_number(.0000123), '0.000012')
        self.assertEqual(display_number(1234.5), '1,234.5')
        self.assertEqual(display_number(.00000001, significant=12, grouping=False, max_decimals=12), '0.00000001')

    def test_simulator_zero_decay_is_shrinking(self):
        value = 50.0
        for _ in range(2000):
            previous = value
            value += (0-value)*.1
            self.assertLessEqual(value, previous)
            self.assertLess(len(display_number(value)), 16)
        self.assertEqual(display_number(value), '≈ 0')


if __name__ == '__main__':
    unittest.main()
