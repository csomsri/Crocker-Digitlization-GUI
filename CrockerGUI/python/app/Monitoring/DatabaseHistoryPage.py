from __future__ import annotations

import csv
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QDateTime
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QDateTimeEdit,
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


class HistoryPlotWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.series: dict[str, list[tuple[float, float]]] = {}
        self.setObjectName("chartPlaceholder")
        self.setMinimumHeight(300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_series(self, series: dict[str, list[tuple[float, float]]]) -> None:
        self.series = series
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0f172a"))

        plot = QRectF(self.rect()).adjusted(64.0, 28.0, -24.0, -48.0)
        if plot.width() <= 8 or plot.height() <= 8:
            return

        painter.setPen(QPen(QColor(51, 65, 85, 150), 1))
        for step in range(5):
            y = plot.top() + plot.height() * step / 4
            x = plot.left() + plot.width() * step / 4
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
        painter.setPen(QPen(QColor("#475569"), 1))
        painter.drawRect(plot)

        all_points = [point for values in self.series.values() for point in values]
        if not all_points:
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(plot, Qt.AlignCenter, "Select channels and plot database history")
            return

        times = [point[0] for point in all_points]
        values = [point[1] for point in all_points]
        start, end = min(times), max(times)
        low, high = min(values), max(values)
        if end <= start:
            end = start + 1.0
        if high <= low:
            high = low + 1.0

        painter.setPen(QColor("#94a3b8"))
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
        painter.drawText(
            QRectF(plot.left(), plot.bottom() + 24, plot.width(), 20),
            Qt.AlignCenter,
            "Time",
        )

        for index, (channel, points) in enumerate(self.series.items()):
            if len(points) < 2:
                continue
            color = PLOT_COLORS[index % len(PLOT_COLORS)]
            path = QPainterPath(self._plot_point(plot, points[0], start, end, low, high))
            for point in points[1:]:
                path.lineTo(self._plot_point(plot, point, start, end, low, high))
            painter.setPen(QPen(color, 2))
            painter.drawPath(path)

        legend_x = plot.left() + 12
        legend_y = plot.top() + 10
        for index, channel in enumerate(self.series):
            color = PLOT_COLORS[index % len(PLOT_COLORS)]
            y = legend_y + index * 18
            painter.setPen(QPen(color, 2))
            painter.drawLine(QPointF(legend_x, y + 8), QPointF(legend_x + 22, y + 8))
            painter.setPen(QColor("#cbd5e1"))
            painter.drawText(
                QRectF(legend_x + 30, y, 210, 18),
                Qt.AlignLeft | Qt.AlignVCenter,
                CHANNEL_LABELS.get(channel, channel),
            )

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
    ) -> None:
        super().__init__(
            "Database History",
            "SQLite readings history",
            "Back to Monitoring",
            go_back,
        )
        self.db_path = self._resolve_db_path(Path(db_path))
        self.last_rows: list[tuple[float, str, float, str]] = []

        _, panel_layout = self.add_workspace()

        top = QHBoxLayout()
        self.path_label = QLabel(str(self.db_path))
        self.path_label.setObjectName("workspaceBody")
        self.status_label = QLabel("")
        self.status_label.setObjectName("workspaceBody")
        browse_button = QPushButton("Open DB")
        reload_button = QPushButton("Reload")
        browse_button.clicked.connect(self._choose_db)
        reload_button.clicked.connect(self.reload)
        for button in (browse_button, reload_button):
            button.setCursor(Qt.PointingHandCursor)
        top.addWidget(QLabel("Database:"))
        top.addWidget(self.path_label, 1)
        top.addWidget(browse_button)
        top.addWidget(reload_button)
        panel_layout.addLayout(top)

        range_row = QHBoxLayout()
        now = QDateTime.currentDateTime()
        self.start_edit = QDateTimeEdit(now.addSecs(-24 * 3600))
        self.end_edit = QDateTimeEdit(now)
        for editor in (self.start_edit, self.end_edit):
            editor.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
            editor.setCalendarPopup(True)
        range_row.addWidget(QLabel("Start:"))
        range_row.addWidget(self.start_edit)
        range_row.addWidget(QLabel("End:"))
        range_row.addWidget(self.end_edit)
        for label, hours in (("1h", 1), ("6h", 6), ("24h", 24), ("7d", 24 * 7)):
            button = QPushButton(label)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda checked=False, h=hours: self._quick_range(h))
            range_row.addWidget(button)
        data_range = QPushButton("Data Range")
        latest = QPushButton("Latest 24h")
        data_range.clicked.connect(self._fill_data_range)
        latest.clicked.connect(lambda checked=False: self._jump_to_latest(24))
        for button in (data_range, latest):
            button.setCursor(Qt.PointingHandCursor)
            range_row.addWidget(button)
        panel_layout.addLayout(range_row)

        body = QHBoxLayout()
        left = QFrame()
        left.setObjectName("workspace")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.addWidget(QLabel("Channels"))
        self.channel_list = QListWidget()
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
        action_row = QHBoxLayout()
        plot_button = QPushButton("Plot")
        export_button = QPushButton("Export CSV")
        plot_button.clicked.connect(self.plot)
        export_button.clicked.connect(self.export_csv)
        for button in (plot_button, export_button):
            button.setCursor(Qt.PointingHandCursor)
            action_row.addWidget(button)
        action_row.addWidget(self.status_label, 1)
        action_row.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        right.addLayout(action_row)

        self.plot_widget = HistoryPlotWidget()
        right.addWidget(self.plot_widget, 2)

        self.summary_table = QTableWidget(0, 5)
        self.summary_table.setHorizontalHeaderLabels(
            ["Channel", "Samples", "Min", "Max", "Latest"]
        )
        right.addWidget(self.summary_table, 1)
        body.addLayout(right, 4)
        panel_layout.addLayout(body, 1)

        self.reload()

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
            self.channel_list.addItem(item)
        for row in range(min(4, self.channel_list.count())):
            self.channel_list.item(row).setSelected(True)

        if start is not None and end is not None:
            self._set_range(float(start), float(end))
            start_text = datetime.fromtimestamp(float(start)).strftime("%Y-%m-%d %H:%M:%S")
            end_text = datetime.fromtimestamp(float(end)).strftime("%Y-%m-%d %H:%M:%S")
            self.status_label.setText(f"{count} readings | {start_text} to {end_text}")
        else:
            self.status_label.setText("No readings")

    def _selected_channels(self) -> list[str]:
        return [
            item.data(Qt.UserRole)
            for item in self.channel_list.selectedItems()
            if item.data(Qt.UserRole)
        ]

    def _quick_range(self, hours: int) -> None:
        end = QDateTime.currentDateTime()
        self.end_edit.setDateTime(end)
        self.start_edit.setDateTime(end.addSecs(-hours * 3600))

    def _fill_data_range(self) -> None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT MIN(timestamp), MAX(timestamp) FROM readings"
                ).fetchone()
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Range Error", str(exc))
            return
        if row[0] is None or row[1] is None:
            return
        self._set_range(float(row[0]), float(row[1]))

    def _jump_to_latest(self, hours: int) -> None:
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT MAX(timestamp) FROM readings").fetchone()
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Range Error", str(exc))
            return
        if row[0] is None:
            return
        end_dt = datetime.fromtimestamp(float(row[0]))
        start_dt = end_dt - timedelta(hours=hours)
        self.start_edit.setDateTime(QDateTime.fromSecsSinceEpoch(int(start_dt.timestamp())))
        self.end_edit.setDateTime(QDateTime.fromSecsSinceEpoch(int(end_dt.timestamp())))

    def _set_range(self, start: float, end: float) -> None:
        self.start_edit.setDateTime(QDateTime.fromSecsSinceEpoch(int(start)))
        self.end_edit.setDateTime(QDateTime.fromSecsSinceEpoch(int(end)))

    def plot(self) -> None:
        channels = self._selected_channels()
        if not channels:
            QMessageBox.warning(self, "No Channels", "Select at least one channel.")
            return

        start = self.start_edit.dateTime().toSecsSinceEpoch()
        end = self.end_edit.dateTime().toSecsSinceEpoch()
        if end < start:
            start, end = end, start

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
        series: dict[str, list[tuple[float, float]]] = {channel: [] for channel in channels}
        for timestamp, channel, value, _units in self.last_rows:
            series.setdefault(channel, []).append((timestamp, value))
        series = {channel: values for channel, values in series.items() if values}

        self.plot_widget.set_series(series)
        self._fill_summary(series)
        self.status_label.setText(f"Plotted {len(self.last_rows)} samples")

    def _fill_summary(self, series: dict[str, list[tuple[float, float]]]) -> None:
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

    def export_csv(self) -> None:
        if not self.last_rows:
            QMessageBox.information(self, "Export CSV", "Plot data before exporting.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export database history",
            "database_history.csv",
            "CSV (*.csv)",
        )
        if not path:
            return
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
