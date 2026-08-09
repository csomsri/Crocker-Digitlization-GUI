from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QSurfaceFormat
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

        # Offset inner rails give the control a compact cyberpunk HUD profile.
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
