# -*- coding: utf-8 -*-
"""PID/GA-local Tesla trend plot with numeric x/y axes.

This module intentionally lives beside ``pid_ga_control_tab.py`` so adding
scientific tick labels to the PID and GA plots does not modify the shared
``controller_theme.py`` used by the rest of the control-system GUI.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import QWidget

from controller_theme import T


# Time-series plots show only the latest two minutes.  Change this single
# constant if a different history length is preferred.
DEFAULT_TIME_WINDOW_S = 120.0
DEFAULT_MAX_DISPLAY_POINTS = 600


class AxisTrendPlot(QWidget):
    """Tesla-style trend with two required series and one optional overlay.

    The public API remains backward compatible with the original two-series
    ``TrendPlot``: existing callers may keep using ``set_data(x, target, actual)``.
    A fourth ``third_data`` argument can be supplied when a diagnostic overlay
    is useful (for example raw beam current plus its live moving average).
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        y_axis_label: str = "CURRENT (A)",
        x_axis_label: str = "TIME (s)",
        target_color: str = T.cyan,
        actual_color: str = T.orange,
        third_color: str | None = None,
        x_tick_count: int = 6,
        y_tick_count: int = 5,
        rolling_window_s: float | None = None,
        relative_time: bool | None = None,
        max_display_points: int = DEFAULT_MAX_DISPLAY_POINTS,
    ):
        super().__init__(parent)
        self.x_data: list[float] = []
        self.target_data: list[float] = []
        self.actual_data: list[float] = []
        self.third_data: list[float] = []
        self.y_axis_label = str(y_axis_label)
        self.x_axis_label = str(x_axis_label)
        self.target_color = QColor(target_color)
        self.actual_color = QColor(actual_color)
        self.third_color = QColor(third_color) if third_color is not None else QColor(T.green)
        self.x_tick_count = max(3, int(x_tick_count))
        self.y_tick_count = max(3, int(y_tick_count))

        # Every plot whose horizontal label contains TIME automatically uses a
        # rolling history.  The newest sample is displayed at 0 s, so a long
        # PID run never produces axes such as 0...4000 s with the data squeezed
        # into a small area at the right.  Non-time plots (for example GA
        # fitness versus EVALUATION) keep their normal absolute x axis.
        self._is_time_axis = "TIME" in self.x_axis_label.upper()
        if rolling_window_s is None:
            rolling_window_s = DEFAULT_TIME_WINDOW_S if self._is_time_axis else 0.0
        self.rolling_window_s = max(0.0, float(rolling_window_s))
        if relative_time is None:
            relative_time = self._is_time_axis
        self.relative_time = bool(relative_time and self._is_time_axis)
        self.max_display_points = max(50, int(max_display_points))
        self._display_x_axis_label = (
            "TIME (s; 0 = latest)" if self.relative_time else self.x_axis_label
        )
        self.setMinimumHeight(140)

    def clear(self) -> None:
        self.x_data.clear()
        self.target_data.clear()
        self.actual_data.clear()
        self.third_data.clear()
        self.update()

    def set_data(
        self,
        x_data: Sequence[float] | Iterable[float],
        target_data: Sequence[float] | Iterable[float],
        actual_data: Sequence[float] | Iterable[float],
        third_data: Sequence[float] | Iterable[float] | None = None,
    ) -> None:
        x = list(x_data)
        target = list(target_data)
        actual = list(actual_data)
        third = None if third_data is None else list(third_data)

        if third is None:
            n = min(len(x), len(target), len(actual))
        else:
            n = min(len(x), len(target), len(actual), len(third))

        filtered: list[tuple[float, ...]] = []
        for i in range(n):
            try:
                values = [float(x[i]), float(target[i]), float(actual[i])]
                if third is not None:
                    values.append(float(third[i]))
            except (TypeError, ValueError):
                continue
            if all(math.isfinite(value) for value in values):
                filtered.append(tuple(values))

        if filtered and self._is_time_axis and self.rolling_window_s > 0.0:
            newest_time = filtered[-1][0]
            cutoff = newest_time - self.rolling_window_s
            filtered = [row for row in filtered if row[0] >= cutoff]
            if self.relative_time:
                # Shift the retained history so the newest point is always 0 s.
                # This produces a scrolling axis such as -120...0 s.
                filtered = [
                    (row[0] - newest_time, *row[1:]) for row in filtered
                ]

        # Painting more points than the plot has horizontal pixels adds GUI
        # work without improving what the operator can see.  Keep the first and
        # last samples and select evenly spaced intermediate samples.
        if len(filtered) > self.max_display_points:
            last = len(filtered) - 1
            indices = {
                round(i * last / (self.max_display_points - 1))
                for i in range(self.max_display_points)
            }
            filtered = [filtered[i] for i in sorted(indices)]

        self.x_data = [row[0] for row in filtered]
        self.target_data = [row[1] for row in filtered]
        self.actual_data = [row[2] for row in filtered]
        self.third_data = [row[3] for row in filtered] if third is not None else []
        self.update()

    @staticmethod
    def _nice_number(value: float, *, round_value: bool) -> float:
        value = abs(float(value))
        if not math.isfinite(value) or value <= 0.0:
            return 1.0
        exponent = math.floor(math.log10(value))
        fraction = value / (10.0**exponent)
        if round_value:
            if fraction < 1.5:
                nice_fraction = 1.0
            elif fraction < 3.0:
                nice_fraction = 2.0
            elif fraction < 7.0:
                nice_fraction = 5.0
            else:
                nice_fraction = 10.0
        else:
            if fraction <= 1.0:
                nice_fraction = 1.0
            elif fraction <= 2.0:
                nice_fraction = 2.0
            elif fraction <= 5.0:
                nice_fraction = 5.0
            else:
                nice_fraction = 10.0
        return nice_fraction * (10.0**exponent)

    @classmethod
    def _nice_axis(
        cls,
        lower: float,
        upper: float,
        requested_ticks: int,
    ) -> tuple[float, float, float]:
        lower = float(lower)
        upper = float(upper)
        if not all(math.isfinite(value) for value in (lower, upper)):
            return 0.0, 1.0, 0.2
        if upper < lower:
            lower, upper = upper, lower
        if math.isclose(lower, upper, rel_tol=0.0, abs_tol=1e-15):
            pad = max(1.0, abs(lower) * 0.10)
            lower -= pad
            upper += pad
        span = cls._nice_number(upper - lower, round_value=False)
        step = cls._nice_number(
            span / max(2, requested_ticks - 1), round_value=True
        )
        axis_min = math.floor(lower / step) * step
        axis_max = math.ceil(upper / step) * step
        if math.isclose(axis_min, axis_max, rel_tol=0.0, abs_tol=1e-15):
            axis_max = axis_min + step
        return axis_min, axis_max, step

    @classmethod
    def _relative_time_axis(
        cls,
        lower: float,
        requested_ticks: int,
    ) -> tuple[float, float, float]:
        """Return a clean rolling time axis ending exactly at 0 seconds."""
        span = max(1.0, abs(float(lower)))
        step = cls._nice_number(
            span / max(2, requested_ticks - 1), round_value=True
        )
        intervals = max(1, math.ceil(span / step))
        return -float(intervals) * step, 0.0, step

    @staticmethod
    def _tick_values(lower: float, upper: float, step: float) -> list[float]:
        if step <= 0.0 or not all(math.isfinite(v) for v in (lower, upper, step)):
            return [lower, upper]
        values: list[float] = []
        value = lower
        # Floating-point guard. A normal axis should contain fewer than 20 ticks.
        for _ in range(30):
            if value > upper + step * 0.25:
                break
            values.append(0.0 if abs(value) < step * 1e-10 else value)
            value += step
        if not values:
            return [lower, upper]
        return values

    @staticmethod
    def _format_tick(value: float, step: float) -> str:
        value = 0.0 if abs(value) < max(1e-15, abs(step) * 1e-10) else value
        magnitude = abs(value)
        if magnitude >= 10000.0 or (0.0 < magnitude < 0.001):
            return f"{value:.2e}"
        if step >= 10.0:
            decimals = 0
        elif step >= 1.0:
            decimals = 1
        elif step >= 0.1:
            decimals = 2
        elif step >= 0.01:
            decimals = 3
        elif step >= 0.001:
            decimals = 4
        else:
            decimals = 5
        return f"{value:.{decimals}f}"

    def _raw_bounds(self) -> tuple[float, float, float, float]:
        if len(self.x_data) < 2:
            if self.relative_time:
                return -1.0, 0.0, 0.0, 1.0
            return 0.0, 1.0, 0.0, 1.0

        x_min = min(self.x_data)
        x_max = max(self.x_data)
        # Only the GA evaluation axis is intentionally anchored at zero.
        # Time histories are already shifted to a rolling -window...0 domain.
        if not self.relative_time and "EVALUATION" in self.x_axis_label.upper():
            x_min = min(0.0, x_min)

        values = self.target_data + self.actual_data
        if self.third_data:
            values += self.third_data
        y_min = min(values)
        y_max = max(values)
        if math.isclose(y_min, y_max, rel_tol=0.0, abs_tol=1e-15):
            pad = max(0.01, abs(y_max) * 0.08, 1.0 if y_max == 0.0 else 0.0)
            y_min -= pad
            y_max += pad
        else:
            pad = 0.08 * (y_max - y_min)
            y_min -= pad
            y_max += pad

        label_upper = self.y_axis_label.upper()
        if y_min >= 0.0 and (
            "ERROR" in label_upper
            or "FITNESS" in label_upper
            or y_min <= 0.20 * max(y_max, 1e-12)
        ):
            y_min = 0.0
        return x_min, x_max, y_min, y_max

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(T.panel))

        # Extra left/bottom space is reserved for numeric tick values and labels.
        left, top, right, bottom = 78, 12, 16, 48
        plot_rect = self.rect().adjusted(left, top, -right, -bottom)
        if plot_rect.width() <= 20 or plot_rect.height() <= 20:
            return

        raw_x_min, raw_x_max, raw_y_min, raw_y_max = self._raw_bounds()
        if self.relative_time:
            x_min, x_max, x_step = self._relative_time_axis(
                raw_x_min, self.x_tick_count
            )
        else:
            x_min, x_max, x_step = self._nice_axis(
                raw_x_min, raw_x_max, self.x_tick_count
            )
        y_min, y_max, y_step = self._nice_axis(
            raw_y_min, raw_y_max, self.y_tick_count
        )
        x_ticks = self._tick_values(x_min, x_max, x_step)
        y_ticks = self._tick_values(y_min, y_max, y_step)

        def map_x(value: float) -> float:
            return plot_rect.left() + (value - x_min) / (x_max - x_min) * plot_rect.width()

        def map_y(value: float) -> float:
            return plot_rect.bottom() - (value - y_min) / (y_max - y_min) * plot_rect.height()

        # Grid and numeric ticks.
        painter.setFont(QFont("Segoe UI", 8))
        grid_pen = QPen(QColor(39, 50, 58, 135), 1)
        tick_pen = QColor(T.muted)

        for value in x_ticks:
            x = map_x(value)
            painter.setPen(grid_pen)
            painter.drawLine(int(x), plot_rect.top(), int(x), plot_rect.bottom())
            painter.setPen(tick_pen)
            text = self._format_tick(value, x_step)
            painter.drawText(
                int(x - 34),
                plot_rect.bottom() + 5,
                68,
                16,
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                text,
            )

        for value in y_ticks:
            y = map_y(value)
            painter.setPen(grid_pen)
            painter.drawLine(plot_rect.left(), int(y), plot_rect.right(), int(y))
            painter.setPen(tick_pen)
            text = self._format_tick(value, y_step)
            painter.drawText(
                24,
                int(y - 8),
                left - 30,
                16,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                text,
            )

        painter.setPen(QPen(QColor(T.border), 1))
        painter.drawLine(plot_rect.bottomLeft(), plot_rect.bottomRight())
        painter.drawLine(plot_rect.bottomLeft(), plot_rect.topLeft())

        painter.setPen(QColor(T.muted))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        painter.drawText(
            plot_rect.left(),
            self.height() - 19,
            plot_rect.width(),
            16,
            int(Qt.AlignmentFlag.AlignCenter),
            self._display_x_axis_label,
        )
        painter.save()
        painter.translate(12, plot_rect.center().y())
        painter.rotate(-90)
        painter.drawText(
            -plot_rect.height() // 2,
            0,
            plot_rect.height(),
            16,
            int(Qt.AlignmentFlag.AlignCenter),
            self.y_axis_label,
        )
        painter.restore()

        if len(self.x_data) < 2:
            return

        def map_point(x_value: float, y_value: float) -> QPointF:
            return QPointF(map_x(x_value), map_y(y_value))

        def make_path(series: Sequence[float]) -> QPainterPath:
            path = QPainterPath()
            path.moveTo(map_point(self.x_data[0], series[0]))
            for x_value, y_value in zip(self.x_data[1:], series[1:]):
                path.lineTo(map_point(x_value, y_value))
            return path

        target_path = make_path(self.target_data)
        actual_path = make_path(self.actual_data)
        third_path = make_path(self.third_data) if self.third_data else None

        # Preserve the original filled measured-response appearance for normal
        # two-series plots.  When a third overlay is present (raw + averaged beam),
        # keep the raw trace visually lighter so the averaged trace is easy to see.
        if third_path is None:
            actual_fill = QPainterPath(actual_path)
            actual_fill.lineTo(map_point(self.x_data[-1], y_min))
            actual_fill.lineTo(map_point(self.x_data[0], y_min))
            actual_fill.closeSubpath()

            base = self.actual_color
            fill_gradient = QLinearGradient(0, plot_rect.top(), 0, plot_rect.bottom())
            fill_gradient.setColorAt(0.00, QColor(base.red(), base.green(), base.blue(), 145))
            fill_gradient.setColorAt(0.42, QColor(base.red(), base.green(), base.blue(), 90))
            fill_gradient.setColorAt(0.78, QColor(base.red(), base.green(), base.blue(), 35))
            fill_gradient.setColorAt(1.00, QColor(base.red(), base.green(), base.blue(), 5))
            painter.fillPath(actual_fill, fill_gradient)

            painter.setPen(
                QPen(
                    QColor(base.red(), base.green(), base.blue(), 45),
                    9,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.drawPath(actual_path)

        painter.setPen(
            QPen(
                self.target_color,
                2,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.drawPath(target_path)

        raw_color = self.actual_color
        if third_path is not None:
            raw_color = QColor(
                self.actual_color.red(),
                self.actual_color.green(),
                self.actual_color.blue(),
                170,
            )
        painter.setPen(
            QPen(
                raw_color,
                1.5 if third_path is not None else 2,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.drawPath(actual_path)

        if third_path is not None:
            # The moving average is the diagnostic trace the operator wants to
            # compare with the noisy raw measurement, so give it the strongest line.
            painter.setPen(
                QPen(
                    QColor(
                        self.third_color.red(),
                        self.third_color.green(),
                        self.third_color.blue(),
                        50,
                    ),
                    7,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.drawPath(third_path)
            painter.setPen(
                QPen(
                    self.third_color,
                    2.5,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.drawPath(third_path)

        endpoint = map_point(self.x_data[-1], self.actual_data[-1])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.actual_color)
        painter.drawEllipse(endpoint, 3.5, 3.5)

        if third_path is not None:
            average_endpoint = map_point(self.x_data[-1], self.third_data[-1])
            painter.setBrush(self.third_color)
            painter.drawEllipse(average_endpoint, 4.0, 4.0)


__all__ = [
    "AxisTrendPlot",
    "DEFAULT_TIME_WINDOW_S",
    "DEFAULT_MAX_DISPLAY_POINTS",
]
