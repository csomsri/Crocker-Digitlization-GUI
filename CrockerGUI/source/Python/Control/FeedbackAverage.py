"""Non-overlapping fresh sample means for OctoberPID control decisions."""
import math


class FeedbackAverage:
    def __init__(self, seconds=0.3):
        self.seconds = float(seconds)
        if not math.isfinite(self.seconds) or self.seconds < 0:
            raise ValueError("Feedback averaging time must be finite and nonnegative")
        self.reset()

    def reset(self):
        self.last_stamp = None
        self.window_start = None
        self.total = 0.0
        self.count = 0

    def add(self, stamp, value):
        if not all(math.isfinite(v) for v in (stamp, value)):
            raise ValueError("Invalid feedback sample")
        if self.last_stamp is not None and stamp < self.last_stamp:
            raise ValueError("Feedback timestamp moved backwards")
        if self.last_stamp is not None and stamp == self.last_stamp:
            return None
        self.last_stamp = stamp
        if self.window_start is None:
            self.window_start = stamp
        self.total += value
        self.count += 1
        if stamp - self.window_start < self.seconds:
            return None
        result = self.total / self.count
        # The boundary belongs to the completed window only.
        self.window_start = stamp
        self.total = 0.0
        self.count = 0
        return result
