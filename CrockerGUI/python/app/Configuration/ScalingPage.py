from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
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
        self._loading = False
        self._dirty = False

        _, workspace = self.add_workspace()
        workspace.setContentsMargins(10, 8, 10, 10)
        workspace.setSpacing(10)

        heading = QLabel("TRIM COIL SCALING")
        heading.setObjectName("settingsHeading")
        workspace.addWidget(heading)

        summary = QFrame()
        summary.setObjectName("displayModePanel")
        summary_layout = QGridLayout(summary)
        summary_layout.setContentsMargins(14, 10, 14, 10)
        summary_layout.setSpacing(8)
        self.enabled_summary = QLabel("0 / 14\nENABLED")
        self.enabled_summary.setObjectName("scalingSummary")
        self.validation_summary = QLabel("READY\nVALIDATION")
        self.validation_summary.setObjectName("scalingSummary")
        self.change_summary = QLabel("SAVED\nSTATE")
        self.change_summary.setObjectName("scalingSummary")
        summary_layout.addWidget(self.enabled_summary, 0, 0)
        summary_layout.addWidget(self.validation_summary, 0, 1)
        summary_layout.addWidget(self.change_summary, 0, 2)
        workspace.addWidget(summary)

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

        bulk_actions = QHBoxLayout()
        bulk_label = QLabel("CHANNEL ENABLEMENT")
        bulk_label.setObjectName("monitorAssignmentLabel")
        bulk_actions.addWidget(bulk_label)
        for label, enabled in (("Enable All", True), ("Disable All", False)):
            button = QPushButton(label)
            button.setObjectName("fieldBulk")
            button.clicked.connect(
                lambda checked=False, value=enabled: self._set_all_enabled(value)
            )
            bulk_actions.addWidget(button)
        bulk_actions.addStretch(1)
        workspace.addLayout(bulk_actions)

        actions = QHBoxLayout()
        for label, handler in (
            ("Reload Saved", self._load_scaling),
            ("Apply Draft", self._apply_draft_scaling),
            ("Save + Apply", self._save_scaling),
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
            enabled.toggled.connect(self._mark_dirty)
            self.table.setCellWidget(row, 1, self._centered_widget(enabled))
            self.enabled_boxes.append(enabled)

            for column, collection in (
                (2, self.raw_to_eng_gain),
                (3, self.raw_to_eng_offset),
                (4, self.eng_to_raw_gain),
                (5, self.eng_to_raw_offset),
            ):
                spinbox = self._make_scaling_spinbox()
                spinbox.valueChanged.connect(self._mark_dirty)
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
        self._set_clean()

    def _save_scaling(self) -> None:
        scaling = self._read_scaling_from_table()
        errors = self._validation_errors(scaling)
        if errors:
            self.status_label.setText("Cannot save: " + "; ".join(errors[:3]))
            self._refresh_summary()
            return
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
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

        self._set_clean()

    def _apply_draft_scaling(self) -> None:
        scaling = self._read_scaling_from_table()
        errors = self._validation_errors(scaling)
        if errors:
            self.status_label.setText("Cannot apply draft: " + "; ".join(errors[:3]))
            self._refresh_summary()
            return
        if self._apply_live_scaling is None:
            self.status_label.setText("No live Field Ctrl backend is available.")
            return
        applied = self._apply_live_scaling(scaling)
        self.status_label.setText(
            "Draft applied to the live backend; it has not been saved."
            if applied else "Live Field Ctrl backend is not active."
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
        self._mark_dirty()

    def _set_all_enabled(self, enabled: bool) -> None:
        for box in self.enabled_boxes:
            box.setChecked(enabled)
        self.status_label.setText(
            "All channels enabled in the draft."
            if enabled else "All channels disabled in the draft."
        )

    def _mark_dirty(self, *_ignored) -> None:
        if self._loading:
            return
        self._dirty = True
        self._refresh_summary()

    def _set_clean(self) -> None:
        self._dirty = False
        self._refresh_summary()

    def _validation_errors(
        self, scaling: dict[str, list[float] | list[bool]]
    ) -> list[str]:
        errors: list[str] = []
        for index, channel in enumerate(CHANNEL_NAMES):
            if not scaling["enabled"][index]:
                continue
            raw_gain = float(scaling["raw_to_eng_gain"][index])
            eng_gain = float(scaling["eng_to_raw_gain"][index])
            if raw_gain == 0.0 or eng_gain == 0.0:
                errors.append(f"{channel} has a zero gain")
        return errors

    def _refresh_summary(self) -> None:
        scaling = self._read_scaling_from_table()
        enabled_count = sum(bool(value) for value in scaling["enabled"])
        errors = self._validation_errors(scaling)
        self.enabled_summary.setText(f"{enabled_count} / {len(CHANNEL_NAMES)}\nENABLED")
        self.validation_summary.setText(
            f"{len(errors)} ISSUE{'S' if len(errors) != 1 else ''}\nVALIDATION"
            if errors else "PASSED\nVALIDATION"
        )
        self.validation_summary.setProperty("warning", bool(errors))
        self.validation_summary.style().unpolish(self.validation_summary)
        self.validation_summary.style().polish(self.validation_summary)
        self.change_summary.setText("UNSAVED\nSTATE" if self._dirty else "SAVED\nSTATE")

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
        self._loading = True
        for index in range(len(CHANNEL_NAMES)):
            self.enabled_boxes[index].setChecked(bool(scaling["enabled"][index]))
            self.raw_to_eng_gain[index].setValue(float(scaling["raw_to_eng_gain"][index]))
            self.raw_to_eng_offset[index].setValue(float(scaling["raw_to_eng_offset"][index]))
            self.eng_to_raw_gain[index].setValue(float(scaling["eng_to_raw_gain"][index]))
            self.eng_to_raw_offset[index].setValue(float(scaling["eng_to_raw_offset"][index]))
        self._loading = False
        self._refresh_summary()

    def _read_scaling_from_table(self) -> dict[str, list[float] | list[bool]]:
        return {
            "raw_to_eng_gain": [spinbox.value() for spinbox in self.raw_to_eng_gain],
            "raw_to_eng_offset": [spinbox.value() for spinbox in self.raw_to_eng_offset],
            "eng_to_raw_gain": [spinbox.value() for spinbox in self.eng_to_raw_gain],
            "eng_to_raw_offset": [spinbox.value() for spinbox in self.eng_to_raw_offset],
            "enabled": [box.isChecked() for box in self.enabled_boxes],
        }
