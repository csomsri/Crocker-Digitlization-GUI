# -*- coding: utf-8 -*-
"""Shared Tesla-style widgets and colors for the cyclotron controller GUI."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Iterable, Sequence

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QTabBar, QWidget


@dataclass(frozen=True)
class Theme:
    window: str = "#070B0E"
    panel: str = "#0B1116"
    panel_2: str = "#0D151B"
    border: str = "#27323A"
    border_soft: str = "#1B252C"
    text: str = "#E8EDF0"
    muted: str = "#AAB5BC"
    dim: str = "#74818A"
    cyan: str = "#69BDF7"
    cyan_bright: str = "#78C9FF"
    green: str = "#62E873"
    orange: str = "#F49A28"
    red: str = "#EF5A5A"
    amber: str = "#F4C65A"


T = Theme()


CONTROLLER_QSS = f"""
QWidget {{
    background: {T.window};
    color: {T.text};
    font-family: 'Segoe UI';
    font-size: 13px;
}}
QToolTip {{
    background: #131A20;
    color: {T.text};
    border: 1px solid {T.border};
    padding: 5px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 9px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #34414A;
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QTableWidget {{
    background: #0A1014;
    alternate-background-color: #0C1318;
    border: 1px solid {T.border};
    border-radius: 8px;
    gridline-color: #202B32;
    selection-background-color: #183148;
    selection-color: white;
}}
QHeaderView::section {{
    background: #10171C;
    color: {T.muted};
    border: none;
    border-bottom: 1px solid {T.border};
    padding: 8px;
    font-weight: 600;
}}
QDoubleSpinBox, QSpinBox, QComboBox {{
    background: #0E151A;
    color: {T.text};
    border: 1px solid #3A4851;
    border-radius: 6px;
    padding: 6px 8px;
    min-height: 24px;
}}
QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {T.cyan};
}}
QCheckBox {{
    color: {T.text};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 17px;
    height: 17px;
    border: 1px solid #566772;
    border-radius: 4px;
    background: #0E151A;
}}
QCheckBox::indicator:checked {{
    background: {T.cyan};
    border-color: {T.cyan};
}}
"""


class Card(QFrame):
    """Simple flat Tesla-style card."""

    def __init__(self, parent: QWidget | None = None, radius: int = 10):
        super().__init__(parent)
        self.setObjectName("teslaCard")
        self.setStyleSheet(
            f"""
            QFrame#teslaCard {{
                background: {T.panel};
                border: 1px solid {T.border};
                border-radius: {radius}px;
            }}
            """
        )


class TeslaTabBar(QTabBar):
    """Flat tabs with a thin cyan selected indicator."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setStyleSheet(
            f"""
            QTabBar {{ background: transparent; }}
            QTabBar::tab {{
                background: transparent;
                color: {T.muted};
                border: none;
                border-bottom: 2px solid transparent;
                padding: 12px 22px 10px 22px;
                min-width: 96px;
                font-size: 13px;
                font-weight: 500;
            }}
            QTabBar::tab:hover {{ color: {T.text}; }}
            QTabBar::tab:selected {{
                color: white;
                border-bottom: 3px solid {T.cyan};
            }}
            """
        )


class StatusDot(QWidget):
    def __init__(self, color: str = T.green, diameter: int = 12, parent: QWidget | None = None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(diameter, diameter)

    def set_color(self, color: str | QColor) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))


class PlotToggle(QPushButton):
    """Independent circular plot-selection toggle."""

    selected = pyqtSignal(int, bool)

    def __init__(self, index: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.index = int(index)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(32, 32)
        self.clicked.connect(lambda checked: self.selected.emit(self.index, bool(checked)))
        self.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                border: 1px solid #8A9AA4;
                border-radius: 11px;
                margin: 5px;
            }}
            QPushButton:hover {{ border-color: {T.cyan}; }}
            QPushButton:checked {{
                background: {T.cyan};
                border: 4px solid #15242E;
            }}
            """
        )


class ClickLabel(QLabel):
    clicked = pyqtSignal(int)

    def __init__(self, index: int, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.index = int(index)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)
        super().mousePressEvent(event)


class TrendPlot(QWidget):
    """Dependency-free two-series trend plot with Tesla-style actual fill.

    The graph intentionally does not draw a legend or duplicate target/actual
    numeric labels. Those values belong in the readout card above the graph.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        y_axis_label: str = "CURRENT (A)",
        x_axis_label: str = "TIME (s)",
        target_color: str = T.cyan,
        actual_color: str = T.orange,
    ):
        super().__init__(parent)
        self.x_data: list[float] = []
        self.target_data: list[float] = []
        self.actual_data: list[float] = []
        self.y_axis_label = y_axis_label
        self.x_axis_label = x_axis_label
        self.target_color = QColor(target_color)
        self.actual_color = QColor(actual_color)
        self.setMinimumHeight(230)

    def clear(self) -> None:
        self.x_data.clear()
        self.target_data.clear()
        self.actual_data.clear()
        self.update()

    def set_data(
        self,
        x_data: Sequence[float] | Iterable[float],
        target_data: Sequence[float] | Iterable[float],
        actual_data: Sequence[float] | Iterable[float],
    ) -> None:
        x = list(x_data)
        target = list(target_data)
        actual = list(actual_data)
        n = min(len(x), len(target), len(actual))
        filtered: list[tuple[float, float, float]] = []
        for i in range(n):
            try:
                values = (float(x[i]), float(target[i]), float(actual[i]))
            except (TypeError, ValueError):
                continue
            if all(math.isfinite(v) for v in values):
                filtered.append(values)
        self.x_data = [row[0] for row in filtered]
        self.target_data = [row[1] for row in filtered]
        self.actual_data = [row[2] for row in filtered]
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(T.panel))

        left, top, right, bottom = 62, 18, 18, 42
        plot_rect = self.rect().adjusted(left, top, -right, -bottom)
        if plot_rect.width() <= 10 or plot_rect.height() <= 10:
            return

        painter.setPen(QPen(QColor(39, 50, 58, 120), 1))
        for i in range(9):
            x = plot_rect.left() + i * plot_rect.width() / 8
            painter.drawLine(int(x), plot_rect.top(), int(x), plot_rect.bottom())
        for i in range(9):
            y = plot_rect.top() + i * plot_rect.height() / 8
            painter.drawLine(plot_rect.left(), int(y), plot_rect.right(), int(y))

        painter.setPen(QPen(QColor(T.border), 1))
        painter.drawLine(plot_rect.bottomLeft(), plot_rect.bottomRight())
        painter.drawLine(plot_rect.bottomLeft(), plot_rect.topLeft())

        painter.setPen(QColor(T.muted))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(plot_rect.left(), self.height() - 12, self.x_axis_label)
        painter.save()
        painter.translate(16, plot_rect.center().y() + 34)
        painter.rotate(-90)
        painter.drawText(0, 0, self.y_axis_label)
        painter.restore()

        if len(self.x_data) < 2:
            return

        x_min, x_max = min(self.x_data), max(self.x_data)
        values = self.target_data + self.actual_data
        y_min, y_max = min(values), max(values)
        if abs(x_max - x_min) < 1e-12:
            x_max = x_min + 1.0
        if abs(y_max - y_min) < 1e-12:
            pad = max(1.0, abs(y_max) * 0.1)
            y_min -= pad
            y_max += pad
        else:
            pad = 0.08 * (y_max - y_min)
            y_min -= pad
            y_max += pad

        def map_point(x_value: float, y_value: float) -> QPointF:
            px = plot_rect.left() + (x_value - x_min) / (x_max - x_min) * plot_rect.width()
            py = plot_rect.bottom() - (y_value - y_min) / (y_max - y_min) * plot_rect.height()
            return QPointF(px, py)

        def make_path(series: Sequence[float]) -> QPainterPath:
            path = QPainterPath()
            path.moveTo(map_point(self.x_data[0], series[0]))
            for x_value, y_value in zip(self.x_data[1:], series[1:]):
                path.lineTo(map_point(x_value, y_value))
            return path

        target_path = make_path(self.target_data)
        actual_path = make_path(self.actual_data)

        actual_fill = QPainterPath(actual_path)
        actual_fill.lineTo(map_point(self.x_data[-1], y_min))
        actual_fill.lineTo(map_point(self.x_data[0], y_min))
        actual_fill.closeSubpath()

        fill_gradient = QLinearGradient(0, plot_rect.top(), 0, plot_rect.bottom())
        fill_gradient.setColorAt(0.00, QColor(255, 178, 72, 150))
        fill_gradient.setColorAt(0.38, QColor(244, 120, 24, 115))
        fill_gradient.setColorAt(0.72, QColor(190, 62, 10, 55))
        fill_gradient.setColorAt(1.00, QColor(45, 10, 0, 8))
        painter.fillPath(actual_fill, fill_gradient)

        painter.setPen(
            QPen(
                QColor(self.actual_color.red(), self.actual_color.green(), self.actual_color.blue(), 50),
                10,
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
        painter.setPen(
            QPen(
                self.actual_color,
                2,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.drawPath(actual_path)

        painter.setPen(QPen(QColor(255, 218, 150, 165), 1))
        painter.drawPath(actual_path)

        endpoint = map_point(self.x_data[-1], self.actual_data[-1])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.actual_color)
        painter.drawEllipse(endpoint, 4.5, 4.5)


def load_cnl_logo_pixmap(base_dir: str) -> QPixmap:
    """Load the replaceable CNL logo from the controller directory."""
    search_paths = (
        os.path.join(base_dir, "cnl_logo.png"),
        os.path.join(base_dir, "cnl_logo(2).png"),
        os.path.join(base_dir, "icons", "cnl_logo.png"),
        os.path.join(base_dir, "icons", "cnl_logo(2).png"),
    )
    for path in search_paths:
        if os.path.exists(path):
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                return pixmap
    return QPixmap()


def secondary_button_css(accent: str = T.cyan) -> str:
    return f"""
        QPushButton {{
            background: #11191F;
            color: {T.text};
            border: 1px solid #3A4851;
            border-radius: 7px;
            padding: 8px 16px;
            font-size: 13px;
            font-weight: 500;
        }}
        QPushButton:hover {{ background: #172129; border-color: {accent}; }}
        QPushButton:pressed, QPushButton:checked {{ background: #20303B; border-color: {accent}; }}
        QPushButton:disabled {{ color: #59646B; border-color: #293239; }}
    """


def bulk_button_css(accent: str) -> str:
    return f"""
        QPushButton {{
            background: #10171C;
            color: {accent};
            border: 1px solid #35434C;
            border-radius: 6px;
            padding: 3px 8px;
            font-size: 10px;
            font-weight: 600;
        }}
        QPushButton:hover {{ background: #172129; border-color: {accent}; }}
        QPushButton:pressed {{ background: #20303B; }}
        QPushButton:disabled {{ color: #59646B; border-color: #293239; }}
    """


def target_label_css(selected: bool) -> str:
    border = T.cyan if selected else "#3C4B55"
    background = "#111C24" if selected else "#0E151A"
    return f"""
        QLabel {{
            color: {T.cyan};
            background: {background};
            border: 1px solid {border};
            border-radius: 6px;
            padding: 7px;
            font-size: 17px;
            font-weight: 600;
        }}
    """


def state_button_css(accent: str, active: bool) -> str:
    background = "#172128" if active else "#10171C"
    return f"""
        QPushButton {{
            color: {accent};
            background: {background};
            border: 1px solid #35434C;
            border-radius: 6px;
            padding: 7px;
            font-size: 14px;
            font-weight: 500;
        }}
        QPushButton:hover {{ border-color: {accent}; }}
        QPushButton:disabled {{ color: #59646B; border-color: #293239; }}
    """


def digit_button_css() -> str:
    return f"""
        QPushButton {{
            background: #10171C;
            color: white;
            border: 1px solid #394750;
            border-radius: 7px;
            font-size: 27px;
        }}
        QPushButton:hover {{ background: #172129; border-color: {T.cyan}; }}
        QPushButton:pressed {{ background: #20303B; }}
    """


def info_label_css(accent: str = T.border) -> str:
    return f"""
        QLabel {{
            color: {T.muted};
            background: #0E151A;
            border: 1px solid {accent};
            border-radius: 7px;
            padding: 9px;
        }}
    """


def flat_button_css() -> str:
    return f"""
        QPushButton {{
            background: transparent;
            border: none;
            color: {T.text};
            font-size: 20px;
        }}
        QPushButton:hover {{ color: {T.cyan}; }}
    """


__all__ = [
    "T",
    "CONTROLLER_QSS",
    "Card",
    "TeslaTabBar",
    "StatusDot",
    "PlotToggle",
    "ClickLabel",
    "TrendPlot",
    "load_cnl_logo_pixmap",
    "secondary_button_css",
    "bulk_button_css",
    "target_label_css",
    "state_button_css",
    "digit_button_css",
    "info_label_css",
    "flat_button_css",
]
