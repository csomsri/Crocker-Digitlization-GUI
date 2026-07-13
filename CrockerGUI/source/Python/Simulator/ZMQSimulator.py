"""
Small ZeroMQ simulator for Crocker GUI dynamic tests.

The simulator behaves like the LabVIEW client: it sends little-endian doubles
to the GUI REP server and waits for the target reply before sending the next
frame.
"""

from __future__ import annotations

import argparse
import math
import struct
import time
from dataclasses import dataclass
from typing import Iterable

import zmq

ADDRESS = "tcp://127.0.0.1:5555"
NUM_CHANNELS = 14
EPOCH_OFFSET = 2082844800.0


@dataclass(frozen=True)
class SimulatorFrame:
    timestamp: float
    channels: list[float]
    bitmask: int


def build_bitmask(on_off: Iterable[bool], enable_ctrl: Iterable[bool]) -> int:
    bitmask = 0
    for index, enabled in enumerate(on_off):
        if enabled:
            bitmask |= 1 << index

    for index, enabled in enumerate(enable_ctrl):
        if enabled:
            bitmask |= 1 << (NUM_CHANNELS + index)

    return bitmask


def generate_frame(step: int, amplitude: float = 35.0, baseline: float = 300.0) -> SimulatorFrame:
    channels = [
        baseline + amplitude * math.sin((step * 0.18) + (channel * 0.55))
        for channel in range(NUM_CHANNELS)
    ]
    on_off = [(step + channel) % 9 != 0 for channel in range(NUM_CHANNELS)]
    enable_ctrl = [(step + channel) % 5 != 0 for channel in range(NUM_CHANNELS)]
    bitmask = build_bitmask(on_off, enable_ctrl)
    timestamp = time.time() + EPOCH_OFFSET
    return SimulatorFrame(timestamp=timestamp, channels=channels, bitmask=bitmask)


class ZMQSimulator:
    def __init__(self, endpoint: str = ADDRESS, timeout_ms: int = 1500) -> None:
        self.endpoint = endpoint
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
        self.socket.setsockopt(zmq.SNDTIMEO, timeout_ms)
        self.socket.connect(endpoint)

    def send_frame(self, frame: SimulatorFrame) -> list[float]:
        packet = struct.pack(
            f"<{NUM_CHANNELS + 2}d",
            frame.timestamp,
            *frame.channels,
            float(frame.bitmask),
        )
        self.socket.send(packet)
        reply = self.socket.recv()
        return list(struct.unpack(f"<{len(reply) // 8}d", reply))

    def stream(self, frames: int | None = None, rate_hz: float = 20.0) -> None:
        interval_seconds = 1.0 / rate_hz if rate_hz > 0 else 0.0
        next_frame_time = time.perf_counter()
        step = 0

        try:
            while frames is None or step < frames:
                frame = generate_frame(step)
                reply = self.send_frame(frame)
                print(
                    f"sent frame {step:04d}: "
                    f"ch0={frame.channels[0]:7.2f}, "
                    f"reply_bitmask={int(reply[-1]) if reply else 0}"
                )
                step += 1
                if interval_seconds > 0:
                    next_frame_time += interval_seconds
                    time.sleep(max(0.0, next_frame_time - time.perf_counter()))
        finally:
            self.close()

    def close(self) -> None:
        self.socket.close(0)
        self.context.term()


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream simulated Crocker ZMQ frames.")
    parser.add_argument("--endpoint", default=ADDRESS)
    parser.add_argument("--frames", type=int, default=None)
    parser.add_argument("--rate-hz", type=float, default=20.0)
    args = parser.parse_args()

    ZMQSimulator(args.endpoint).stream(frames=args.frames, rate_hz=args.rate_hz)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
