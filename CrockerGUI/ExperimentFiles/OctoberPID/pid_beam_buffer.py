# -*- coding: utf-8 -*-
"""Fresh high-rate beam samples for the single-loop PID (no Qt dependency).

Input is the original packet stream, BEFORE GUI decimation. Average raw beam
voltage within one meter range, then apply the existing calibration once.

Receive timestamps are stamped in the ZeroMQ process, not when a queued packet
finally reaches the GUI. A CycleMark excludes packets already received before
the previous decision/command. Source timestamps reject duplicates and define
the averaging duration. This does NOT constitute an acknowledgment that LabVIEW
applied a target or that the power supply/beam has settled.
"""
from __future__ import annotations

import math
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Mapping

VERSION = "single-loop-pid-1.0"


@dataclass(frozen=True)
class CycleMark:
    sequence: int
    receive_time: float
    source_time: float | None
    generation: int


@dataclass(frozen=True)
class BeamSample:
    sequence: int
    source_time: float
    receive_time: float
    raw: float
    range_index: int


class BeamSampleBuffer:
    """Bounded, thread-safe sample history. No hardware access and no fake samples."""

    def __init__(self, capacity: int = 10000):
        if capacity < 2:
            raise ValueError("capacity must be at least two")
        self._samples: deque[BeamSample] = deque(maxlen=capacity)
        self._intervals: deque[float] = deque(maxlen=101)
        self._lock = threading.RLock()
        self._sequence = 0
        self._generation = 0
        self._last_source: float | None = None
        self._last_receive: float | None = None
        self._range: int | None = None
        self._status = "NO HIGH-RATE BEAM DATA"
        self._healthy = False
        self.rejected_samples = 0

    def clear(self) -> None:
        """Explicit acquisition restart; never fabricates a fresh timestamp."""
        with self._lock:
            self._samples.clear()
            self._intervals.clear()
            self._last_source = None
            self._last_receive = None
            self._range = None
            self._generation += 1
            self._healthy = False
            self._status = "WAITING FOR FRESH BEAM DATA"

    def mark(self, now: float | None = None) -> CycleMark:
        with self._lock:
            return CycleMark(self._sequence,
                             time.monotonic() if now is None else float(now),
                             self._last_source, self._generation)

    def _invalidate(self, message: str) -> bool:
        self.rejected_samples += 1
        self._healthy = False
        self._status = message
        self._samples.clear()
        self._intervals.clear()
        self._generation += 1
        return False

    def add(self, raw: float, range_index: int, source_time: float,
            receive_time: float) -> bool:
        """Append one original sample. Equal/backwards source times are ignored."""
        with self._lock:
            try:
                raw, source_time, receive_time = map(float, (raw, source_time, receive_time))
                index_float = float(range_index)
                range_index = int(index_float)
            except (TypeError, ValueError, OverflowError):
                return self._invalidate("INVALID BEAM PACKET")
            if not all(math.isfinite(v) for v in (raw, source_time, receive_time, index_float)):
                return self._invalidate("NON-FINITE BEAM PACKET")
            if source_time <= 0 or receive_time <= 0 or index_float != range_index or range_index < 0:
                return self._invalidate("INVALID BEAM TIMESTAMP OR RANGE")
            if self._last_source is not None and source_time <= self._last_source:
                # A held value must not refresh freshness or enter the mean again.
                self.rejected_samples += 1
                return False
            if self._last_receive is not None and receive_time < self._last_receive:
                self.rejected_samples += 1
                return False
            gap = None if self._last_source is None else source_time - self._last_source
            changed_range = self._range is not None and range_index != self._range
            typical_dt = statistics.median(self._intervals) if self._intervals else None
            gap_detected = (gap is not None and typical_dt is not None
                            and gap > max(0.05, 3.0 * typical_dt))
            if changed_range or gap_detected:
                self._samples.clear()
                self._intervals.clear()
                self._generation += 1
            elif gap is not None and gap > 0:
                self._intervals.append(gap)
            self._sequence += 1
            self._samples.append(BeamSample(self._sequence, source_time, receive_time, raw, range_index))
            self._last_source = source_time
            self._last_receive = receive_time
            self._range = range_index
            self._healthy = True
            self._status = "LIVE HIGH-RATE BEAM"
            return True

    def add_packet(self, packet: Mapping, range_selector: Callable[[dict], int] | None = None) -> bool:
        """Use server-stamped timing; do not silently timestamp an old GUI packet now."""
        try:
            raw = packet.get("beam_current", packet.get("beam_v_raw", packet.get("beam")))
            if isinstance(raw, (tuple, list)):
                if len(raw) != 1:
                    raise ValueError("expected one scalar beam sample per packet")
                raw = raw[0]
            index = packet.get("beam_range_idx", packet.get("range_idx"))
            if index is None and range_selector is not None:
                index = range_selector(dict(packet))
            source = packet.get("_pid_source_s")
            received = packet.get("_pid_rx_mono")
            if source is None or received is None:
                with self._lock:
                    return self._invalidate("PID STREAM NOT TIMESTAMPED — RESTART UPDATED MAIN.PY")
            return self.add(raw, index, source, received)
        except (TypeError, ValueError, OverflowError):
            with self._lock:
                return self._invalidate("INVALID HIGH-RATE BEAM PACKET")

    def snapshot(self, window_s: float, max_age_s: float,
                 calibrate: Callable[[float, int], float], *,
                 after: CycleMark | None = None, now: float | None = None) -> dict:
        """Return the latest complete mean, or a reason to HOLD (never a partial mean).

        At a regular 100 Hz, 300 ms corresponds to approximately 30 ORIGINAL
        samples. At a slower rate, the actual count is reported, never assumed.
        At least two samples are needed for an average. After an interruption or
        range change, a new complete window is required.
        """
        window_s, max_age_s = float(window_s), float(max_age_s)
        now = time.monotonic() if now is None else float(now)
        if not all(math.isfinite(v) for v in (window_s, max_age_s, now)) or window_s <= 0 or max_age_s <= 0:
            raise ValueError("averaging window and stale limit must be positive and finite")
        with self._lock:
            out = {"valid": False, "ready": False, "fresh": False,
                   "value_nA": float("nan"), "raw_mean": float("nan"),
                   "raw_latest": float("nan"), "timestamp": 0.0,
                   "age_s": float("inf"), "sample_count": 0,
                   "window_s": 0.0, "requested_window_s": window_s,
                   "generation": self._generation, "sequence": self._sequence,
                   "status": self._status, "range_index": self._range,
                   "source_first_s": None, "source_last_s": None,
                   "receive_first_s": None, "receive_last_s": None}
            if not self._samples or not self._healthy:
                return out
            latest = self._samples[-1]
            age = now - latest.receive_time
            out.update(timestamp=latest.receive_time, age_s=max(0.0, age),
                       raw_latest=latest.raw, source_last_s=latest.source_time)
            if age < -0.05:
                out["status"] = "INVALID RECEIVE CLOCK"
                return out
            if age > max_age_s:
                out["status"] = "BEAM FEEDBACK STALE"
                return out
            out["fresh"] = True
            eligible = list(self._samples)
            if after is not None:
                eligible = [s for s in eligible
                            if s.sequence > after.sequence and s.receive_time > after.receive_time]
            if len(eligible) < 2:
                out.update(status="COLLECTING FRESH BEAM SAMPLES", sample_count=len(eligible))
                return out
            latest = eligible[-1]
            tail = eligible[-102:]
            periods = [tail[i].source_time - tail[i-1].source_time for i in range(1, len(tail))]
            nominal_dt = statistics.median(periods)
            threshold = latest.source_time - window_s
            tolerance = max(1e-7, abs(latest.source_time) * 2e-16)
            chosen = [s for s in eligible if s.source_time > threshold + tolerance]
            if len(chosen) < 2:
                chosen = eligible[-2:]
            support_start = chosen[0].source_time - nominal_dt
            if after is not None and after.generation == self._generation and after.source_time is not None:
                support_start = max(support_start, after.source_time)
            duration = latest.source_time - support_start
            out.update(sample_count=len(chosen), window_s=duration,
                       source_first_s=chosen[0].source_time, source_last_s=latest.source_time,
                       receive_first_s=chosen[0].receive_time, receive_last_s=latest.receive_time,
                       timestamp=latest.receive_time, sequence=latest.sequence,
                       age_s=max(0.0, now - latest.receive_time))
            if duration + tolerance < window_s:
                out["status"] = "COLLECTING COMPLETE BEAM AVERAGE"
                return out
            raw_mean = math.fsum(s.raw for s in chosen) / len(chosen)
            try:
                value = float(calibrate(raw_mean, latest.range_index))
                if not math.isfinite(value):
                    raise ValueError("non-finite calibrated mean")
            except Exception as exc:
                out.update(fresh=False, raw_mean=raw_mean,
                           status=f"BEAM AVERAGE CALIBRATION ERROR: {exc}")
                return out
            out.update(valid=True, ready=True, value_nA=value, raw_mean=raw_mean,
                       range_index=latest.range_index,
                       status=f"AVERAGED {len(chosen)} SAMPLES / {duration*1000:.0f} ms")
            return out


BEAM_BUFFER = BeamSampleBuffer()


def feed_pid_packet(packet: Mapping) -> bool:
    """Called by MainControlWindow for EVERY original packet, not averaged ones."""
    from beam_cal import beam_cal
    return BEAM_BUFFER.add_packet(packet, beam_cal.select_index_for_pkt)


def calibrate_beam_mean(raw: float, range_index: int) -> float:
    """Preserve installed calibration; don't clip an out-of-support LUT mean."""
    from beam_cal import beam_cal
    if not 0 <= range_index < len(beam_cal.cfg.ranges):
        raise ValueError("beam meter range is invalid")
    selected = beam_cal.cfg.ranges[range_index]
    if selected.mode == "curve" and selected.curve:
        xs = [float(pair[0]) for pair in selected.curve]
        if raw < min(xs) or raw > max(xs):
            raise ValueError("averaged voltage is outside the calibrated curve")
    return float(beam_cal.volts_to_nA(raw, range_index))
