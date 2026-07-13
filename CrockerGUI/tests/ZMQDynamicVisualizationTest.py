"""
Dynamic visualization smoke test driven by the ZMQ simulator.

Run from the repository root after building the CycloViz Python extension:
    python CrockerGUI/tests/ZMQDynamicVisualizationTest.py
"""

from __future__ import annotations

import argparse
import importlib
import math
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QWidget

REPO_ROOT = Path(__file__).resolve().parents[2]
CROCKER_ROOT = REPO_ROOT / "CrockerGUI"
SIMULATOR_ROOT = CROCKER_ROOT / "source" / "Python" / "Simulator"

for candidate in (
    CROCKER_ROOT,
    CROCKER_ROOT / "Debug",
    CROCKER_ROOT / "Release",
    CROCKER_ROOT / "build" / "Debug",
    CROCKER_ROOT / "build" / "Release",
    SIMULATOR_ROOT,
):
    sys.path.insert(0, str(candidate))

CycloViz = importlib.import_module("CycloViz")
from ZMQSimulator import ZMQSimulator, generate_frame


@dataclass
class RollingTiming:
    maxlen: int = 240
    intervals_ms: deque[float] = field(init=False)
    last_time: float | None = None

    def __post_init__(self) -> None:
        self.intervals_ms = deque(maxlen=self.maxlen)

    def mark(self) -> None:
        now = time.perf_counter()
        if self.last_time is not None:
            self.intervals_ms.append((now - self.last_time) * 1000.0)
        self.last_time = now

    def average_ms(self) -> float:
        if not self.intervals_ms:
            return 0.0
        return sum(self.intervals_ms) / len(self.intervals_ms)

    def fps(self) -> float:
        average = self.average_ms()
        return 1000.0 / average if average > 0 else 0.0


class ChannelBars(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.channels = [0.0] * 14
        self.history = deque(maxlen=160)
        self.paint_timing = RollingTiming()
        self.setMinimumSize(920, 520)

    def set_channels(self, channels: list[float]) -> None:
        self.channels = channels[:14]
        if self.channels:
            self.history.append(self.channels[0])

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        self.paint_timing.mark()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(18, 22, 28))

        margin = 34
        chart = self.rect().adjusted(margin, margin, -margin, -margin)
        if chart.width() <= 0 or chart.height() <= 0:
            return

        painter.setPen(QPen(QColor(82, 92, 106), 1))
        painter.drawRect(chart)

        low = min(self.channels + [240.0])
        high = max(self.channels + [360.0])
        span = max(high - low, 1.0)
        bar_width = chart.width() / 14.0

        for index, value in enumerate(self.channels):
            normalized = (value - low) / span
            height = normalized * chart.height()
            x = chart.left() + index * bar_width + 4
            y = chart.bottom() - height
            hue = 185 + int(45 * math.sin(index * 0.8))
            painter.fillRect(
                int(x),
                int(y),
                max(4, int(bar_width - 8)),
                int(height),
                QColor.fromHsv(hue % 360, 170, 225),
            )

        if len(self.history) > 1:
            painter.setPen(QPen(QColor(255, 209, 102), 2))
            points = []
            for index, value in enumerate(self.history):
                x = chart.left() + (index / (self.history.maxlen - 1)) * chart.width()
                y = chart.bottom() - ((value - low) / span) * chart.height()
                points.append((x, y))

            for previous, current in zip(points, points[1:]):
                painter.drawLine(int(previous[0]), int(previous[1]), int(current[0]), int(current[1]))

        painter.setPen(QColor(218, 224, 232))
        painter.drawText(chart.left(), margin - 10, "ZMQ dynamic channel visualization")
        painter.setPen(QColor(150, 160, 174))
        painter.drawText(chart.left(), self.height() - 10, f"range {low:.1f} to {high:.1f}")


class VisualizationWindow(QMainWindow):
    def __init__(self, server, endpoint: str, render_hz: float) -> None:
        super().__init__()
        self.server = server
        self.chart = ChannelBars()
        self.status = QLabel("waiting for simulator packets")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet("color: #c7d0dc; background: #12161c; padding: 8px;")

        container = QWidget()
        container.setStyleSheet("background: #12161c;")
        container.setLayoutDirection(Qt.LeftToRight)
        self.setCentralWidget(container)

        from PySide6.QtWidgets import QVBoxLayout

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.chart, 1)
        layout.addWidget(self.status)

        self.packet_count = 0
        self.latest_packet: dict | None = None
        self.packet_timing = RollingTiming()
        self.render_timing = RollingTiming()
        self.setWindowTitle(f"Crocker ZMQ Visualization Test - {endpoint}")
        self.resize(980, 620)

        self.drain_timer = QTimer(self)
        self.drain_timer.timeout.connect(self.drain_packets)
        self.drain_timer.start(5)

        self.render_timer = QTimer(self)
        self.render_timer.timeout.connect(self.render_frame)
        self.render_timer.start(max(1, int(1000 / render_hz)))

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start(250)

    def drain_packets(self) -> None:
        while True:
            packet = self.server.TryPopPacket()
            if packet is None:
                break

            self.packet_count += 1
            self.packet_timing.mark()
            self.latest_packet = packet

    def render_frame(self) -> None:
        self.render_timing.mark()
        if self.latest_packet is not None:
            channels = [
                float(value)
                for value in self.latest_packet.get("channels", [])[:14]
            ]
            self.chart.set_channels(channels)
        self.chart.update()

    def refresh_status(self) -> None:
        packet = self.latest_packet or {}
        channels = packet.get("channels", [])
        first_channel = float(channels[0]) if channels else 0.0
        self.status.setText(
            f"packets {self.packet_count} | ch0 {first_channel:.2f} | "
            f"latency {packet.get('latency', 0.0):.1f} ms | "
            f"packet {self.packet_timing.fps():.1f} Hz ({self.packet_timing.average_ms():.1f} ms) | "
            f"render {self.render_timing.fps():.1f} Hz ({self.render_timing.average_ms():.1f} ms) | "
            f"paint {self.chart.paint_timing.fps():.1f} Hz ({self.chart.paint_timing.average_ms():.1f} ms)"
        )


def run_simulator(endpoint: str, stop_event: threading.Event, rate_hz: float) -> None:
    simulator = ZMQSimulator(endpoint)
    step = 0
    interval_seconds = 1.0 / rate_hz if rate_hz > 0 else 0.0
    next_frame_time = time.perf_counter()

    try:
        while not stop_event.is_set():
            simulator.send_frame(generate_frame(step))
            step += 1
            if interval_seconds <= 0:
                continue

            next_frame_time += interval_seconds
            sleep_seconds = max(0.0, next_frame_time - time.perf_counter())
            stop_event.wait(sleep_seconds)
    finally:
        simulator.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Visualize live packets from the ZMQ simulator.")
    parser.add_argument("--endpoint", default="tcp://127.0.0.1:5555")
    parser.add_argument("--rate-hz", type=float, default=20.0)
    parser.add_argument("--render-hz", type=float, default=60.0)
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=None,
        help="Close automatically after this many seconds; useful for smoke tests.",
    )
    args = parser.parse_args()

    app = QApplication(sys.argv)

    server = CycloViz.ZMQServer(args.endpoint)
    server.Start()

    endpoint = ""
    for _ in range(50):
        endpoint = server.BoundEndpoint()
        if endpoint:
            break
        time.sleep(0.02)

    if not endpoint:
        server.Stop()
        raise RuntimeError("ZMQServer did not bind an endpoint")

    stop_event = threading.Event()
    simulator_thread = threading.Thread(
        target=run_simulator,
        args=(endpoint, stop_event, args.rate_hz),
        daemon=True,
    )
    simulator_thread.start()

    window = VisualizationWindow(server, endpoint, args.render_hz)
    window.show()

    if args.duration_seconds is not None:
        QTimer.singleShot(max(1, int(args.duration_seconds * 1000)), window.close)

    try:
        return app.exec()
    finally:
        stop_event.set()
        simulator_thread.join(timeout=2.0)
        server.Stop()


if __name__ == "__main__":
    raise SystemExit(main())
