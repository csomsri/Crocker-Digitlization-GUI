from __future__ import annotations

import math
import time
from collections import deque

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QWidget


MAX_GAUGE_VALUE = 1000.0
CHANNEL_NAMES = [f"TC{i}" for i in range(1, 13)] + ["Main Magnet", "Centering Beam"]
FIELD_PLOT_SAMPLE_RATE_HZ = 60
FIELD_PLOT_SAMPLE_LIMIT = 2160
FIELD_PLOT_VISIBLE_SAMPLES = 1800
FIELD_PLOT_RENDER_SAMPLES = 360
FIELD_PLOT_VISIBLE_SECONDS = 30.0
FIELD_MONITOR_GROUPS = (
    ("Trim Coils 1-4", tuple(range(0, 4))),
    ("Trim Coils 5-8", tuple(range(4, 8))),
    ("Trim Coils 9-12", tuple(range(8, 12))),
)
FIELD_AUXILIARY_GROUP = ("Auxiliary Magnets", (12, 13))


class MagneticFieldPlotState:
    def __init__(self) -> None:
        self.target_values = [0.0 for _ in CHANNEL_NAMES]
        self.actual_values = [0.0 for _ in CHANNEL_NAMES]
        self.plot_enabled = [True for _ in CHANNEL_NAMES]
        self.history = [deque(maxlen=FIELD_PLOT_SAMPLE_LIMIT) for _ in CHANNEL_NAMES]
        self.last_updated = 0.0

    def set_plot_enabled(self, index: int, enabled: bool) -> None:
        if 0 <= index < len(self.plot_enabled):
            self.plot_enabled[index] = bool(enabled)
            self.last_updated = time.perf_counter()

    def set_values(self, index: int, actual: float, target: float) -> None:
        if 0 <= index < len(CHANNEL_NAMES):
            self.actual_values[index] = clamp(actual)
            self.target_values[index] = clamp(target)
            self.last_updated = time.perf_counter()

    def append_sample(self, index: int, timestamp: float, actual: float, target: float, error: float) -> None:
        if 0 <= index < len(self.history):
            self.set_values(index, actual, target)
            self.history[index].append((timestamp, actual, target, error))

    def enabled_indices(self, indices: tuple[int, ...]) -> list[int]:
        return [index for index in indices if index < len(self.plot_enabled) and self.plot_enabled[index]]


_MAGNETIC_FIELD_PLOT_STATE = MagneticFieldPlotState()


def magnetic_field_plot_state() -> MagneticFieldPlotState:
    return _MAGNETIC_FIELD_PLOT_STATE


def clamp(value: float, lower: float = 0.0, upper: float = MAX_GAUGE_VALUE) -> float:
    return max(lower, min(upper, float(value)))


class BubbleToggle(QPushButton):
    def __init__(self, tooltip: str, color: str = "#60a5fa", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setMinimumSize(96, 28)
        self.setMaximumHeight(28)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFlat(True)
        self._color = QColor(color)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(6.0, 1.5, -6.0, -1.5)
        checked = self.isChecked()
        hovered = self.underMouse()

        border = QColor(self._color)
        border.setAlpha(245 if checked else (165 if hovered else 105))
        fill = QColor(self._color)
        fill.setAlpha(42 if checked else (16 if hovered else 5))

        painter.setPen(QPen(border, 2.0 if checked else 1.2))
        painter.setBrush(fill)
        painter.drawRoundedRect(bounds, 6.0, 6.0)

        # Offset inner rails keep the compact toggle readable at small sizes.
        rail = QColor(self._color)
        rail.setAlpha(180 if checked else 55)
        painter.setPen(QPen(rail, 1.0))
        painter.drawLine(QPointF(bounds.left() + 8, bounds.top() + 4),
                         QPointF(bounds.right() - 18, bounds.top() + 4))
        painter.drawLine(QPointF(bounds.left() + 18, bounds.bottom() - 4),
                         QPointF(bounds.right() - 8, bounds.bottom() - 4))

        text_color = QColor(self._color)
        text_color.setAlpha(255 if checked else 125)
        painter.setPen(text_color)
        painter.drawText(bounds, Qt.AlignCenter, "ON" if checked else "OFF")


class ClickableValue(QLabel):
    clicked = Signal(int)

    def __init__(self, index: int, text: str = "0.00") -> None:
        super().__init__(text)
        self.index = index
        self.setCursor(Qt.PointingHandCursor)
        self.setAlignment(Qt.AlignCenter)
        self.setObjectName("fieldValue")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.index)
        super().mousePressEvent(event)


class NativeSpeedometer(QOpenGLWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        surface_format = self.format()
        surface_format.setSamples(8)
        self.setFormat(surface_format)
        self.setMinimumSize(360, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._target = 0.0
        self._actual = 0.0
        self._display_actual = 0.0
        self._channel = CHANNEL_NAMES[0]
        self._converged = True
        self._error = 0.0
        self._tolerance = 0.5
        self._convergence_seconds = 0.0
        self._timing_active = False
        self._native = None
        self._ready = False
        self._frame_timer = QElapsedTimer()
        self._animation_clock = QElapsedTimer()
        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(16)
        self._animation_timer.timeout.connect(self._animate_needle)

    def set_values(self, target: float, actual: float, channel: str) -> None:
        channel_changed = channel != self._channel
        self._target = clamp(target)
        self._actual = clamp(actual)
        self._channel = channel
        if channel_changed:
            self._display_actual = self._actual
        if abs(self._actual - self._display_actual) >= 0.01:
            if not self._animation_clock.isValid():
                self._animation_clock.start()
            self._animation_timer.start()
        self._push_values()

    def _animate_needle(self) -> None:
        elapsed_ms = max(1, self._animation_clock.restart())
        blend = 1.0 - math.exp(-elapsed_ms / 140.0)
        self._display_actual += (self._actual - self._display_actual) * blend
        if abs(self._actual - self._display_actual) < 0.01:
            self._display_actual = self._actual
            self._animation_timer.stop()
        self._push_values()

    def _push_values(self) -> None:
        changed = True
        if self._ready and self._native is not None:
            changed = self._native.set_values(
                self._target, self._display_actual, MAX_GAUGE_VALUE, self._channel
            )
        if changed and (not self._frame_timer.isValid() or self._frame_timer.elapsed() >= 14):
            self._frame_timer.restart()
            self.update()

    def set_status(
        self,
        converged: bool,
        error: float,
        tolerance: float,
        convergence_seconds: float,
        timing_active: bool,
    ) -> None:
        self._converged = converged
        self._error = float(error)
        self._tolerance = float(tolerance)
        self._convergence_seconds = float(convergence_seconds)
        self._timing_active = timing_active
        if self._ready and self._native is not None:
            changed = self._native.set_status(
                self._converged,
                self._error,
                self._tolerance,
                self._convergence_seconds,
                self._timing_active,
            )
            if not changed:
                return
        if not self._frame_timer.isValid() or self._frame_timer.elapsed() >= 45:
            self._frame_timer.restart()
            self.update()

    def initializeGL(self) -> None:
        try:
            import CycloViz
            from PySide6.QtGui import QOpenGLContext

            context = QOpenGLContext.currentContext()

            def get_proc(name: str) -> int:
                address = context.getProcAddress(name.encode("ascii"))
                return int(address) if address else 0

            CycloViz.load_opengl(get_proc)
            self._native = CycloViz.MagneticFieldSpeedometer()
            self._display_actual = self._actual
            self._native.set_values(self._target, self._display_actual, MAX_GAUGE_VALUE, self._channel)
            self._native.set_status(
                self._converged,
                self._error,
                self._tolerance,
                self._convergence_seconds,
                self._timing_active,
            )
            self._ready = True
        except Exception as exc:
            self._ready = False
            self._native = None
            print(f"[FieldCtrl] Native OpenGL speedometer unavailable: {exc}")

    def paintGL(self) -> None:
        if not self._ready or self._native is None:
            return
        pixel_ratio = self.devicePixelRatio()
        self._native.render(
            max(1, int(round(self.width() * pixel_ratio))),
            max(1, int(round(self.height() * pixel_ratio))),
        )


class MissingNativeSpeedometer(QLabel):
    def __init__(self, reason: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(360, 280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAlignment(Qt.AlignCenter)
        self.setObjectName("chartPlaceholder")
        self.setText(
            "Native C++ OpenGL speedometer unavailable.\n"
            "Rebuild CycloViz or check the Python extension path.\n\n"
            f"{reason}"
        )

    def set_values(self, target: float, actual: float, channel: str) -> None:
        return

    def set_status(
        self,
        converged: bool,
        error: float,
        tolerance: float,
        convergence_seconds: float,
        timing_active: bool,
    ) -> None:
        return


class TimeDomainPlot(QOpenGLWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        surface_format = self.format()
        surface_format.setSamples(8)
        self.setFormat(surface_format)
        self.setMinimumHeight(155)
        self.setMaximumHeight(170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setObjectName("timeDomainPlot")
        self._samples: list[tuple[float, float, float, float]] = []
        self._native = None
        self._ready = False

    def set_samples(self, samples: list[tuple[float, float, float, float]]) -> None:
        self._samples = list(samples)
        if self._ready and self._native is not None:
            self._native.set_samples(self._samples)
        self.update()

    def initializeGL(self) -> None:
        try:
            import CycloViz
            from PySide6.QtGui import QOpenGLContext

            context = QOpenGLContext.currentContext()

            def get_proc(name: str) -> int:
                address = context.getProcAddress(name.encode("ascii"))
                return int(address) if address else 0

            CycloViz.load_opengl(get_proc)
            self._native = CycloViz.TimeDomainLinePlot()
            self._native.set_samples(self._samples)
            self._ready = True
        except Exception as exc:
            self._ready = False
            self._native = None
            print(f"[FieldCtrl] Native OpenGL time-domain plot unavailable: {exc}")

    def paintGL(self) -> None:
        if not self._ready or self._native is None:
            return
        pixel_ratio = self.devicePixelRatio()
        self._native.render(
            max(1, int(round(self.width() * pixel_ratio))),
            max(1, int(round(self.height() * pixel_ratio))),
        )


class QtTimeDomainPlot(QWidget):
    """Qt-painted fallback for the time plot when OpenGL text is unreliable."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(155)
        self.setMaximumHeight(170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setObjectName("timeDomainPlot")
        self._samples: list[tuple[float, float, float, float]] = []

    def set_samples(self, samples: list[tuple[float, float, float, float]]) -> None:
        self._samples = list(samples)
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0f172a"))

        plot = QRectF(self.rect()).adjusted(54.0, 28.0, -18.0, -38.0)
        if plot.width() <= 8 or plot.height() <= 8:
            return

        grid_pen = QPen(QColor(51, 65, 85, 140), 1.0)
        painter.setPen(grid_pen)
        for step in range(4):
            y = plot.top() + plot.height() * step / 3
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        for step in range(4):
            x = plot.left() + plot.width() * step / 3
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))

        painter.setPen(QPen(QColor("#475569"), 1.0))
        painter.drawRect(plot)

        font = QFont(self.font())
        point_size = font.pointSize()
        font.setPointSize(point_size if point_size > 0 else 8)
        painter.setFont(font)

        samples = self._samples[-FIELD_PLOT_VISIBLE_SAMPLES:]
        if samples:
            cutoff = samples[-1][0] - FIELD_PLOT_VISIBLE_SECONDS
            samples = [sample for sample in samples if sample[0] >= cutoff]
        if samples:
            start = samples[0][0]
            end = max(samples[-1][0], start + 1.0)
        else:
            start = 0.0
            end = 16.8

        values = [0.0]
        for _, actual, target, error in samples:
            values.extend([actual, target, error])
        lower = min(values)
        upper = max(values)
        if math.isclose(lower, upper, abs_tol=0.001):
            lower -= 1.0
            upper += 1.0
        padding = max(0.5, (upper - lower) * 0.12)
        lower -= padding
        upper += padding

        axis_color = QColor("#cbd5e1")
        painter.setPen(axis_color)
        for step in range(4):
            t = start + (end - start) * step / 3
            x = plot.left() + plot.width() * step / 3
            y_value = upper - (upper - lower) * step / 3
            y = plot.top() + plot.height() * step / 3
            painter.drawText(QRectF(plot.left() - 52, y - 9, 44, 18), Qt.AlignRight | Qt.AlignVCenter, f"{y_value:.0f}")
            painter.drawText(QRectF(x - 30, plot.bottom() + 8, 60, 18), Qt.AlignCenter, f"{t - start:.1f}")
        painter.drawText(QRectF(plot.center().x() - 60, plot.bottom() + 26, 120, 18), Qt.AlignCenter, "Time (s)")

        self._draw_trace(painter, plot, samples, start, end, lower, upper, 1, QColor("#60a5fa"))
        self._draw_trace(painter, plot, samples, start, end, lower, upper, 2, QColor("#22c55e"))
        self._draw_trace(painter, plot, samples, start, end, lower, upper, 3, QColor("#f59e0b"))
        self._draw_legend(painter, plot)

    def _point_for(
        self,
        plot: QRectF,
        sample: tuple[float, float, float, float],
        start: float,
        end: float,
        lower: float,
        upper: float,
        value_index: int,
    ) -> QPointF:
        x_ratio = (sample[0] - start) / max(0.001, end - start)
        y_ratio = (sample[value_index] - lower) / max(0.001, upper - lower)
        return QPointF(
            plot.left() + plot.width() * x_ratio,
            plot.bottom() - plot.height() * y_ratio,
        )

    def _draw_trace(
        self,
        painter: QPainter,
        plot: QRectF,
        samples: list[tuple[float, float, float, float]],
        start: float,
        end: float,
        lower: float,
        upper: float,
        value_index: int,
        color: QColor,
    ) -> None:
        if len(samples) < 2:
            return
        painter.setPen(QPen(color, 1.5))
        previous = self._point_for(plot, samples[0], start, end, lower, upper, value_index)
        for sample in samples[1:]:
            current = self._point_for(plot, sample, start, end, lower, upper, value_index)
            painter.drawLine(previous, current)
            previous = current

    def _draw_legend(self, painter: QPainter, plot: QRectF) -> None:
        items = (
            ("Actual", QColor("#60a5fa")),
            ("Target", QColor("#22c55e")),
            ("Error", QColor("#f59e0b")),
        )
        x = plot.right() - 280
        y = plot.top() - 22
        for label, color in items:
            painter.setPen(QPen(color, 1.5))
            painter.drawLine(QPointF(x, y + 8), QPointF(x + 18, y + 8))
            painter.setPen(QColor("#cbd5e1"))
            painter.drawText(QRectF(x + 28, y, 58, 18), Qt.AlignLeft | Qt.AlignVCenter, label)
            x += 94


class SimulatedActual:
    def __init__(self) -> None:
        self.value = 0.0

    def step(self, target: float) -> float:
        self.value += (target - self.value) * 0.08
        self.value += math.sin(self.value * 0.03) * 0.015
        return clamp(self.value)


def make_speedometer(parent: QWidget | None = None) -> QWidget:
    try:
        import CycloViz

        if hasattr(CycloViz, "MagneticFieldSpeedometer") and hasattr(CycloViz, "load_opengl"):
            return NativeSpeedometer(parent)
        return MissingNativeSpeedometer("CycloViz is missing MagneticFieldSpeedometer/load_opengl.", parent)
    except Exception as exc:
        return MissingNativeSpeedometer(str(exc), parent)


def make_time_domain_plot(parent: QWidget | None = None) -> QWidget:
    return QtTimeDomainPlot(parent)
