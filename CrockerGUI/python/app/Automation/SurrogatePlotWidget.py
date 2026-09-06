from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from source.Python.Optimization.pid_gain_adapter import (
    PidGainCandidate,
    PidTrialResult,
)


class SurrogatePlotWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._grid: dict | None = None
        self._results: list[PidTrialResult] = []
        self._candidate: PidGainCandidate | None = None
        self._best: PidTrialResult | None = None
        self.setObjectName("pidSurrogatePlot")
        self.setMinimumHeight(280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_state(
        self,
        *,
        grid: dict | None,
        results: list[PidTrialResult],
        candidate: PidGainCandidate | None,
        best: PidTrialResult | None,
    ) -> None:
        self._grid = grid
        self._results = list(results)
        self._candidate = candidate
        self._best = best
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0f172a"))

        plot = QRectF(self.rect()).adjusted(58.0, 42.0, -24.0, -48.0)
        self._draw_title(painter)
        if plot.width() <= 8 or plot.height() <= 8:
            return

        grid = self._grid
        if grid and grid.get("ready"):
            self._draw_heatmap(painter, plot, grid)
            x_values = grid["x_values"]
            y_values = grid["y_values"]
            x_bounds = (float(x_values[0]), float(x_values[-1]))
            y_bounds = (float(y_values[0]), float(y_values[-1]))
        else:
            self._draw_empty_surface(painter, plot)
            x_bounds, y_bounds = self._bounds_from_results()
            message = "Waiting for safe observations"
            if grid and grid.get("message"):
                message = str(grid["message"])
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(plot, Qt.AlignCenter, message)

        self._draw_axes(painter, plot, x_bounds, y_bounds)
        self._draw_trials(painter, plot, x_bounds, y_bounds)
        self._draw_marker(painter, plot, x_bounds, y_bounds, self._candidate, QColor("#f59e0b"), 7.0)
        if self._best is not None:
            self._draw_marker(painter, plot, x_bounds, y_bounds, self._best.candidate, QColor("#22c55e"), 8.5)
        self._draw_legend(painter, plot)

    def _draw_title(self, painter: QPainter) -> None:
        font = QFont(self.font())
        point_size = font.pointSize()
        font.setPointSize(point_size if point_size > 0 else 9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#e5e7eb"))
        painter.drawText(
            QRectF(16.0, 10.0, self.width() - 32.0, 22.0),
            Qt.AlignLeft | Qt.AlignVCenter,
            "Surrogate Model: Kp / Ki Cost Slice",
        )

    def _draw_heatmap(self, painter: QPainter, plot: QRectF, grid: dict) -> None:
        mean = grid["mean"]
        stddev = grid["stddev"]
        flat_mean = [float(value) for row in mean for value in row]
        flat_stddev = [float(value) for row in stddev for value in row]
        low = min(flat_mean)
        high = max(flat_mean)
        uncertainty_high = max(flat_stddev) if flat_stddev else 0.0
        rows = len(mean)
        columns = len(mean[0]) if rows else 0
        if rows <= 0 or columns <= 0:
            return
        cell_width = plot.width() / columns
        cell_height = plot.height() / rows
        for row_index, row in enumerate(mean):
            for column_index, value in enumerate(row):
                uncertainty = float(stddev[row_index][column_index])
                color = self._cost_color(float(value), low, high)
                if uncertainty_high > 0.0:
                    color = self._mix(color, QColor("#e5e7eb"), min(0.32, 0.24 * uncertainty / uncertainty_high))
                rect = QRectF(
                    plot.left() + column_index * cell_width,
                    plot.bottom() - (row_index + 1) * cell_height,
                    cell_width + 0.6,
                    cell_height + 0.6,
                )
                painter.fillRect(rect, color)

    def _draw_empty_surface(self, painter: QPainter, plot: QRectF) -> None:
        painter.fillRect(plot, QColor("#111827"))
        painter.setPen(QPen(QColor(51, 65, 85, 120), 1.0))
        for step in range(6):
            x = plot.left() + plot.width() * step / 5
            y = plot.top() + plot.height() * step / 5
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

    def _draw_axes(
        self,
        painter: QPainter,
        plot: QRectF,
        x_bounds: tuple[float, float],
        y_bounds: tuple[float, float],
    ) -> None:
        painter.setPen(QPen(QColor("#475569"), 1.0))
        painter.drawRect(plot)
        painter.setPen(QColor("#cbd5e1"))
        for step in range(4):
            amount = step / 3
            x = plot.left() + plot.width() * amount
            y = plot.bottom() - plot.height() * amount
            kp = x_bounds[0] + (x_bounds[1] - x_bounds[0]) * amount
            ki = y_bounds[0] + (y_bounds[1] - y_bounds[0]) * amount
            painter.drawText(QRectF(x - 34.0, plot.bottom() + 8.0, 68.0, 18.0), Qt.AlignCenter, f"{kp:.2g}")
            painter.drawText(QRectF(plot.left() - 52.0, y - 9.0, 44.0, 18.0), Qt.AlignRight | Qt.AlignVCenter, f"{ki:.2g}")
        painter.drawText(QRectF(plot.left(), plot.bottom() + 28.0, plot.width(), 18.0), Qt.AlignCenter, "Kp")
        painter.drawText(QRectF(plot.left() - 56.0, plot.center().y() - 24.0, 18.0, 48.0), Qt.AlignCenter, "Ki")

    def _draw_trials(
        self,
        painter: QPainter,
        plot: QRectF,
        x_bounds: tuple[float, float],
        y_bounds: tuple[float, float],
    ) -> None:
        safe_scores = [result.score for result in self._results if result.safe]
        low = min(safe_scores) if safe_scores else 0.0
        high = max(safe_scores) if safe_scores else 1.0
        for result in self._results:
            point = self._point(plot, x_bounds, y_bounds, result.candidate)
            color = self._cost_color(result.score, low, high) if result.safe else QColor("#ef4444")
            painter.setPen(QPen(QColor("#0f172a"), 1.5))
            painter.setBrush(color)
            painter.drawEllipse(point, 5.2, 5.2)

    def _draw_marker(
        self,
        painter: QPainter,
        plot: QRectF,
        x_bounds: tuple[float, float],
        y_bounds: tuple[float, float],
        candidate: PidGainCandidate | None,
        color: QColor,
        radius: float,
    ) -> None:
        if candidate is None:
            return
        point = self._point(plot, x_bounds, y_bounds, candidate)
        painter.setPen(QPen(color, 2.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(point, radius, radius)
        painter.drawLine(QPointF(point.x() - radius - 3, point.y()), QPointF(point.x() + radius + 3, point.y()))
        painter.drawLine(QPointF(point.x(), point.y() - radius - 3), QPointF(point.x(), point.y() + radius + 3))

    def _draw_legend(self, painter: QPainter, plot: QRectF) -> None:
        best_text = "Best: none" if self._best is None else f"Best: {self._best.score:.3g}"
        candidate_text = "Candidate: none" if self._candidate is None else (
            f"Candidate: Kp {self._candidate.kp:.3g}, Ki {self._candidate.ki:.3g}, Kd {self._candidate.kd:.3g}"
        )
        painter.setPen(QColor("#cbd5e1"))
        painter.drawText(
            QRectF(plot.left(), 16.0, plot.width(), 18.0),
            Qt.AlignRight | Qt.AlignVCenter,
            f"{best_text}    {candidate_text}",
        )

    def _bounds_from_results(self) -> tuple[tuple[float, float], tuple[float, float]]:
        kp_values = [result.candidate.kp for result in self._results]
        ki_values = [result.candidate.ki for result in self._results]
        if self._candidate is not None:
            kp_values.append(self._candidate.kp)
            ki_values.append(self._candidate.ki)
        return self._padded_bounds(kp_values, 0.0, 5.0), self._padded_bounds(ki_values, 0.0, 2.0)

    def _point(
        self,
        plot: QRectF,
        x_bounds: tuple[float, float],
        y_bounds: tuple[float, float],
        candidate: PidGainCandidate,
    ) -> QPointF:
        x_ratio = (candidate.kp - x_bounds[0]) / max(1.0e-9, x_bounds[1] - x_bounds[0])
        y_ratio = (candidate.ki - y_bounds[0]) / max(1.0e-9, y_bounds[1] - y_bounds[0])
        return QPointF(
            plot.left() + plot.width() * max(0.0, min(1.0, x_ratio)),
            plot.bottom() - plot.height() * max(0.0, min(1.0, y_ratio)),
        )

    @staticmethod
    def _padded_bounds(values: list[float], default_low: float, default_high: float) -> tuple[float, float]:
        if not values:
            return default_low, default_high
        low = min(values)
        high = max(values)
        if abs(high - low) < 1.0e-9:
            return low - 0.5, high + 0.5
        padding = (high - low) * 0.18
        return low - padding, high + padding

    @staticmethod
    def _cost_color(value: float, low: float, high: float) -> QColor:
        ratio = 0.0 if high <= low else max(0.0, min(1.0, (value - low) / (high - low)))
        stops = (
            QColor("#22c55e"),
            QColor("#60a5fa"),
            QColor("#f59e0b"),
            QColor("#ef4444"),
        )
        scaled = ratio * (len(stops) - 1)
        left = int(scaled)
        right = min(left + 1, len(stops) - 1)
        return SurrogatePlotWidget._mix(stops[left], stops[right], scaled - left)

    @staticmethod
    def _mix(left: QColor, right: QColor, amount: float) -> QColor:
        amount = max(0.0, min(1.0, amount))
        return QColor(
            round(left.red() + (right.red() - left.red()) * amount),
            round(left.green() + (right.green() - left.green()) * amount),
            round(left.blue() + (right.blue() - left.blue()) * amount),
        )
