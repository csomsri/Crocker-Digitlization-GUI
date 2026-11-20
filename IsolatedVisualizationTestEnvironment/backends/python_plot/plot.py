"""Python geometry preparation and Matplotlib raster rendering."""

from time import perf_counter

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure


class PythonPlot(FigureCanvasQTAgg):
    def __init__(self, count):
        figure = Figure(facecolor="#151b24")
        super().__init__(figure)
        axes = figure.add_axes((0.04, 0.04, 0.92, 0.92), facecolor="#151b24")
        axes.set(xlim=(0, count), ylim=(-1, 1))
        axes.set_axis_off()
        self.bars = axes.bar(range(count), [0] * count, width=0.85, align="edge", linewidth=0)

    def render(self, heights):
        started = perf_counter()
        for bar, height in zip(self.bars, heights):
            bar.set_height(height)
            bar.set_color("#53c9c4" if height >= 0 else "#e9a66b")
        self.draw()
        self.repaint()
        return (perf_counter() - started) * 1000 if self.isVisible() else None


def prepare(values, scale, count):
    return [max(-1.0, min(1.0, values[i % len(values)] / scale)) for i in range(count)]
