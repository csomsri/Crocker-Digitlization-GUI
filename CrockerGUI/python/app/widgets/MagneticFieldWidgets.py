from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QRadialGradient
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QWidget


MAX_GAUGE_VALUE = 1000.0
CHANNEL_NAMES = [f"TC{i}" for i in range(1, 13)] + ["Main Magnet", "Centering Beam"]


def clamp(value: float, lower: float = 0.0, upper: float = MAX_GAUGE_VALUE) -> float:
    return max(lower, min(upper, float(value)))


class BubbleToggle(QPushButton):
    def __init__(self, tooltip: str, color: str = "#4de8ff", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setFixedSize(32, 32)
        self._color = QColor(color)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        radius = min(self.width(), self.height()) * 0.5 - 2
        center = QPointF(self.width() * 0.5, self.height() * 0.5)

        fill = QRadialGradient(center, radius)
        fill.setColorAt(0.0, QColor(44, 58, 73))
        fill.setColorAt(1.0, QColor(6, 12, 22))
        if self.isChecked():
            fill.setColorAt(0.15, QColor(255, 255, 255, 190))
            fill.setColorAt(0.55, QColor(self._color.red(), self._color.green(), self._color.blue(), 165))

        painter.setPen(QPen(self._color, 2 if self.isChecked() else 1))
        painter.setBrush(fill)
        painter.drawEllipse(center, radius, radius)


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
        self.setMinimumSize(360, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._target = 0.0
        self._actual = 0.0
        self._channel = CHANNEL_NAMES[0]
        self._converged = True
        self._error = 0.0
        self._tolerance = 0.5
        self._convergence_seconds = 0.0
        self._timing_active = False
        self._native = None
        self._ready = False
        self._frame_timer = QElapsedTimer()

    def set_values(self, target: float, actual: float, channel: str) -> None:
        self._target = clamp(target)
        self._actual = clamp(actual)
        self._channel = channel
        if self._ready and self._native is not None:
            changed = self._native.set_values(self._target, self._actual, MAX_GAUGE_VALUE, self._channel)
            if not changed:
                return
        if not self._frame_timer.isValid() or self._frame_timer.elapsed() >= 45:
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
            self._native.set_values(self._target, self._actual, MAX_GAUGE_VALUE, self._channel)
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


class TimeDomainPlot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(155)
        self.setMaximumHeight(170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setObjectName("timeDomainPlot")
        self._samples: list[tuple[float, float, float, float]] = []

    def set_samples(self, samples: list[tuple[float, float, float, float]]) -> None:
        self._samples = samples
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        bounds = QRectF(0, 0, self.width(), self.height())
        painter.fillRect(bounds, QColor(0, 0, 0))

        plot = bounds.adjusted(54, 38, -18, -42)
        painter.setPen(QPen(QColor(0, 188, 255, 80), 1))
        painter.drawRect(plot)
        for i in range(1, 4):
            y = plot.top() + plot.height() * i / 4.0
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

        painter.setPen(QColor(202, 239, 255, 180))
        painter.drawText(QRectF(10, 8, 180, 16), Qt.AlignLeft | Qt.AlignVCenter, "Time Response")
        self._draw_legend(painter, plot)

        if len(self._samples) < 2:
            painter.setPen(QColor(202, 239, 255, 120))
            painter.drawText(plot, Qt.AlignCenter, "Waiting for samples")
            return

        values = [value for _, actual, target, error in self._samples for value in (actual, target, error)]
        low = min(values)
        high = max(values)
        if high - low < 1.0:
            low -= 0.5
            high += 0.5

        start = self._samples[0][0]
        end = self._samples[-1][0]
        if end <= start:
            end = start + 1.0
        span = end - start

        def map_point(sample: tuple[float, float, float, float], value: float) -> QPointF:
            x = plot.left() + (sample[0] - start) / span * plot.width()
            y = plot.bottom() - (value - low) / (high - low) * plot.height()
            return QPointF(x, y)

        self._draw_time_axis(painter, plot, span)
        self._draw_series(painter, [map_point(sample, sample[1]) for sample in self._samples], QColor(255, 0, 188))
        self._draw_series(painter, [map_point(sample, sample[2]) for sample in self._samples], QColor(255, 184, 45))
        self._draw_series(painter, [map_point(sample, sample[3]) for sample in self._samples], QColor(255, 62, 62))

        painter.setPen(QColor(202, 239, 255, 150))
        painter.drawText(QRectF(5, plot.top() - 6, 38, 16), Qt.AlignRight | Qt.AlignVCenter, f"{high:.0f}")
        painter.drawText(QRectF(5, plot.bottom() - 10, 38, 16), Qt.AlignRight | Qt.AlignVCenter, f"{low:.0f}")
        painter.drawText(QRectF(plot.left(), bounds.bottom() - 22, plot.width(), 16), Qt.AlignCenter, "Time (s)")

    def _draw_series(self, painter: QPainter, points: list[QPointF], color: QColor) -> None:
        if len(points) < 2:
            return
        painter.setPen(QPen(color, 2))
        painter.drawPolyline(QPolygonF(points))

    def _draw_legend(self, painter: QPainter, plot: QRectF) -> None:
        items = (
            ("Actual", QColor(255, 0, 188)),
            ("Target", QColor(255, 184, 45)),
            ("Error", QColor(255, 62, 62)),
        )
        x = plot.right() - 210
        for label, color in items:
            painter.setPen(QPen(color, 2))
            painter.drawLine(QPointF(x, 16), QPointF(x + 20, 16))
            painter.setPen(QColor(202, 239, 255, 185))
            painter.drawText(QRectF(x + 25, 8, 48, 16), Qt.AlignLeft | Qt.AlignVCenter, label)
            x += 72

    def _draw_time_axis(self, painter: QPainter, plot: QRectF, span: float) -> None:
        step = self._nice_time_step(span)
        painter.setPen(QPen(QColor(0, 188, 255, 70), 1))
        tick = 0.0
        while tick <= span + step * 0.5:
            x = plot.left() + min(tick / span, 1.0) * plot.width()
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setPen(QColor(202, 239, 255, 150))
            painter.drawText(QRectF(x - 22, plot.bottom() + 4, 44, 16), Qt.AlignCenter, f"{tick:g}")
            painter.setPen(QPen(QColor(0, 188, 255, 70), 1))
            tick += step

    def _nice_time_step(self, span: float) -> float:
        if span <= 6.0:
            return 1.0
        rough = span / 4.0
        magnitude = 10 ** math.floor(math.log10(max(rough, 1.0)))
        for multiplier in (1.0, 2.0, 5.0, 10.0):
            step = multiplier * magnitude
            if rough <= step:
                return step
        return 10.0 * magnitude


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
