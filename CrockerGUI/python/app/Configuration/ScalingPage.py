from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from python.app.PageShell import DetailPage
from python.app.widgets.MagneticFieldWidgets import CHANNEL_NAMES


class ScalingPage(DetailPage):
    CONFIG_RELATIVE_PATH = Path("config") / "trim_coil_scaling.json"
    CHANNEL_KEYS = [f"ch{index}" for index in range(1, 13)] + ["main_magnet", "centering_beam"]
    COLUMNS = (
        "Channel",
        "Enabled",
        "Raw to Eng Gain",
        "Raw to Eng Offset",
        "Eng to Raw Gain",
        "Eng to Raw Offset",
    )

    def __init__(
        self,
        go_back: Callable[[], None],
        apply_live_scaling: Callable[[dict[str, object]], bool] | None = None,
    ) -> None:
        super().__init__(
            "Scaling",
            "Scaling and calibration setup",
            "Back to Configuration",
            go_back,
        )

        self.config_path = Path(__file__).resolve().parents[3] / self.CONFIG_RELATIVE_PATH
        self._apply_live_scaling = apply_live_scaling
        self.enabled_boxes: list[QCheckBox] = []
        self.raw_to_eng_gain: list[QDoubleSpinBox] = []
        self.raw_to_eng_offset: list[QDoubleSpinBox] = []
        self.eng_to_raw_gain: list[QDoubleSpinBox] = []
        self.eng_to_raw_offset: list[QDoubleSpinBox] = []

        _, workspace = self.add_workspace()
        workspace.setContentsMargins(10, 8, 10, 10)
        workspace.setSpacing(10)

        heading = QLabel("TRIM COIL SCALING")
        heading.setObjectName("settingsHeading")
        workspace.addWidget(heading)

        self.status_label = QLabel()
        self.status_label.setObjectName("settingsDescription")
        self.status_label.setWordWrap(True)
        workspace.addWidget(self.status_label)

        self.table = QTableWidget(len(CHANNEL_NAMES), len(self.COLUMNS))
        self.table.setObjectName("scalingTable")
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        workspace.addWidget(self.table, 1)

        self._build_rows()

        actions = QHBoxLayout()
        for label, handler in (
            ("Load", self._load_scaling),
            ("Save + Apply", self._save_scaling),
            ("Apply File", self._apply_file_scaling),
            ("Reset Identity", self._reset_identity),
        ):
            button = QPushButton(label)
            button.setObjectName("applySettingsButton" if label == "Save + Apply" else "fieldBulk")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(handler)
            actions.addWidget(button)
        actions.addStretch(1)
        workspace.addLayout(actions)

        self._load_scaling()

    def _build_rows(self) -> None:
        for row, channel in enumerate(CHANNEL_NAMES):
            name_item = QTableWidgetItem(channel)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 0, name_item)

            enabled = QCheckBox()
            enabled.setObjectName("toggleRow")
            enabled.setToolTip(f"Enable scaling for {channel}")
            self.table.setCellWidget(row, 1, self._centered_widget(enabled))
            self.enabled_boxes.append(enabled)

            for column, collection in (
                (2, self.raw_to_eng_gain),
                (3, self.raw_to_eng_offset),
                (4, self.eng_to_raw_gain),
                (5, self.eng_to_raw_offset),
            ):
                spinbox = self._make_scaling_spinbox()
                self.table.setCellWidget(row, column, spinbox)
                collection.append(spinbox)

    def _make_scaling_spinbox(self) -> QDoubleSpinBox:
        spinbox = QDoubleSpinBox()
        spinbox.setDecimals(10)
        spinbox.setRange(-1.0e9, 1.0e9)
        spinbox.setSingleStep(0.01)
        spinbox.setKeyboardTracking(False)
        return spinbox

    def _centered_widget(self, child: QWidget) -> QWidget:
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        layout.addWidget(child)
        layout.addStretch(1)
        return frame

    def _identity_scaling(self) -> dict[str, list[float] | list[bool]]:
        count = len(CHANNEL_NAMES)
        return {
            "raw_to_eng_gain": [1.0] * count,
            "raw_to_eng_offset": [0.0] * count,
            "eng_to_raw_gain": [1.0] * count,
            "eng_to_raw_offset": [0.0] * count,
            "enabled": [False] * count,
        }

    def _load_scaling(self) -> None:
        scaling = self._identity_scaling()
        if self.config_path.exists():
            try:
                with self.config_path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                scaling = self._normalize_scaling(data)
                self.status_label.setText(f"Loaded {self.config_path}")
            except Exception as exc:
                self.status_label.setText(f"Could not load scaling file: {exc}")
        else:
            self.status_label.setText(f"No active scaling file. Save creates {self.config_path}")
        self._apply_scaling_to_table(scaling)

    def _save_scaling(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        scaling = self._read_scaling_from_table()
        with self.config_path.open("w", encoding="utf-8") as handle:
            json.dump(scaling, handle, indent=2)
            handle.write("\n")
        enabled_count = sum(1 for enabled in scaling["enabled"] if enabled)
        live_status = ""
        if self._apply_live_scaling is not None:
            live_status = " Live backend updated." if self._apply_live_scaling(scaling) else " Live backend not active."
        self.status_label.setText(
            f"Saved {enabled_count}/{len(CHANNEL_NAMES)} enabled channels to {self.config_path}.{live_status}"
        )

    def _apply_file_scaling(self) -> None:
        if self._apply_live_scaling is None:
            self.status_label.setText("No live Field Ctrl backend is available.")
            return
        if not self.config_path.exists():
            self.status_label.setText(f"No active scaling file at {self.config_path}")
            return

        try:
            with self.config_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("scaling file must contain a JSON object")
        except Exception as exc:
            self.status_label.setText(f"Could not apply scaling file: {exc}")
            return

        live_status = "Live backend updated." if self._apply_live_scaling(data) else "Live backend not active."
        self.status_label.setText(f"Applied {self.config_path}. {live_status}")

    def _reset_identity(self) -> None:
        self._apply_scaling_to_table(self._identity_scaling())
        self.status_label.setText("Reset table to identity scaling. Save to make it active.")

    def _normalize_scaling(self, data: object) -> dict[str, list[float] | list[bool]]:
        scaling = self._identity_scaling()
        if not isinstance(data, dict):
            raise ValueError("scaling file must contain a JSON object")

        array_keys = {"raw_to_eng_gain", "raw_to_eng_offset", "eng_to_raw_gain", "eng_to_raw_offset", "enabled"}
        if array_keys.intersection(data):
            for key in array_keys:
                if key not in data:
                    continue
                values = data[key]
                if not isinstance(values, list) or len(values) != len(CHANNEL_NAMES):
                    raise ValueError(f"{key} must contain {len(CHANNEL_NAMES)} entries")
                scaling[key] = [bool(value) for value in values] if key == "enabled" else [float(value) for value in values]
            return scaling

        for index, key in enumerate(self.CHANNEL_KEYS):
            entry = data.get(key)
            if not isinstance(entry, dict):
                continue
            raw_to_eng = entry.get("raw_to_eng")
            eng_to_raw = entry.get("eng_to_raw")
            enabled = bool(entry.get("enabled", True)) and isinstance(raw_to_eng, dict) and isinstance(eng_to_raw, dict)
            scaling["enabled"][index] = enabled
            if not enabled:
                continue
            scaling["raw_to_eng_gain"][index] = float(raw_to_eng.get("gain", 1.0))
            scaling["raw_to_eng_offset"][index] = float(raw_to_eng.get("offset", 0.0))
            scaling["eng_to_raw_gain"][index] = float(eng_to_raw.get("gain", 1.0))
            scaling["eng_to_raw_offset"][index] = float(eng_to_raw.get("offset", 0.0))
        return scaling

    def _apply_scaling_to_table(self, scaling: dict[str, list[float] | list[bool]]) -> None:
        for index in range(len(CHANNEL_NAMES)):
            self.enabled_boxes[index].setChecked(bool(scaling["enabled"][index]))
            self.raw_to_eng_gain[index].setValue(float(scaling["raw_to_eng_gain"][index]))
            self.raw_to_eng_offset[index].setValue(float(scaling["raw_to_eng_offset"][index]))
            self.eng_to_raw_gain[index].setValue(float(scaling["eng_to_raw_gain"][index]))
            self.eng_to_raw_offset[index].setValue(float(scaling["eng_to_raw_offset"][index]))

    def _read_scaling_from_table(self) -> dict[str, list[float] | list[bool]]:
        return {
            "raw_to_eng_gain": [spinbox.value() for spinbox in self.raw_to_eng_gain],
            "raw_to_eng_offset": [spinbox.value() for spinbox in self.raw_to_eng_offset],
            "eng_to_raw_gain": [spinbox.value() for spinbox in self.eng_to_raw_gain],
            "eng_to_raw_offset": [spinbox.value() for spinbox in self.eng_to_raw_offset],
            "enabled": [box.isChecked() for box in self.enabled_boxes],
        }
