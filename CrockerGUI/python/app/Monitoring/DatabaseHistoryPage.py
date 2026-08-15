from __future__ import annotations

import csv
import base64
import json
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QPointF,
    QRectF,
    Qt,
    QDate,
    QDateTime,
    QBuffer,
    QByteArray,
    QIODevice,
    QMimeData,
    QTimer,
    QTime,
)
from PySide6.QtGui import (
    QColor,
    QDrag,
    QPainter,
    QPainterPath,
    QPen,
    QImage,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from python.app.PageShell import DetailPage
from source.Python.Data.pipeline_schema import DEFAULT_DB_PATH


CHANNEL_LABELS = {
    "ch1": "Trim Coil 1",
    "ch2": "Trim Coil 2",
    "ch3": "Trim Coil 3",
    "ch4": "Trim Coil 4",
    "ch5": "Trim Coil 5",
    "ch6": "Trim Coil 6",
    "ch7": "Trim Coil 7",
    "ch8": "Trim Coil 8",
    "ch9": "Trim Coil 9",
    "ch10": "Trim Coil 10",
    "ch11": "Trim Coil 11",
    "ch12": "Trim Coil 12",
    "main_magnet": "Main Magnet",
    "centering_beam": "Centering Beam",
    "arc_voltage": "Arc Voltage",
    "arc_current": "Arc Current",
    "filament": "Filament",
    "esd_kv": "ESD kV",
    "esd_ma": "ESD mA",
    "outside_iron": "Outside Iron",
    "inside_iron": "Inside Iron",
    "vac1": "Vac 1",
    "vac2": "Vac 2",
    "vac3": "Vac 3",
    "vac4": "Vac 4",
    "vac5": "Vac 5",
    "beam_current": "Beam Current",
    "latency": "Latency",
}

CHANNEL_ORDER = list(CHANNEL_LABELS)
PLOT_COLORS = [
    QColor("#60a5fa"),
    QColor("#94a3b8"),
    QColor("#22c55e"),
    QColor("#f59e0b"),
    QColor("#a78bfa"),
    QColor("#e5e7eb"),
]
LIMITED_EXPORT_COLORS = [
    QColor("#0f172a"),
    QColor("#2563eb"),
    QColor("#b45309"),
    QColor("#047857"),
]


class ChannelListWidget(QListWidget):
    def startDrag(self, supported_actions) -> None:  # noqa: N802 - Qt API name
        del supported_actions
        items = self.selectedItems()
        if not items and self.currentItem() is not None:
            items = [self.currentItem()]
        channels = [
            str(item.data(Qt.UserRole))
            for item in items
            if item.data(Qt.UserRole)
        ]
        if not channels:
            return
        mime = QMimeData()
        mime.setText(",".join(channels))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)


class HistoryPlotWidget(QWidget):
    def __init__(
        self,
        title: str,
        channels_changed: Callable[[], None],
        hover_time_changed: Callable[[float | None], None],
        marker_time_pinned: Callable[[float], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.title = title
        self.channels_changed = channels_changed
        self.hover_time_changed = hover_time_changed
        self.marker_time_pinned = marker_time_pinned
        self.channels: list[str] = []
        self.series: dict[str, list[tuple[float, float]]] = {}
        self.units: dict[str, str] = {}
        self._hover_time: float | None = None
        self._hover_point: tuple[str, float, float] | None = None
        self._pinned_times: list[float] = []
        self._show_time_tooltip = False
        self._export_color_mode = "normal"
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setObjectName("historyPlot")
        self.setMinimumHeight(315)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def add_channels(self, channels: list[str]) -> None:
        changed = False
        for channel in channels:
            if channel and channel not in self.channels:
                self.channels.append(channel)
                changed = True
        if changed:
            self.channels_changed()
            self.update()

    def clear_channels(self) -> None:
        if not self.channels:
            return
        self.channels.clear()
        self.series.clear()
        self.channels_changed()
        self.update()

    def clear_pinned_tooltips(self) -> None:
        self._pinned_times.clear()
        self.update()

    def set_shared_markers(
        self,
        hover_time: float | None,
        pinned_times: list[float],
        show_time_tooltip: bool,
    ) -> None:
        self._hover_time = hover_time
        self._hover_point = None
        self._pinned_times = list(pinned_times)
        self._show_time_tooltip = show_time_tooltip
        self.update()

    def set_series(self, series: dict[str, list[tuple[float, float]]]) -> None:
        self.series = series
        self.update()

    def set_units(self, units: dict[str, str]) -> None:
        self.units = units
        self.update()

    def set_export_color_mode(self, mode: str) -> None:
        self._export_color_mode = mode if mode in {"normal", "bw", "limited"} else "normal"
        self.update()

    def marker_x_ratios(self) -> list[float]:
        all_points = [point for values in self.series.values() for point in values]
        if not all_points:
            return []
        plot = self._plot_rect()
        start, end, _low, _high = self._bounds(all_points)
        marker_times = [*self._pinned_times]
        if self._hover_time is not None:
            marker_times.append(self._hover_time)
        ratios = []
        for marker_time in marker_times:
            x_ratio = (marker_time - start) / max(0.001, end - start)
            x = plot.left() + plot.width() * max(0.0, min(1.0, x_ratio))
            ratios.append(x / max(1.0, float(self.width())))
        return ratios

    def _plot_color(self, index: int) -> QColor:
        if self._export_color_mode == "bw":
            return QColor("#111827")
        if self._export_color_mode == "limited":
            return LIMITED_EXPORT_COLORS[index % len(LIMITED_EXPORT_COLORS)]
        return PLOT_COLORS[index % len(PLOT_COLORS)]

    def _color(self, normal: str, bw: str, limited: str | None = None) -> QColor:
        if self._export_color_mode == "bw":
            return QColor(bw)
        if self._export_color_mode == "limited":
            return QColor(limited or bw)
        return QColor(normal)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt API name
        channels = [
            channel.strip()
            for channel in event.mimeData().text().split(",")
            if channel.strip()
        ]
        self.add_channels(channels)
        event.acceptProposedAction()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if self._update_hover_at(event.position()):
            self.hover_time_changed(self._hover_time)
        else:
            self.hover_time_changed(None)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if event.button() == Qt.MouseButton.LeftButton and self._update_hover_at(event.position()):
            if self._hover_time is not None:
                self.marker_time_pinned(self._hover_time)
                event.accept()
                return
        super().mousePressEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        self.hover_time_changed(None)

    def _update_hover_at(self, position: QPointF) -> bool:
        plot = self._plot_rect()
        all_points = [point for values in self.series.values() for point in values]
        if not plot.contains(position) or not all_points:
            self._hover_time = None
            self._hover_point = None
            return False

        start, end, _low, _high = self._bounds(all_points)
        x_ratio = (position.x() - plot.left()) / max(1.0, plot.width())
        hover_time = start + (end - start) * max(0.0, min(1.0, x_ratio))
        nearest: tuple[str, float, float] | None = None
        nearest_delta = float("inf")
        for channel, points in self.series.items():
            for timestamp, value in points:
                delta = abs(timestamp - hover_time)
                if delta < nearest_delta:
                    nearest_delta = delta
                    nearest = (channel, timestamp, value)
        self._hover_time = hover_time
        self._hover_point = nearest
        return nearest is not None

    def _plot_rect(self) -> QRectF:
        top = 46.0 + self._legend_rows() * 20.0
        return QRectF(self.rect()).adjusted(58.0, top, -22.0, -80.0)

    def _legend_rows(self) -> int:
        if not self.channels:
            return 1
        usable_width = max(1.0, self.width() - 80.0)
        rows = 1
        row_width = 0.0
        for channel in self.channels:
            label = self._short_label(channel)
            item_width = max(92.0, min(170.0, 58.0 + len(label) * 7.0))
            if row_width and row_width + item_width > usable_width:
                rows += 1
                row_width = 0.0
            row_width += item_width
        return rows

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self._color("#0f172a", "#ffffff"))

        plot = self._plot_rect()
        if plot.width() <= 8 or plot.height() <= 8:
            return

        painter.setPen(self._color("#e5e7eb", "#111827"))
        painter.drawText(
            QRectF(18, 8, self.width() - 36, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            self.title,
        )
        self._draw_legend(painter, plot)

        painter.setPen(QPen(self._color("#334155", "#d1d5db"), 1))
        for step in range(5):
            y = plot.top() + plot.height() * step / 4
            x = plot.left() + plot.width() * step / 4
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
        painter.setPen(QPen(self._color("#475569", "#4b5563"), 1))
        painter.drawRect(plot)
        footer = self._footer_rect(plot)
        painter.setPen(QPen(self._color("#334155", "#d1d5db"), 1))
        painter.drawLine(QPointF(plot.left(), footer.top()), QPointF(plot.right(), footer.top()))

        all_points = [point for values in self.series.values() for point in values]
        if not all_points:
            painter.setPen(self._color("#94a3b8", "#374151"))
            if self.channels:
                text = "No samples in the selected date range"
            else:
                text = "No variables assigned"
            painter.drawText(plot, Qt.AlignCenter, text)
            return

        start, end, low, high = self._bounds(all_points)

        painter.setPen(self._color("#94a3b8", "#374151"))
        painter.drawText(
            QRectF(plot.left() - 58, plot.top() - 8, 48, 18),
            Qt.AlignRight | Qt.AlignVCenter,
            f"{high:.2g}",
        )
        painter.drawText(
            QRectF(plot.left() - 58, plot.bottom() - 10, 48, 18),
            Qt.AlignRight | Qt.AlignVCenter,
            f"{low:.2g}",
        )
        if self._hover_time is None:
            painter.drawText(
                QRectF(plot.left(), plot.bottom() + 24, plot.width(), 20),
                Qt.AlignCenter,
                "Time",
            )

        for index, channel in enumerate(self.channels):
            points = self.series.get(channel, [])
            if len(points) < 2:
                continue
            color = self._plot_color(index)
            path = QPainterPath(self._plot_point(plot, points[0], start, end, low, high))
            for point in points[1:]:
                path.lineTo(self._plot_point(plot, point, start, end, low, high))
            painter.setPen(QPen(color, 2))
            painter.drawPath(path)

        for index, pinned_time in enumerate(self._pinned_times):
            self._draw_marker_set(
                painter, plot, footer, start, end, low, high, pinned_time, index
            )

        if self._hover_time is not None:
            self._draw_marker_set(
                painter, plot, footer, start, end, low, high, self._hover_time, len(self._pinned_times)
            )

    def _footer_rect(self, plot: QRectF) -> QRectF:
        return QRectF(plot.left(), plot.bottom() + 8.0, plot.width(), 42.0)

    def _draw_marker_set(
        self,
        painter: QPainter,
        plot: QRectF,
        footer: QRectF,
        start: float,
        end: float,
        low: float,
        high: float,
        marker_time: float,
        lane_index: int,
    ) -> None:
        samples = self._nearest_samples(marker_time)
        if not samples:
            return
        x_ratio = (marker_time - start) / (end - start)
        x = plot.left() + plot.width() * max(0.0, min(1.0, x_ratio))
        painter.setPen(QPen(self._color("#cbd5e1", "#111827"), 1, Qt.DashLine))
        painter.drawLine(QPointF(x, 0.0), QPointF(x, float(self.height())))
        for channel, timestamp, value in samples:
            point = self._plot_point(plot, (timestamp, value), start, end, low, high)
            color_index = self.channels.index(channel) if channel in self.channels else 0
            painter.setPen(QPen(self._plot_color(color_index), 2))
            painter.drawLine(QPointF(point.x() - 6, point.y()), QPointF(point.x() + 6, point.y()))
            painter.drawLine(QPointF(point.x(), point.y() - 6), QPointF(point.x(), point.y() + 6))
        self._draw_value_label(painter, QPointF(x, plot.top()), samples, lane_index)
        if self._show_time_tooltip:
            self._draw_time_label(painter, x, footer, marker_time)

    def _draw_legend(self, painter: QPainter, plot: QRectF) -> None:
        if not self.channels:
            return
        x = plot.left()
        y = 34.0
        max_x = plot.right()
        for index, channel in enumerate(self.channels):
            label = self._short_label(channel)
            item_width = max(92.0, min(170.0, 58.0 + len(label) * 7.0))
            if x + item_width > max_x:
                x = plot.left()
                y += 20.0
            color = self._plot_color(index)
            painter.setPen(QPen(color, 2))
            painter.drawLine(QPointF(x, y + 9), QPointF(x + 26, y + 9))
            painter.setPen(self._color("#cbd5e1", "#111827"))
            painter.drawText(QRectF(x + 34, y, item_width - 34, 18), Qt.AlignLeft | Qt.AlignVCenter, label)
            x += item_width

    def _draw_value_label(
        self,
        painter: QPainter,
        anchor: QPointF,
        samples: list[tuple[str, float, float]],
        lane_index: int,
    ) -> None:
        if not samples:
            return
        lines = []
        for channel, _timestamp, value in samples:
            units = self.units.get(channel, "")
            suffix = f" {units}" if units else ""
            lines.append(f"{self._short_label(channel)}  {value:.5g}{suffix}")
        box_width = max(180.0, min(280.0, max(len(line) for line in lines) * 7.4 + 24.0))
        box_height = 22.0 + len(lines) * 19.0
        x = anchor.x() + 12.0
        y = anchor.y() + 10.0 + (lane_index % 3) * 8.0
        if x + box_width > self.width() - 10:
            x = anchor.x() - box_width - 12.0
        if y < 10:
            y = anchor.y() + 12.0
        box = QRectF(
            max(10.0, min(x, self.width() - box_width - 10.0)),
            max(10.0, min(y, self.height() - box_height - 10.0)),
            box_width,
            box_height,
        )
        painter.setPen(QPen(self._color("#60a5fa", "#111827"), 1))
        painter.setBrush(self._color("#0f172a", "#ffffff"))
        painter.drawRoundedRect(box, 7, 7)
        for index, line in enumerate(lines):
            channel = samples[index][0]
            color_index = self.channels.index(channel) if channel in self.channels else 0
            y_line = box.top() + 10 + index * 19
            painter.setPen(QPen(self._plot_color(color_index), 2))
            painter.drawLine(QPointF(box.left() + 10, y_line + 8), QPointF(box.left() + 26, y_line + 8))
            painter.setPen(self._color("#e5e7eb", "#111827"))
            painter.drawText(QRectF(box.left() + 34, y_line, box.width() - 44, 17), Qt.AlignLeft | Qt.AlignVCenter, line)

    def _draw_time_label(
        self,
        painter: QPainter,
        x: float,
        footer: QRectF,
        marker_time: float,
    ) -> None:
        time_text = datetime.fromtimestamp(marker_time).strftime("%Y-%m-%d %H:%M:%S")
        box_width = 156.0
        box_height = 28.0
        box = QRectF(
            max(footer.left() + 6.0, min(x - box_width / 2, footer.right() - box_width - 6.0)),
            footer.center().y() - box_height / 2,
            box_width,
            box_height,
        )
        painter.setPen(QPen(self._color("#475569", "#111827"), 1))
        painter.setBrush(self._color("#0f172a", "#ffffff"))
        painter.drawRoundedRect(box, 7, 7)
        painter.setPen(self._color("#bfdbfe", "#111827"))
        painter.drawText(box, Qt.AlignCenter, time_text)

    def _nearest_samples(
        self,
        hover_time: float | None,
    ) -> list[tuple[str, float, float]]:
        if hover_time is None:
            return []
        samples: list[tuple[str, float, float]] = []
        for channel in self.channels:
            points = self.series.get(channel, [])
            if not points:
                continue
            timestamp, value = min(points, key=lambda point: abs(point[0] - hover_time))
            samples.append((channel, timestamp, value))
        return samples

    def _short_label(self, channel: str) -> str:
        if channel.startswith("ch") and channel[2:].isdigit():
            return f"TC{channel[2:]}"
        return CHANNEL_LABELS.get(channel, channel)

    def _bounds(self, all_points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
        times = [point[0] for point in all_points]
        values = [point[1] for point in all_points]
        start, end = min(times), max(times)
        low, high = min(values), max(values)
        if end <= start:
            end = start + 1.0
        if high <= low:
            padding = max(abs(high) * 0.05, 1.0)
            low -= padding
            high += padding
        else:
            padding = (high - low) * 0.08
            low -= padding
            high += padding
        return start, end, low, high

    def _plot_point(
        self,
        plot: QRectF,
        point: tuple[float, float],
        start: float,
        end: float,
        low: float,
        high: float,
    ) -> QPointF:
        t, value = point
        x_ratio = (t - start) / (end - start)
        y_ratio = (value - low) / (high - low)
        return QPointF(
            plot.left() + plot.width() * x_ratio,
            plot.bottom() - plot.height() * y_ratio,
        )


class DatabaseHistoryPage(DetailPage):
    def __init__(
        self,
        go_back: Callable[[], None],
        db_path: str | Path = DEFAULT_DB_PATH,
        back_label: str = "Back to Monitoring",
    ) -> None:
        super().__init__(
            "Database History",
            "SQLite readings history",
            back_label,
            go_back,
        )
        self.db_path = self._resolve_db_path(Path(db_path))
        self.last_rows: list[tuple[float, str, float, str]] = []
        self._shared_hover_time: float | None = None
        self._shared_pinned_times: list[float] = []
        self._last_plotted_sample_count = 0
        self._last_plot_time_range: tuple[float, float] | None = None
        self._has_loaded_defaults = False
        self._pdf_process: subprocess.Popen[str] | None = None
        self._pdf_poll_timer = QTimer(self)
        self._pdf_poll_timer.setInterval(250)
        self._pdf_poll_timer.timeout.connect(self._poll_pdf_export)
        self._pdf_output_path = ""
        self.header.hide()

        _, panel_layout = self.add_workspace()
        panel_layout.setContentsMargins(18, 8, 18, 16)
        panel_layout.setSpacing(10)

        toolbar = QFrame()
        toolbar.setObjectName("historyToolbar")
        toolbar_layout = QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 8, 8, 8)
        toolbar_layout.setSpacing(7)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        self.path_label = QLabel(str(self.db_path))
        self.path_label.setObjectName("historyPathPill")
        self.status_label = QLabel("")
        self.status_label.setObjectName("historyStatusValue")
        browse_button = QPushButton("Open DB")
        reload_button = QPushButton("Reload")
        self.export_pdf_button = QPushButton("Export PDF")
        self.export_csv_button = QPushButton("Export CSV")
        browse_button.clicked.connect(self._choose_db)
        reload_button.clicked.connect(self.reload)
        self.export_pdf_button.clicked.connect(self.export_pdf)
        self.export_csv_button.clicked.connect(self.export_csv)
        for button in (browse_button, reload_button, self.export_pdf_button, self.export_csv_button):
            button.setCursor(Qt.PointingHandCursor)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self.plots_tab_button = QPushButton("Plots")
        self.summary_tab_button = QPushButton("Summary")
        tab_cluster = QFrame()
        tab_cluster.setObjectName("historySegment")
        tab_layout = QHBoxLayout(tab_cluster)
        tab_layout.setContentsMargins(3, 3, 3, 3)
        tab_layout.setSpacing(3)
        for index, button in enumerate((self.plots_tab_button, self.summary_tab_button)):
            button.setObjectName("historyTabButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            self.tab_group.addButton(button, index)
            tab_layout.addWidget(button)
        top.addWidget(tab_cluster)
        self.plots_tab_button.setChecked(True)

        db_group = QFrame()
        db_group.setObjectName("historyToolbarGroup")
        db_layout = QHBoxLayout(db_group)
        db_layout.setContentsMargins(9, 5, 9, 5)
        db_layout.setSpacing(8)
        database_label = QLabel("Database")
        database_label.setObjectName("historyToolbarLabel")
        db_layout.addWidget(database_label)
        db_layout.addWidget(self.path_label)
        top.addWidget(db_group, 1)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setCalendarPopup(True)
        self.sample_limit = QSpinBox()
        self.sample_limit.setRange(25, 20000)
        self.sample_limit.setSingleStep(25)
        self.sample_limit.setValue(500)
        self.sample_limit.setSuffix(" samples")
        self.export_name = QLineEdit("database_history")
        self.export_name.setObjectName("historyExportName")
        self.export_name.setMinimumWidth(180)
        self.pdf_color_group = QButtonGroup(self)
        self.pdf_color_group.setExclusive(True)
        pdf_color_segment = QFrame()
        pdf_color_segment.setObjectName("historySegment")
        pdf_color_layout = QHBoxLayout(pdf_color_segment)
        pdf_color_layout.setContentsMargins(3, 3, 3, 3)
        pdf_color_layout.setSpacing(3)
        for index, (label, mode) in enumerate(
            (
                ("Color", "normal"),
                ("B/W", "bw"),
                ("Limited", "limited"),
            )
        ):
            button = QPushButton(label)
            button.setObjectName("historyTabButton")
            button.setCheckable(True)
            button.setProperty("pdfColorMode", mode)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setChecked(index == 0)
            self.pdf_color_group.addButton(button, index)
            pdf_color_layout.addWidget(button)
        self.date_edit.dateChanged.connect(lambda date: self.plot())
        self.sample_limit.valueChanged.connect(lambda value: self.plot())
        for editor in (self.date_edit,):
            editor.setCalendarPopup(True)

        filters_group = QFrame()
        filters_group.setObjectName("historyToolbarGroup")
        filters_layout = QHBoxLayout(filters_group)
        filters_layout.setContentsMargins(9, 5, 9, 5)
        filters_layout.setSpacing(8)
        date_label = QLabel("Date")
        date_label.setObjectName("historyToolbarLabel")
        filters_layout.addWidget(date_label)
        filters_layout.addWidget(self.date_edit)
        samples_label = QLabel("Samples")
        samples_label.setObjectName("historyToolbarLabel")
        filters_layout.addWidget(samples_label)
        filters_layout.addWidget(self.sample_limit)
        filename_label = QLabel("File")
        filename_label.setObjectName("historyToolbarLabel")
        filters_layout.addWidget(filename_label)
        filters_layout.addWidget(self.export_name)
        filters_layout.addWidget(pdf_color_segment)
        controls.addWidget(filters_group, 1)

        first_date = QPushButton("First Date")
        latest = QPushButton("Latest Date")
        plot_button = QPushButton("Refresh Plots")
        first_date.clicked.connect(self._jump_to_first)
        latest.clicked.connect(self._jump_to_latest)
        plot_button.clicked.connect(self.plot)
        actions_group = QFrame()
        actions_group.setObjectName("historyToolbarActions")
        actions_layout = QHBoxLayout(actions_group)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(7)
        for button in (first_date, latest, plot_button):
            button.setCursor(Qt.PointingHandCursor)
            actions_layout.addWidget(button)
        controls.addWidget(actions_group)

        status_group = QFrame()
        status_group.setObjectName("historyStatusCard")
        status_layout = QVBoxLayout(status_group)
        status_layout.setContentsMargins(10, 5, 10, 5)
        status_layout.setSpacing(0)
        status_caption = QLabel("STATUS")
        status_caption.setObjectName("historyStatusCaption")
        status_layout.addWidget(status_caption)
        status_layout.addWidget(self.status_label)
        top.addWidget(status_group)

        file_actions = QFrame()
        file_actions.setObjectName("historyToolbarActions")
        file_actions_layout = QHBoxLayout(file_actions)
        file_actions_layout.setContentsMargins(0, 0, 0, 0)
        file_actions_layout.setSpacing(7)
        file_actions_layout.addWidget(self.export_csv_button)
        file_actions_layout.addWidget(self.export_pdf_button)
        file_actions_layout.addWidget(browse_button)
        file_actions_layout.addWidget(reload_button)
        top.addWidget(file_actions)
        toolbar_layout.addLayout(top)
        toolbar_layout.addLayout(controls)
        panel_layout.addWidget(toolbar)

        plots_tab = QWidget()
        plots_tab_layout = QVBoxLayout(plots_tab)
        plots_tab_layout.setContentsMargins(0, 0, 0, 0)
        plots_tab_layout.setSpacing(12)

        body = QHBoxLayout()
        left = QFrame()
        left.setObjectName("workspace")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.addWidget(QLabel("Variables"))
        self.channel_list = ChannelListWidget()
        self.channel_list.setDragEnabled(True)
        self.channel_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        left_layout.addWidget(self.channel_list, 1)
        channel_actions = QHBoxLayout()
        select_all = QPushButton("All")
        clear = QPushButton("Clear")
        select_all.clicked.connect(self.channel_list.selectAll)
        clear.clicked.connect(self.channel_list.clearSelection)
        channel_actions.addWidget(select_all)
        channel_actions.addWidget(clear)
        left_layout.addLayout(channel_actions)
        body.addWidget(left, 1)

        right = QVBoxLayout()
        right.setSpacing(0)

        self.plot_widgets: list[HistoryPlotWidget] = []
        for index in range(3):
            plot_row = QHBoxLayout()
            plot_row.setContentsMargins(0, 0, 0, 0)
            plot_row.setSpacing(8)
            plot_widget = HistoryPlotWidget(
                f"Plot {index + 1}",
                self.plot,
                self._set_shared_hover_time,
                self._pin_shared_marker,
            )
            self.plot_widgets.append(plot_widget)
            clear_plot = QPushButton("Clear")
            clear_plot.setMaximumWidth(72)
            clear_plot.setCursor(Qt.PointingHandCursor)
            clear_plot.clicked.connect(
                lambda checked=False, plot=plot_widget: plot.clear_channels()
            )
            clear_tooltips = QPushButton("Marks")
            clear_tooltips.setMaximumWidth(72)
            clear_tooltips.setCursor(Qt.PointingHandCursor)
            clear_tooltips.clicked.connect(
                lambda checked=False: self._clear_shared_markers()
            )
            plot_actions = QVBoxLayout()
            plot_actions.setSpacing(8)
            plot_actions.addStretch(1)
            plot_actions.addWidget(clear_plot)
            plot_actions.addWidget(clear_tooltips)
            plot_actions.addStretch(1)
            plot_row.addWidget(plot_widget, 1)
            plot_row.addLayout(plot_actions)
            right.addLayout(plot_row, 1)
        body.addLayout(right, 5)
        plots_tab_layout.addLayout(body, 1)

        summary_tab = QWidget()
        summary_layout = QVBoxLayout(summary_tab)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(10)
        summary_header = QFrame()
        summary_header.setObjectName("historySummaryHeader")
        summary_actions = QHBoxLayout(summary_header)
        summary_actions.setContentsMargins(12, 10, 12, 10)
        summary_actions.setSpacing(10)
        summary_text = QVBoxLayout()
        summary_text.setSpacing(2)
        summary_title = QLabel("Summary")
        summary_title.setObjectName("historySummaryTitle")
        self.summary_meta_label = QLabel("No plotted channels")
        self.summary_meta_label.setObjectName("historySummaryMeta")
        summary_text.addWidget(summary_title)
        summary_text.addWidget(self.summary_meta_label)
        summary_actions.addLayout(summary_text, 1)
        export_button = QPushButton("Export CSV")
        export_button.setCursor(Qt.PointingHandCursor)
        export_button.clicked.connect(self.export_csv)
        summary_actions.addWidget(export_button)
        summary_layout.addWidget(summary_header)
        self.summary_table = QTableWidget(0, 5)
        self.summary_table.setObjectName("historySummaryTable")
        self.summary_table.setAlternatingRowColors(True)
        self.summary_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.summary_table.setShowGrid(False)
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.horizontalHeader().setStretchLastSection(True)
        self.summary_table.setHorizontalHeaderLabels(
            ["Channel", "Samples", "Min", "Max", "Latest"]
        )
        summary_layout.addWidget(self.summary_table, 1)

        self.data_stack = QStackedWidget()
        self.data_stack.addWidget(plots_tab)
        self.data_stack.addWidget(summary_tab)
        self.tab_group.idClicked.connect(self.data_stack.setCurrentIndex)
        panel_layout.addWidget(self.data_stack, 1)

        self.reload()

    def _set_shared_hover_time(self, hover_time: float | None) -> None:
        self._shared_hover_time = hover_time
        self._sync_shared_markers()

    def _pin_shared_marker(self, marker_time: float) -> None:
        self._shared_pinned_times.append(marker_time)
        self._sync_shared_markers()

    def _clear_shared_markers(self) -> None:
        self._shared_pinned_times.clear()
        self._sync_shared_markers()

    def _sync_shared_markers(self) -> None:
        for index, plot_widget in enumerate(getattr(self, "plot_widgets", [])):
            plot_widget.set_shared_markers(
                self._shared_hover_time,
                self._shared_pinned_times,
                index == len(self.plot_widgets) - 1,
            )

    def _resolve_db_path(self, path: Path) -> Path:
        if path.exists() or path.is_absolute():
            return path
        app_root = Path(__file__).resolve().parents[3]
        app_relative = app_root / path
        if app_relative.exists():
            return app_relative
        return path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _choose_db(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open SQLite Database",
            str(self.db_path.parent),
            "SQLite DB (*.db *.sqlite *.sqlite3);;All Files (*)",
        )
        if not path:
            return
        self.db_path = Path(path)
        self.path_label.setText(str(self.db_path))
        self.reload()

    def reload(self) -> None:
        if not self.db_path.exists():
            self.status_label.setText("Database not found")
            self.channel_list.clear()
            return
        selected_channels = {
            item.data(Qt.UserRole)
            for item in self.channel_list.selectedItems()
            if item.data(Qt.UserRole)
        }
        existing_plot_channels = [
            list(plot.channels)
            for plot in getattr(self, "plot_widgets", [])
        ]
        had_plot_assignments = any(existing_plot_channels)
        previous_date = self.date_edit.date()
        try:
            with self._connect() as connection:
                channels = [
                    row["channel"]
                    for row in connection.execute(
                        """
                        SELECT channel
                        FROM readings
                        GROUP BY channel
                        ORDER BY channel
                        """
                    )
                ]
                count, start, end = connection.execute(
                    "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM readings"
                ).fetchone()
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Database Error", str(exc))
            return

        self.channel_list.clear()
        ordered = sorted(
            channels,
            key=lambda c: (CHANNEL_ORDER.index(c) if c in CHANNEL_ORDER else 999, c),
        )
        for channel in ordered:
            item = QListWidgetItem(CHANNEL_LABELS.get(channel, channel))
            item.setData(Qt.UserRole, channel)
            if channel in selected_channels:
                item.setSelected(True)
            self.channel_list.addItem(item)

        if not selected_channels:
            for row in range(min(4, self.channel_list.count())):
                self.channel_list.item(row).setSelected(True)

        available_channels = set(ordered)
        if had_plot_assignments:
            for plot, plot_channels in zip(self.plot_widgets, existing_plot_channels):
                plot.channels = [
                    channel for channel in plot_channels if channel in available_channels
                ]
        elif not self._has_loaded_defaults and getattr(self, "plot_widgets", None):
            for row in range(min(3, self.channel_list.count())):
                channel = self.channel_list.item(row).data(Qt.UserRole)
                if channel:
                    self.plot_widgets[row % len(self.plot_widgets)].channels.append(channel)
        self._has_loaded_defaults = True

        if start is not None and end is not None:
            data_start_date = QDateTime.fromSecsSinceEpoch(int(start)).date()
            data_end_date = QDateTime.fromSecsSinceEpoch(int(end)).date()
            if self._has_loaded_defaults and data_start_date <= previous_date <= data_end_date:
                self.date_edit.setDate(previous_date)
            else:
                self.date_edit.setDate(data_end_date)
            start_text = datetime.fromtimestamp(float(start)).strftime("%Y-%m-%d %H:%M:%S")
            end_text = datetime.fromtimestamp(float(end)).strftime("%Y-%m-%d %H:%M:%S")
            self.status_label.setText(f"{count:,} readings · {start_text} to {end_text}")
        else:
            self.status_label.setText("No readings")
        self.plot()

    def _jump_to_first(self) -> None:
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT MIN(timestamp) FROM readings").fetchone()
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Range Error", str(exc))
            return
        if row[0] is None:
            return
        self.date_edit.setDate(QDateTime.fromSecsSinceEpoch(int(row[0])).date())
        self.plot()

    def _jump_to_latest(self) -> None:
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT MAX(timestamp) FROM readings").fetchone()
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Range Error", str(exc))
            return
        if row[0] is None:
            return
        self.date_edit.setDate(QDateTime.fromSecsSinceEpoch(int(row[0])).date())
        self.plot()

    def plot(self) -> None:
        channels = []
        for plot_widget in self.plot_widgets:
            channels.extend(plot_widget.channels)
        channels = list(dict.fromkeys(channels))
        if not channels:
            for plot_widget in self.plot_widgets:
                plot_widget.set_series({})
            self._fill_summary({})
            self._last_plotted_sample_count = 0
            self._last_plot_time_range = None
            self.status_label.setText("No variables assigned")
            return

        selected_date = self.date_edit.date()
        start_dt = QDateTime(selected_date, QTime(0, 0, 0))
        start = start_dt.toSecsSinceEpoch()
        end = start + (24 * 3600) - 1

        placeholders = ", ".join("?" for _ in channels)
        query = f"""
            SELECT timestamp, channel, engineering_value, units
            FROM readings
            WHERE channel IN ({placeholders})
              AND timestamp >= ?
              AND timestamp <= ?
              AND engineering_value IS NOT NULL
            ORDER BY timestamp
        """
        params = [*channels, start, end]

        try:
            with self._connect() as connection:
                rows = connection.execute(query, params).fetchall()
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Query Error", str(exc))
            return

        self.last_rows = [
            (
                float(row["timestamp"]),
                str(row["channel"]),
                float(row["engineering_value"]),
                str(row["units"] or ""),
            )
            for row in rows
        ]
        all_series: dict[str, list[tuple[float, float]]] = {channel: [] for channel in channels}
        units_by_channel: dict[str, str] = {}
        for timestamp, channel, value, _units in self.last_rows:
            all_series.setdefault(channel, []).append((timestamp, value))
            if _units:
                units_by_channel[channel] = _units
        sample_limit = self.sample_limit.value()
        all_series = {
            channel: self._limit_points(values, sample_limit)
            for channel, values in all_series.items()
            if values
        }

        for plot_widget in self.plot_widgets:
            plot_widget.set_series({
                channel: all_series[channel]
                for channel in plot_widget.channels
                if channel in all_series
            })
            plot_widget.set_units(units_by_channel)
        self._fill_summary(all_series)
        day_text = selected_date.toString("yyyy-MM-dd")
        plotted_samples = sum(len(values) for values in all_series.values())
        plotted_times = [
            timestamp
            for values in all_series.values()
            for timestamp, _value in values
        ]
        self._last_plotted_sample_count = plotted_samples
        self._last_plot_time_range = (
            (min(plotted_times), max(plotted_times)) if plotted_times else None
        )
        self.status_label.setText(f"{plotted_samples:,} plotted samples · {day_text}")

    def _limit_points(
        self,
        points: list[tuple[float, float]],
        limit: int,
    ) -> list[tuple[float, float]]:
        if len(points) <= limit:
            return points
        if limit <= 1:
            return [points[-1]]
        step = (len(points) - 1) / (limit - 1)
        limited = [points[round(index * step)] for index in range(limit)]
        return limited

    def _fill_summary(self, series: dict[str, list[tuple[float, float]]]) -> None:
        if hasattr(self, "summary_meta_label"):
            channel_count = len(series)
            sample_count = sum(len(points) for points in series.values())
            if channel_count:
                self.summary_meta_label.setText(
                    f"{channel_count:,} channels · {sample_count:,} plotted samples"
                )
            else:
                self.summary_meta_label.setText("No plotted channels")
        self.summary_table.setRowCount(len(series))
        for row, (channel, points) in enumerate(series.items()):
            values = [point[1] for point in points]
            latest_time, latest_value = points[-1]
            latest_text = (
                f"{latest_value:.4g} @ "
                f"{datetime.fromtimestamp(latest_time).strftime('%H:%M:%S')}"
            )
            cells = [
                CHANNEL_LABELS.get(channel, channel),
                str(len(points)),
                f"{min(values):.4g}",
                f"{max(values):.4g}",
                latest_text,
            ]
            for column, text in enumerate(cells):
                self.summary_table.setItem(row, column, QTableWidgetItem(text))

    def export_pdf(self) -> None:
        self.export_pdf_button.setFocus(Qt.FocusReason.OtherFocusReason)
        if self._pdf_process is not None and self._pdf_process.poll() is None:
            self.status_label.setText("PDF export already running")
            return
        if not self.last_rows:
            self.plot()
        if not self.last_rows:
            self.status_label.setText("Plot data before exporting")
            return

        path = str(self._export_file_path(".pdf"))

        previous_tab = self.data_stack.currentIndex()
        changed_tab_for_capture = previous_tab != 0
        if changed_tab_for_capture:
            self.data_stack.setCurrentIndex(0)
            QApplication.processEvents()
        try:
            manifest = self._prepare_pdf_manifest(path)
        except Exception as exc:
            self.status_label.setText(f"PDF export failed: {exc}")
            return
        finally:
            if changed_tab_for_capture:
                self.data_stack.setCurrentIndex(previous_tab)

        self.export_pdf_button.setEnabled(False)
        self.status_label.setText("Exporting PDF...")
        self._pdf_output_path = path
        script_path = Path(__file__).with_name("export_history_pdf.py")
        try:
            self._pdf_process = subprocess.Popen(
                [sys.executable, str(script_path), "-"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(Path(__file__).resolve().parents[3]),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if self._pdf_process.stdin is not None:
                self._pdf_process.stdin.write(manifest)
                self._pdf_process.stdin.close()
        except Exception as exc:
            self._pdf_export_failed(str(exc))
            return
        self._pdf_poll_timer.start()

    def _prepare_pdf_manifest(self, output_path: str) -> str:
        color_mode = self._pdf_color_mode()
        image_data = [
            self._plot_image_data(plot_widget, index, color_mode)
            for index, plot_widget in enumerate(self.plot_widgets)
        ]
        return json.dumps(
            {
                "output_path": output_path,
                "header_text": self._pdf_header_text(),
                "image_data": image_data,
                "color_mode": color_mode,
                "marker_x_ratios": self._pdf_marker_x_ratios(),
            }
        )

    def _exports_dir(self) -> Path:
        path = Path(__file__).resolve().parents[3] / "Exports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _exports_path(self, filename: str) -> Path:
        return self._exports_dir() / filename

    def _export_file_path(self, suffix: str) -> Path:
        stem = self._export_stem()
        path = self._exports_path(f"{stem}{suffix}")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _export_stem(self) -> str:
        raw = self.export_name.text().strip() or "database_history"
        if raw.lower().endswith((".pdf", ".csv")):
            raw = Path(raw).stem
        safe = "".join(
            char if char.isalnum() or char in ("-", "_") else "_"
            for char in raw
        ).strip("_")
        safe = safe or "database_history"
        if safe != raw:
            self.export_name.setText(safe)
        return safe

    def _pdf_color_mode(self) -> str:
        selected = self.pdf_color_group.checkedButton()
        if selected is None:
            return "normal"
        return str(selected.property("pdfColorMode") or "normal")

    def _plot_image_data(self, plot_widget: HistoryPlotWidget, index: int, color_mode: str) -> str:
        image = self._plot_image(plot_widget, color_mode)
        data = QByteArray()
        buffer = QBuffer(data)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise RuntimeError(f"Could not prepare Plot {index + 1} for PDF export.")
        if not image.save(buffer, "PNG"):
            raise RuntimeError(f"Could not capture Plot {index + 1} for PDF export.")
        return base64.b64encode(bytes(data)).decode("ascii")

    def _plot_image(self, plot_widget: HistoryPlotWidget, color_mode: str) -> QImage:
        previous_mode = plot_widget._export_color_mode
        plot_widget.set_export_color_mode(color_mode)
        QApplication.processEvents()
        try:
            plot_widget.repaint()
            snapshot = plot_widget.grab()
            if snapshot.isNull():
                image = QImage(max(1, plot_widget.width()), max(1, plot_widget.height()), QImage.Format.Format_RGB32)
                image.fill(QColor("#ffffff" if color_mode in {"bw", "limited"} else "#0f172a"))
                return image
            return snapshot.toImage()
        finally:
            plot_widget.set_export_color_mode(previous_mode)

    def _pdf_marker_x_ratios(self) -> list[float]:
        for plot_widget in self.plot_widgets:
            ratios = plot_widget.marker_x_ratios()
            if ratios:
                unique = []
                for ratio in ratios:
                    if not any(abs(ratio - existing) < 0.001 for existing in unique):
                        unique.append(ratio)
                return unique
        return []

    def _pdf_header_text(self) -> str:
        selected_date = self.date_edit.date().toString("MM/dd/yyyy")
        sample_count = self._last_plotted_sample_count or len(self.last_rows)
        return (
            f"Date: {selected_date}    "
            f"Time: {self._pdf_time_text()}    "
            f"Number of Samples: {sample_count:,}"
        )

    def _poll_pdf_export(self) -> None:
        process = self._pdf_process
        if process is None:
            self._pdf_poll_timer.stop()
            return
        exit_code = process.poll()
        if exit_code is None:
            return
        self._pdf_poll_timer.stop()
        stderr = process.stderr.read() if process.stderr is not None else ""
        if exit_code == 0:
            self.status_label.setText("PDF export complete")
        else:
            self._pdf_export_failed(stderr.strip() or f"PDF export failed with exit code {exit_code}.")
            return
        self._pdf_export_cleaned_up()

    def _pdf_export_failed(self, message: str) -> None:
        self.status_label.setText("PDF export failed")
        if message:
            self.status_label.setToolTip(message)
        self._pdf_export_cleaned_up()

    def _pdf_export_cleaned_up(self) -> None:
        self._pdf_poll_timer.stop()
        self.export_pdf_button.setEnabled(True)
        self._pdf_process = None
        self._pdf_output_path = ""

    def _pdf_time_text(self) -> str:
        if self._last_plot_time_range is None:
            return "--"
        start, end = self._last_plot_time_range
        start_text = self._format_standard_time(datetime.fromtimestamp(start))
        end_text = self._format_standard_time(datetime.fromtimestamp(end))
        if start_text == end_text:
            return start_text
        return f"{start_text} - {end_text}"

    def _format_standard_time(self, value: datetime) -> str:
        if value.minute == 0:
            text = value.strftime("%I %p")
        else:
            text = value.strftime("%I:%M %p")
        return text.lstrip("0")

    def export_csv(self) -> None:
        if not self.last_rows:
            self.status_label.setText("Plot data before exporting")
            return
        path = self._export_file_path(".csv")
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["timestamp", "datetime", "channel", "engineering_value", "units"])
            for timestamp, channel, value, units in self.last_rows:
                writer.writerow([
                    timestamp,
                    datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
                    channel,
                    value,
                    units,
                ])
        self.status_label.setText(f"CSV exported: {path.name}")
