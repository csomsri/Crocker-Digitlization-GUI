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
from threading import Event
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

    def stream(
        self,
        frames: int | None = None,
        rate_hz: float = 20.0,
        stop_event: Event | None = None,
        plant: "CyclotronPlant | None" = None,
    ) -> None:
        interval_seconds = 1.0 / rate_hz if rate_hz > 0 else 0.0
        next_frame_time = time.perf_counter()
        step = 0

        try:
            while (frames is None or step < frames) and not (stop_event and stop_event.is_set()):
                frame = plant.frame() if plant is not None else generate_frame(step)
                reply = self.send_frame(frame)
                if plant is not None:
                    plant.apply_reply(reply, interval_seconds)
                if plant is None:
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


class CyclotronPlant:
    """Cyclotron plant that speaks the existing 14-channel ZMQ contract.

    GUI channel values remain in their existing 0..1000 engineering range.
    Main Magnet maps linearly to 0..1 tesla, while the trim channels provide
    small field corrections around their 500-unit midpoint.
    """

    def __init__(self) -> None:
        try:
            import CycloViz
        except Exception as exc:
            raise RuntimeError("CycloViz with CyclotronModel is required") from exc
        if not hasattr(CycloViz, "CyclotronModel"):
            raise RuntimeError("Rebuild CycloViz so it includes CyclotronModel")

        config = CycloViz.CyclotronConfig()
        config.magnetic_field_t = 0.1
        config.rf_frequency_hz = 15.245e6
        config.rf_peak_electric_field_v_m = 100_000.0
        config.gap_half_width_m = 0.0025
        config.chamber_radius_m = 0.25
        config.time_step_s = 1.0e-10
        self.model = CycloViz.CyclotronModel(config)
        self.channels = [0.0] * NUM_CHANNELS
        self.targets = [0.0] * NUM_CHANNELS
        self.on_off = [False] * NUM_CHANNELS
        self.enabled = [False] * NUM_CHANNELS

    def frame(self) -> SimulatorFrame:
        return SimulatorFrame(
            timestamp=time.time() + EPOCH_OFFSET,
            channels=list(self.channels),
            bitmask=build_bitmask(self.on_off, self.enabled),
        )

    def apply_reply(self, reply: list[float], dt: float) -> None:
        if len(reply) < NUM_CHANNELS + 1:
            return
        self.targets = reply[:NUM_CHANNELS]
        mask = int(round(reply[NUM_CHANNELS]))
        self.on_off = [bool(mask & (1 << index)) for index in range(NUM_CHANNELS)]
        self.enabled = [
            bool(mask & (1 << (NUM_CHANNELS + index))) for index in range(NUM_CHANNELS)
        ]

        alpha = min(1.0, 4.0 * max(0.0, dt))
        for index in range(NUM_CHANNELS):
            target = self.targets[index] if self.on_off[index] and self.enabled[index] else 0.0
            self.channels[index] += (target - self.channels[index]) * alpha

        main_field_t = max(1.0e-6, self.channels[12] / 1000.0)
        trim_correction_t = sum((value - 500.0) * 1.0e-6 for value in self.channels[:12])
        self.model.set_magnetic_field_t(max(1.0e-6, main_field_t + trim_correction_t))
        # Advance a bounded physical-time window per telemetry frame. Cyclotron
        # motion occurs on nanosecond scales, not the GUI's wall-clock scale.
        self.model.step(5_000)
        if self.model.diagnostics.lost:
            self.model.reset()


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream simulated Crocker ZMQ frames.")
    parser.add_argument("--endpoint", default=ADDRESS)
    parser.add_argument("--frames", type=int, default=None)
    parser.add_argument("--rate-hz", type=float, default=20.0)
    parser.add_argument(
        "--plant",
        choices=("smoke", "cyclotron"),
        default="smoke",
        help="Plant model to stream. Default: smoke",
    )
    args = parser.parse_args()

    plant = CyclotronPlant() if args.plant == "cyclotron" else None
    ZMQSimulator(args.endpoint).stream(frames=args.frames, rate_hz=args.rate_hz, plant=plant)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
