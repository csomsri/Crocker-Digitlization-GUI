"""Compare visualization backends against Crocker's standard ZMQ REP server."""

import argparse
import math
from pathlib import Path
import sys
from threading import Event, Thread
from time import monotonic

from PySide6.QtCore import QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from benchmark_page import BenchmarkPage
from features.bar_plot.feature import BarPlot
from features.dashboard.feature import SectionPlots

ROOT = Path(__file__).resolve().parent
CROCKER = ROOT.parent / "CrockerGUI"
FEATURES = {"dashboard": SectionPlots, "bar-plot": BarPlot}
MODES = ("python-plot", "cpu-opengl", "cuda-opengl")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature", choices=FEATURES, default="dashboard")
    parser.add_argument("--mode", choices=MODES, default="python-plot")
    parser.add_argument("--library", type=Path, help="Path to the native feature DLL or .so")
    parser.add_argument("--bars", type=int, help="Override the bar count for each multichannel panel")
    parser.add_argument("--cuda-device", type=int, default=0, help="CUDA device ordinal")
    parser.add_argument("--gpu-id", default="0", help="nvidia-smi index, UUID or PCI ID")
    parser.add_argument("--port", type=int, default=0, help="Loopback port. Default chooses a free port.")
    parser.add_argument("--external", action="store_true", help="Wait for a separate test sender")
    parser.add_argument("--rate-hz", type=float, default=60.0, help="Built-in simulator packet rate")
    parser.add_argument("--record", action="store_true", help="Record immediately")
    parser.add_argument("--warmup-frames", type=int, default=30)
    parser.add_argument("--duration-seconds", type=float, help="Close after this many seconds")
    args = parser.parse_args()
    if args.mode != "python-plot" and args.library is None:
        parser.error("--library is required for the OpenGL configurations")
    if args.bars is not None and not (1 <= args.bars <= 4096):
        parser.error("--bars must be between 1 and 4096")
    if args.warmup_frames < 1:
        parser.error("--warmup-frames must be at least 1")
    if not (0 <= args.port <= 65535 and args.cuda_device >= 0):
        parser.error("Port or CUDA device ordinal out of range")
    if not (math.isfinite(args.rate_hz) and args.rate_hz > 0):
        parser.error("--rate-hz must be finite and positive")
    if args.duration_seconds is not None and not (0 < args.duration_seconds <= 86400):
        parser.error("--duration-seconds must be greater than zero and at most 86400")
    return args


def run_simulator(endpoint, stop, rate, dashboard):
    sys.path.insert(0, str(CROCKER / "source" / "Python" / "Simulator"))
    from ZMQSimulator import Smoke2Plant, ZMQSimulator, generate_frame

    simulator = ZMQSimulator(endpoint, timeout_ms=500)
    plant = Smoke2Plant() if dashboard else None
    try:
        step = 0
        next_frame = monotonic()
        while not stop.is_set():
            reply = simulator.send_frame(plant.frame() if plant else generate_frame(step))
            if plant:
                plant.apply_reply(reply, 1 / rate)
            step += 1
            next_frame = max(next_frame + 1 / rate, monotonic())
            stop.wait(max(0, next_frame - monotonic()))
    except Exception as error:
        if not stop.is_set():
            print(f"Simulator stopped: {error}", file=sys.stderr)
    finally:
        simulator.close()


def main():
    args = parse_args()
    sys.path.insert(0, str(CROCKER))
    try:
        from CycloViz import ZMQServer
    except ImportError as error:
        raise RuntimeError("Build CrockerGUI's CycloViz extension for this Python interpreter") from error

    if args.mode != "python-plot":
        surface = QSurfaceFormat()
        surface.setVersion(3, 3)
        surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        QSurfaceFormat.setDefaultFormat(surface)
    app = QApplication([])
    bars = args.bars if args.feature == "dashboard" else (args.bars or 14)
    feature = FEATURES[args.feature](args.mode, args.library, bars, args.cuda_device)
    endpoint = f"tcp://127.0.0.1:{args.port if args.port else '*'}"
    server = ZMQServer(endpoint)
    stop = Event()
    sender = None
    server.Start()
    try:
        feature.start()
        for _ in range(100):
            bound = server.BoundEndpoint()
            if bound:
                break
            stop.wait(0.02)
        else:
            raise RuntimeError(f"Crocker ZMQ server could not bind {endpoint}")
        print(f"Listening on {bound}", flush=True)
        page = BenchmarkPage(server, bound, feature, args.gpu_id, args.warmup_frames,
                             None if args.external else args.rate_hz)
        page.show()
        if args.record:
            if not page.start_recording():
                raise RuntimeError(page.result.text())
        if not args.external:
            sender = Thread(target=run_simulator,
                            args=(bound, stop, args.rate_hz, args.feature == "dashboard"),
                            daemon=True)
            sender.start()
        if args.duration_seconds is not None:
            QTimer.singleShot(int(args.duration_seconds * 1000), page.close)
        code = app.exec()
        if args.record and (page.recording_failed or not page.frames):
            print("No complete recording. " + page.result.text(), file=sys.stderr)
            return 1
        return code
    finally:
        stop.set()
        if sender is not None:
            sender.join(timeout=1)
        server.Stop()
        feature.stop()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as error:
        raise SystemExit(str(error)) from error
