"""Common workload and widget for all bar-plot configurations."""

import math
from pathlib import Path
from time import perf_counter

from PySide6.QtWidgets import QVBoxLayout, QWidget


class BarPlot(QWidget):
    name = "Bar plot"
    metrics = ("upload_ms", "kernel_ms", "download_ms", "render_ms", "bars",
               "renderer", "plot_width_px", "plot_height_px")

    def __init__(self, mode, library, bars, device, minimum_height=330):
        super().__init__()
        self.mode = mode
        self.bars = bars
        self.results = Path(__file__).with_name("results") / mode
        self.geometry = None
        if mode == "python-plot":
            from backends.python_plot.plot import PythonPlot, prepare

            self.renderer = PythonPlot(bars)
            self.prepare_python = prepare
        else:
            from backends.opengl import OpenGLPlot

            if mode == "cpu-opengl":
                from backends.cpu_opengl.geometry import CpuGeometry

                self.geometry = CpuGeometry(library, bars)
            else:
                from backends.cuda_opengl.geometry import CudaGeometry

                self.geometry = CudaGeometry(library, bars, device)
            self.renderer = OpenGLPlot(bars)
        self.renderer.setMinimumHeight(minimum_height)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.renderer)

    @property
    def device_id(self):
        return self.geometry.device_id if self.geometry is not None else ""

    def start(self):
        if self.geometry is not None:
            self.geometry.start()

    def stop(self):
        if self.geometry is not None:
            self.geometry.stop()

    def process(self, packet, validate=False):
        return self.plot_values(packet.get("channels", [])[:14], validate)

    def plot_values(self, values, validate=False, scale=None):
        if not values or any(not math.isfinite(v) or abs(v) > 3.4e38 for v in values):
            return None
        started = perf_counter()
        if scale is None:
            scale = max(max(map(abs, values)), 1e-30)
        if self.geometry is None:
            heights, timings = self.prepare_python(values, scale, self.bars), {}
        else:
            heights, timings = self.geometry.prepare(values, scale, validate)
        prepare_ms = (perf_counter() - started) * 1000
        render_ms = self.renderer.render(heights)
        pixel_ratio = self.renderer.devicePixelRatioF()
        return {
            "prepare_ms": prepare_ms,
            "render_ms": render_ms,
            "bars": self.bars,
            "renderer": getattr(self.renderer, "renderer_name", "Matplotlib Agg"),
            "plot_width_px": round(self.renderer.width() * pixel_ratio),
            "plot_height_px": round(self.renderer.height() * pixel_ratio),
            **timings,
        }
