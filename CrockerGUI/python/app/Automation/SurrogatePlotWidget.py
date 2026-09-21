from __future__ import annotations

import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QFont
from PySide6.QtWidgets import QSizePolicy, QWidget

from source.Python.Optimization.pid_gain_adapter import PidGainCandidate, PidTrialResult
from python.app.widgets.PlotSurface import PlotSurface


class SurrogatePlotWidget(PlotSurface):
    """Cost versus one gain, with a posterior band from the full 3D GP."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._grid: dict | None = None
        self._results: list[PidTrialResult] = []
        self._candidate: PidGainCandidate | None = None
        self._best: PidTrialResult | None = None
        self._axis = "kp"
        self.setObjectName("pidSurrogatePlot")
        self.setMinimumHeight(300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAccessibleName("Gaussian process cost mean and 95 percent posterior interval")
        self.setToolTip('The curve holds the other gains fixed. Stars share those fixed gains; '
                        'hollow points come from other gain combinations. The band is uncertainty in mean cost, '
                        'not a guarantee of the next trial result. The dashed line projects the next candidate onto this gain.')

    def set_state(self, *, grid: dict | None, results: list[PidTrialResult],
                  candidate: PidGainCandidate | None, best: PidTrialResult | None,
                  axis_x: str = "kp") -> None:
        self._axis = axis_x
        self._grid = grid if grid and grid.get("axis_x") == axis_x else None
        self._results = list(results)
        self._candidate, self._best = candidate, best
        self.update()

    @staticmethod
    def _star(center: QPointF, radius: float = 7.0) -> QPainterPath:
        path = QPainterPath()
        for index in range(10):
            angle = -math.pi / 2 + index * math.pi / 5
            distance = radius if index % 2 == 0 else radius * 0.45
            vertex = center + QPointF(math.cos(angle) * distance, math.sin(angle) * distance)
            if index == 0:
                path.moveTo(vertex)
            else:
                path.lineTo(vertex)
        path.closeSubpath()
        return path

    def _on_slice(self, candidate: PidGainCandidate) -> bool:
        fixed = (self._grid or {}).get("fixed_values", {})
        return bool(fixed) and all(math.isclose(getattr(candidate, name), value,
                                               rel_tol=1e-7, abs_tol=1e-9)
                                   for name, value in fixed.items())

    @staticmethod
    def _bounds(values, default=(0.0, 1.0)):
        finite = [float(v) for v in values if math.isfinite(v)]
        if not finite:
            return default
        low, high = min(finite), max(finite)
        padding = max((high - low) * 0.08, 0.1 if low == high else 1e-9)
        return low - padding, high + padding

    def paint_chart(self, event) -> None:
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(QFont('Segoe UI', 9))
        p.fillRect(self.rect(), QColor("#0f172a"))
        p.setPen(QColor("#e5e7eb"))
        p.drawText(QRectF(16, 8, self.width()-32, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   f"Gaussian process: cost vs {self._axis.capitalize()}")
        grid = self._grid or {}
        fixed = grid.get("fixed_values", {})
        fixed_text = "  |  ".join(f"{name.capitalize()} = {value:.4g}" for name, value in fixed.items())
        p.setPen(QColor("#94a3b8"))
        p.drawText(QRectF(16, 31, self.width()-32, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   f"Fixed at best safe trial (or midpoints): {fixed_text}" if fixed else "Preparing slice; other gains will be held fixed")
        x, y = 16, 62
        for kind, label, color in [('line', 'Predicted mean', '#fb923c'),
                                   ('band', '95% posterior interval', '#fb923c'),
                                   ('star', 'Trials on slice', '#60a5fa'),
                                   ('hollow', 'Other trials (projected)', '#60a5fa'),
                                   ('dash', 'Next candidate', '#c4b5fd')]:
            width = p.fontMetrics().horizontalAdvance(label) + 58
            if x + width > self.width()-16 and x > 16:
                x, y = 16, y+28
            p.setPen(QPen(QColor(color), 2, Qt.DashLine if kind == 'dash' else Qt.SolidLine))
            p.setBrush(Qt.NoBrush)
            if kind in ('line', 'dash'):
                p.drawLine(QPointF(x, y+8), QPointF(x+24, y+8))
            elif kind == 'band':
                p.fillRect(QRectF(x, y+1, 24, 14), QColor(251, 146, 60, 70))
            elif kind == 'star':
                p.setBrush(QColor(color))
                p.drawPath(self._star(QPointF(x+12, y+8)))
            else:
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(x+12, y+8), 4.5, 4.5)
            p.setPen(QColor('#cbd5e1'))
            p.drawText(QRectF(x+32, y-2, width-32, 22), Qt.AlignVCenter, label)
            x += width
        plot = QRectF(self.rect()).adjusted(82, y+36, -24, -66)
        if plot.width() < 20 or plot.height() < 20:
            return
        safe = [r for r in self._results if math.isfinite(r.score)
                and math.isfinite(getattr(r.candidate, self._axis))]
        xs = grid.get("x_values", [])
        ready = bool(grid.get("ready"))
        x_bounds = (xs[0], xs[-1]) if len(xs) >= 2 else self._bounds(
            [getattr(r.candidate, self._axis) for r in safe]
            + ([getattr(self._candidate, self._axis)] if self._candidate else []))
        visible = safe
        y_bounds = self._bounds([r.score for r in visible]
                                + (grid["lower"] + grid["upper"] if ready else []))

        def point(x, y):
            return QPointF(plot.left() + (x-x_bounds[0]) / max(1e-12, x_bounds[1]-x_bounds[0]) * plot.width(),
                           plot.bottom() - (y-y_bounds[0]) / max(1e-12, y_bounds[1]-y_bounds[0]) * plot.height())

        p.fillRect(plot, QColor("#111827"))
        for i in range(5):
            ratio = i/4
            x = x_bounds[0] + ratio * (x_bounds[1]-x_bounds[0])
            y = y_bounds[0] + ratio * (y_bounds[1]-y_bounds[0])
            px, py = point(x, y_bounds[0]).x(), point(x_bounds[0], y).y()
            p.setPen(QPen(QColor("#273449"), 1))
            p.drawLine(QPointF(px, plot.top()), QPointF(px, plot.bottom()))
            p.drawLine(QPointF(plot.left(), py), QPointF(plot.right(), py))
            p.setPen(QColor("#cbd5e1"))
            p.drawText(QRectF(px-40, plot.bottom()+7, 80, 18), Qt.AlignCenter, f"{x:.3g}")
            p.drawText(QRectF(12, py-9, 62, 18), Qt.AlignRight | Qt.AlignVCenter, f"{y:.3g}")
        p.drawText(QRectF(plot.left(), plot.bottom()+28, plot.width(), 18), Qt.AlignCenter, self._axis.capitalize())
        p.save()
        p.translate(12, plot.center().y())
        p.rotate(-90)
        p.drawText(QRectF(-plot.height()/2, -10, plot.height(), 18), Qt.AlignCenter, "Cost (lower is better)")
        p.restore()
        p.save()
        p.setClipRect(plot)
        if ready:
            band = QPainterPath(point(xs[0], grid["upper"][0]))
            for x, y in zip(xs[1:], grid["upper"][1:]): band.lineTo(point(x, y))
            for x, y in zip(reversed(xs), reversed(grid["lower"])): band.lineTo(point(x, y))
            band.closeSubpath()
            p.fillPath(band, QColor(251, 146, 60, 70))
            curve = QPainterPath(point(xs[0], grid["mean"][0]))
            for x, y in zip(xs[1:], grid["mean"][1:]): curve.lineTo(point(x, y))
            p.setPen(QPen(QColor("#fb923c"), 2.2))
            p.drawPath(curve)
        for result in visible:
            xy = point(getattr(result.candidate, self._axis), result.score)
            p.setPen(QPen(QColor("#60a5fa"), 1.7))
            if self._on_slice(result.candidate):
                p.setBrush(QColor("#60a5fa"))
                p.drawPath(self._star(xy))
            else:
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(xy, 4.5, 4.5)
        if self._candidate is not None:
            px = point(getattr(self._candidate, self._axis), y_bounds[0]).x()
            p.setPen(QPen(QColor("#c4b5fd"), 1.3, Qt.DashLine))
            p.drawLine(QPointF(px, plot.top()), QPointF(px, plot.bottom()))
        if not ready:
            p.setPen(QColor("#e5e7eb"))
            p.drawText(plot.adjusted(10, 5, -10, -5), Qt.AlignCenter,
                       grid.get("message", "Waiting for safe trials to fit the Gaussian process"))
        p.restore()
        p.setPen(QPen(QColor("#475569"), 1))
        p.drawRect(plot)
        p.setPen(QColor("#94a3b8"))
        excluded = len(self._results) - len(safe)
        p.drawText(QRectF(16, self.height()-21, self.width()-32, 18), Qt.AlignLeft,
                   f"Trials without plottable values: {excluded}   ·   Hover for interpretation")
