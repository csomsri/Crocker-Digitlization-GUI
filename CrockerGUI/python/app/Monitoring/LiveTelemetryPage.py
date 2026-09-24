"""Read-only monitoring of the shared LabVIEW receiver; never opens a control socket."""
from collections import deque
import csv
import math
from pathlib import Path
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,
                              QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QWidget)
from python.app.PageShell import DetailPage
from python.app.widgets.AppDialogs import AppFileDialog, AppMessageBox
from python.app.widgets.MonitoringPlotState import monitoring_plot_state
from python.app.Monitoring.TelemetryFields import MONITOR_FIELDS, reading


class TelemetryTrend(QWidget):
    def __init__(self):
        super().__init__()
        self.samples = []
        self.caption = "Select a reading"
        self.setMinimumSize(280, 210)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#111827"))
        painter.setPen(QColor("#cbd5e1"))
        painter.drawText(14, 24, self.caption)
        plot = QRectF(80, 45, max(1, self.width() - 102), max(1, self.height() - 85))
        painter.setPen(QPen(QColor("#334155"), 1))
        painter.drawRect(plot)
        valid = [(stamp, value) for stamp, value in self.samples if value is not None]
        if not valid:
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(plot, Qt.AlignCenter, "Waiting for readings")
            return
        low, high = min(v for _, v in valid), max(v for _, v in valid)
        pad = max((high - low) * .08, abs(high) * .01, 1e-12)
        low, high = low - pad, high + pad
        end = self.samples[-1][0]
        start = min(self.samples[0][0], end - 1)
        painter.setPen(QColor("#94a3b8"))
        painter.drawText(5, 52, f"{high:.3g}")
        painter.drawText(5, int(plot.bottom()), f"{low:.3g}")
        painter.drawText(int(plot.left()), self.height() - 12, f"{start - end:.0f} s")
        painter.drawText(int(plot.right()) - 60, self.height() - 12, "Latest")
        path = QPainterPath()
        connected = False
        for stamp, value in self.samples:
            if value is None:
                connected = False
                continue
            point = QPointF(plot.left() + (stamp - start) / (end - start) * plot.width(),
                            plot.bottom() - (value - low) / (high - low) * plot.height())
            if connected:
                path.lineTo(point)
            else:
                path.moveTo(point)
            connected = True
        painter.setPen(QPen(QColor("#60a5fa"), 2))
        painter.drawPath(path)


class LiveTelemetryPage(DetailPage):
    def __init__(self, title, go_back):
        super().__init__(title, "Live LabVIEW readings", "Back to Monitoring", go_back)
        self.monitor_title = title
        self.specs = MONITOR_FIELDS[title]
        self.channels = [spec[0] for spec in self.specs]
        self.monitor_plot_state = monitoring_plot_state()
        self.snapshot_source = None
        self.paused = False
        self.last_identity = None
        self.last_timestamp = None
        self.history = {name: deque(maxlen=1200) for name in self.channels}
        self.latest = {}
        _, layout = self.add_workspace()
        controls = QHBoxLayout()
        self.status = QLabel("Waiting for LabVIEW")
        self.status.setStyleSheet("color: #cbd5e1;")
        controls.addWidget(self.status, 1)
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.toggle_pause)
        controls.addWidget(self.pause_button)
        self.export_button = QPushButton("Export readings…")
        self.export_button.clicked.connect(self.export_readings)
        controls.addWidget(self.export_button)
        layout.addLayout(controls)
        note = QLabel("Numbered readings follow the LabVIEW packet order. Raw values await device names and calibration.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #94a3b8;")
        layout.addWidget(note)
        split = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(len(self.specs), 4)
        self.table.setHorizontalHeaderLabels(["Reading", "Actual", "Units", "Status"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for row, (name, _, _, units) in enumerate(self.specs):
            for column, text in enumerate((name, "—", units, "Unavailable")):
                self.table.setItem(row, column, QTableWidgetItem(text))
        split.addWidget(self.table)
        self.trend = TelemetryTrend()
        split.addWidget(self.trend)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setSizes([520, 650])
        layout.addWidget(split, 1)
        self.table.currentCellChanged.connect(self.refresh_trend)
        self.table.selectRow(0)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def set_snapshot_source(self, source):
        self.snapshot_source = source

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_button.setText("Resume" if self.paused else "Pause")
        if self.paused:
            self.status.setText("Paused — displayed readings are frozen")
        else:
            self.refresh()

    def refresh(self):
        if self.paused:
            return
        try:
            snapshot = self.snapshot_source() if self.snapshot_source else None
        except Exception:
            snapshot = None
        snapshot = snapshot or {}
        stamp = snapshot.get("timestamp")
        valid_stamp = isinstance(stamp, (int, float)) and math.isfinite(stamp) and stamp > 0
        age = max(0, time.time() - stamp) if valid_stamp else float("inf")
        connection = str(snapshot.get("connection", "Disconnected"))
        fresh = age <= 2 and connection.lower() == "connected"
        self.status.setText(f"{'Simulation' if snapshot.get('simulated') else 'LabVIEW'} · {connection} · "
                            + (f"{age:.1f} s since reading" if valid_stamp else "Waiting for readings"))
        identity = (snapshot.get("sequence_number"), stamp)
        new_sample = valid_stamp and identity != self.last_identity
        if new_sample and self.last_timestamp is not None and stamp < self.last_timestamp:
            for samples in self.history.values():
                samples.clear()
        for row, spec in enumerate(self.specs):
            name = spec[0]
            value = reading(snapshot, spec) if valid_stamp else None
            state = "Unavailable" if value is None else ("Live" if fresh else "Stale")
            self.latest[name] = (value, spec[3], state, stamp if valid_stamp else None)
            self.table.item(row, 1).setText("—" if value is None else f"{value:.6g}")
            self.table.item(row, 3).setText(state)
            self.table.setRowHidden(row, not self.monitor_plot_state.is_enabled(self.monitor_title, name))
            if new_sample:
                self.history[name].append((stamp, value if fresh else None))
        if new_sample:
            self.last_identity, self.last_timestamp = identity, stamp
        if self.table.currentRow() >= 0 and self.table.isRowHidden(self.table.currentRow()):
            self.table.clearSelection()
            for row in range(len(self.specs)):
                if not self.table.isRowHidden(row):
                    self.table.selectRow(row)
                    break
        self.refresh_trend()

    def refresh_trend(self, *_):
        row = self.table.currentRow()
        if row < 0 or self.table.isRowHidden(row):
            self.trend.samples, self.trend.caption = [], "Enable a reading in Field Ctrl"
        else:
            name, _, _, units = self.specs[row]
            self.trend.samples = list(self.history[name])
            self.trend.caption = f"{name} ({units}) • recent received samples"
        self.trend.update()

    def export_readings(self):
        path, _ = AppFileDialog.getSaveFileName(self, "Export displayed readings", "readings.csv", "Spreadsheet files (*.csv)")
        if not path:
            return
        try:
            with Path(path).open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Reading", "Actual", "Units", "Status", "Unix timestamp (seconds)"])
                for name, (value, units, state, stamp) in self.latest.items():
                    writer.writerow([name, value, units, state, stamp])
        except OSError as exc:
            AppMessageBox.warning(self, "Export readings", str(exc))
