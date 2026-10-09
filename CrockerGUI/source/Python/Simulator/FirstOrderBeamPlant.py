"""Deterministic TC10 beam plant for closed-loop PID and BO experiments."""
from __future__ import annotations

from dataclasses import replace
import json
import math
from pathlib import Path

from .ZMQSimulator import Smoke2Plant


class FirstOrderBeamPlant(Smoke2Plant):
    """tau * d(beam)/dt + beam = gain * TC10 + disturbance.

    Currents are A and nA. These synthetic coefficients are not a machine model.
    Other channels retain the smoke simulator's behaviour but cannot drive beam.
    """

    channel_index = 9

    def __init__(self, raw_scale=1e-8, time_constant_s=2.0, gain_na_per_a=0.004):
        super().__init__(raw_scale)
        if time_constant_s <= 0 or gain_na_per_a <= 0:
            raise ValueError("Time constant and gain must be positive")
        self.time_constant_s = time_constant_s
        self.gain_na_per_a = gain_na_per_a
        self.disturbance_na = 0.0
        self.beam_na = self.channels[self.channel_index] * gain_na_per_a
        calibration = Path(__file__).resolve().parents[3] / "config" / "beam_cal.json"
        self._points = json.loads(calibration.read_text())["ranges"][0]["points"]

    def apply_reply(self, reply, dt):
        # TC10 is the single first-order state; no second actuator lag is added.
        previous = self.channels[self.channel_index]
        super().apply_reply(reply, dt)
        i = self.channel_index
        target = self.targets[i] if self.enabled[i] and self.on_off[i] else self.running_values[i] if self.on_off[i] else 0.0
        alpha = -math.expm1(-max(0.0, dt) / self.time_constant_s)
        self.channels[i] = previous + alpha * (target - previous)
        self.beam_na = self.gain_na_per_a * self.channels[i] + self.disturbance_na

    def frame(self):
        frame = super().frame()
        # Invert the same detector calibration the GUI uses (uA at the boundary).
        value = max(0.0, self.beam_na) / 1000.0
        points = self._points
        pair = next(((a, b) for a, b in zip(points, points[1:]) if value <= b[1]), (points[-2], points[-1]))
        a, b = pair
        voltage = a[0] + (value - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
        return replace(frame, beam_current=voltage, beam_range_idx=0)
