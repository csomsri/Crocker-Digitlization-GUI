"""Snapshot capture and category-based recall using the application's dialog surface."""
from datetime import datetime
import json
import sqlite3
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialogButtonBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)
from python.app.widgets.AppDialogs import AppDialog, AppFileDialog
from python.app.widgets.PidDialog import setup_pid_dialog
from python.app.widgets.ScreenSafeComboBox import ScreenSafeComboBox


def local_time(value):
    return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def populate_tree(tree, categories):
    tree.clear()
    def add(parent, key, value):
        container = isinstance(value, (dict, list))
        text = "" if container and value else ("Unavailable" if value is None or container else str(value))
        item = QTreeWidgetItem(parent, [str(key), text])
        if isinstance(value, dict):
            for name, child in value.items():
                add(item, name, child)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                add(item, f"Reading {index + 1}", child)
        return item
    for category, values in categories.items():
        add(tree, category, values).setExpanded(True)
    tree.resizeColumnToContents(0)


def value_tree():
    tree = QTreeWidget()
    tree.setHeaderLabels(["Captured value", "Reading"])
    tree.setAlternatingRowColors(True)
    tree.setMinimumHeight(180)
    tree.setStyleSheet("QTreeWidget { background: #142235; alternate-background-color: #1b2c42; color: #e7eef8; border: 1px solid #34465d; } QTreeWidget::item { padding: 4px; }")
    return tree


class CaptureDialog(AppDialog):
    def __init__(self, parent, store, record):
        super().__init__(parent)
        self.store, self.record = store, record
        self.resize(720, 620)
        layout = setup_pid_dialog(self, "Snapshot", window_controls=False, resize_grip=False)
        layout.addWidget(QLabel("Save all readings. Naming is optional."))
        self.name = QLineEdit()
        self.name.setMaxLength(100)
        self.name.setPlaceholderText(store.next_name())
        self.name.setAccessibleName("Snapshot name")
        layout.addWidget(self.name)
        telemetry = record["telemetry"]
        source = "Simulation" if telemetry.get("simulated") else record["mode"].upper()
        layout.addWidget(QLabel(f"{local_time(record['captured_at'])}  •  {source}  •  {telemetry.get('connection', 'Unknown')}"))
        age = max(0, time.time() - float(telemetry.get("timestamp") or 0))
        freshness = QLabel(f"Readings are {age:.1f} s old at capture." if age > 2 else "Latest received readings")
        layout.addWidget(freshness)
        tree = value_tree()
        populate_tree(tree, record["categories"])
        layout.addWidget(tree, 1)
        note = QLabel("All available telemetry is included. Unavailable readings are saved as missing.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        try:
            self.saved_id = self.store.save(self.record, self.name.text())
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class RecallDialog(AppDialog):
    def __init__(self, parent, store, recall):
        super().__init__(parent)
        self.store, self.recall = store, recall
        self.record = None
        self.resize(900, 680)
        layout = setup_pid_dialog(self, "Recall snapshot", window_controls=False, resize_grip=False)
        instructions = QLabel("Choose a saved snapshot and the groups to recall. Press Apply afterward to send targets.")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        filters = QHBoxLayout()
        self.date = ScreenSafeComboBox()
        self.date.addItem("All dates", "")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search snapshot name")
        self.search.setAccessibleName("Search snapshot name")
        filters.addWidget(self.date)
        filters.addWidget(self.search, 1)
        layout.addLayout(filters)
        self.entries = store.list()
        for day in sorted({local_time(row[2])[:10] for row in self.entries}, reverse=True):
            self.date.addItem(day, day)
        self.snapshots = ScreenSafeComboBox()
        self.snapshots.setAccessibleName("Saved snapshot")
        layout.addWidget(self.snapshots)
        self.metadata = QLabel()
        self.metadata.setWordWrap(True)
        layout.addWidget(self.metadata)
        body = QSplitter(Qt.Horizontal)
        selection = QWidget()
        self.category_layout = QVBoxLayout(selection)
        self.category_layout.setContentsMargins(0, 0, 12, 0)
        self.checks = {}
        body.addWidget(selection)
        self.preview = value_tree()
        body.addWidget(self.preview)
        body.setStretchFactor(1, 1)
        layout.addWidget(body, 1)
        note = QLabel("Trim coils and auxiliary magnets → Target fields. Other categories → saved reference table. Actual readings stay live.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        footer = QHBoxLayout()
        self.export = QPushButton("Export snapshot…")
        self.export.setToolTip("Save a copy of this snapshot to a file.")
        self.export.clicked.connect(self.export_json)
        footer.addWidget(self.export)
        footer.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self.recall_button = QPushButton("Recall selected")
        self.recall_button.clicked.connect(self.apply_recall)
        footer.addWidget(self.recall_button)
        layout.addLayout(footer)
        self.date.currentIndexChanged.connect(self.filter_entries)
        self.search.textChanged.connect(self.filter_entries)
        self.snapshots.currentIndexChanged.connect(self.load_selected)
        self.filter_entries()

    def filter_entries(self, *_):
        self.snapshots.blockSignals(True)
        self.snapshots.clear()
        for identity, name, stamp in self.entries:
            if self.date.currentData() and local_time(stamp)[:10] != self.date.currentData():
                continue
            if self.search.text().casefold() not in name.casefold():
                continue
            self.snapshots.addItem(f"{name}  ·  {local_time(stamp)}", identity)
        self.snapshots.blockSignals(False)
        self.load_selected()

    def load_selected(self, *_):
        self.record = None
        self.error.clear()
        self.metadata.clear()
        while self.category_layout.count():
            item = self.category_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.checks.clear()
        identity = self.snapshots.currentData()
        if identity is not None:
            try:
                self.record = self.store.load(identity)
                telemetry = self.record["telemetry"]
                source = "Simulation" if telemetry.get("simulated") else self.record["mode"].upper()
                self.metadata.setText(f"{source} • {telemetry.get('connection', 'Unknown')} at capture")
            except (ValueError, OSError, sqlite3.Error) as exc:
                self.error.setText(str(exc))
        for category in (self.record or {}).get("categories", {}):
            check = QCheckBox(category)
            check.setChecked(category == "Trim Coils")
            check.toggled.connect(self.refresh_preview)
            self.checks[category] = check
            self.category_layout.addWidget(check)
        self.category_layout.addStretch()
        self.export.setEnabled(self.record is not None)
        if self.record is None and not self.error.text():
            self.error.setText("No snapshots found. Capture one with Snapshot.")
        self.refresh_preview()

    def selected_categories(self):
        return {name: self.record["categories"][name] for name, check in self.checks.items() if check.isChecked()}

    def refresh_preview(self, *_):
        selected = self.selected_categories()
        populate_tree(self.preview, selected)
        self.recall_button.setEnabled(bool(selected))

    def apply_recall(self):
        try:
            self.recall(self.record, self.selected_categories())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()

    def export_json(self):
        path, _ = AppFileDialog.getSaveFileName(self, "Export snapshot", "snapshot.json", "Snapshot files (*.json)")
        if path:
            try:
                Path(path).write_text(json.dumps(self.record, indent=2, allow_nan=False), encoding="utf-8")
            except OSError as exc:
                self.error.setText(str(exc))
