from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpacerItem,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
)

from python.app.PageShell import DetailPage


class AlarmPage(DetailPage):
    def __init__(
        self,
        go_back: Callable[[], None],
        get_alarms: Callable[[], list[dict[str, Any]]] | None = None,
        acknowledge: Callable[[], None] | None = None,
        reload_config: Callable[[], list[dict[str, Any]]] | None = None,
        get_config: Callable[[], dict[str, Any]] | None = None,
        save_config: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            "Alarm",
            "Alarm on/off toggle",
            "Back to Manual Controls",
            go_back,
        )
        self._get_alarms = get_alarms
        self._acknowledge = acknowledge
        self._reload_config = reload_config
        self._get_config = get_config
        self._save_config = save_config

        _, workspace = self.add_workspace()

        actions = QHBoxLayout()
        self.acknowledge_button = QPushButton("Acknowledge")
        self.acknowledge_button.setCursor(Qt.PointingHandCursor)
        self.acknowledge_button.clicked.connect(self._acknowledge_alarms)
        self.reload_button = QPushButton("Reload Config")
        self.reload_button.setCursor(Qt.PointingHandCursor)
        self.reload_button.clicked.connect(self._reload)
        self.save_button = QPushButton("Save Settings")
        self.save_button.setCursor(Qt.PointingHandCursor)
        self.save_button.clicked.connect(self._save_settings)
        actions.addWidget(self.acknowledge_button)
        actions.addWidget(self.reload_button)
        actions.addWidget(self.save_button)
        actions.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        workspace.addLayout(actions)

        self.status_label = QLabel("No active alarms")
        self.status_label.setObjectName("pidStatusCard")
        workspace.addWidget(self.status_label)

        workspace.addWidget(self._build_settings_panel())

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Code", "Channel", "Severity", "State", "Message"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        workspace.addWidget(self.table, 1)

        self._load_config_fields()
        self._refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(250)

    def _build_settings_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("displayModePanel")
        layout = QGridLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)

        self.enabled_box = QCheckBox("Alarm engine")
        self.log_events_box = QCheckBox("Log events")
        layout.addWidget(self.enabled_box, 0, 0)
        layout.addWidget(self.log_events_box, 0, 1)

        self.rf_channel_edit = QLineEdit()
        self.rf_delta_spin = self._make_spinbox(0.0, 1000000.0, 1.0)
        self.rf_window_spin = self._make_spinbox(0.1, 3600.0, 3.0)
        self.vac_channels_edit = QLineEdit()
        self.vac_factor_spin = self._make_spinbox(1.0, 1000000.0, 2.0)
        self.vac_window_spin = self._make_spinbox(0.1, 3600.0, 3.0)

        fields = (
            ("RF channel", self.rf_channel_edit),
            ("RF delta kV", self.rf_delta_spin),
            ("RF window s", self.rf_window_spin),
            ("Vac channels", self.vac_channels_edit),
            ("Vac factor", self.vac_factor_spin),
            ("Vac window s", self.vac_window_spin),
        )
        for index, (label, widget) in enumerate(fields, start=1):
            row = 1 + ((index - 1) // 3)
            column = ((index - 1) % 3) * 2
            field_label = QLabel(label)
            field_label.setObjectName("settingsDescription")
            layout.addWidget(field_label, row, column)
            layout.addWidget(widget, row, column + 1)
        return panel

    def _make_spinbox(self, minimum: float, maximum: float, value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(4)
        spin.setSingleStep(0.1)
        spin.setValue(value)
        return spin

    def _load_config_fields(self) -> None:
        config = self._get_config() if self._get_config is not None else {}
        self.enabled_box.setChecked(bool(config.get("enabled", True)))
        self.log_events_box.setChecked(bool(config.get("log_events", True)))
        self.rf_channel_edit.setText(str(config.get("rf_channel", "rf_kv")))
        self.rf_delta_spin.setValue(float(config.get("rf_dkv", 1.0)))
        self.rf_window_spin.setValue(float(config.get("rf_window_s", 3.0)))
        vac_channels = config.get("vac_channels", ["vac1", "vac2"])
        if isinstance(vac_channels, list):
            self.vac_channels_edit.setText(", ".join(str(channel) for channel in vac_channels))
        else:
            self.vac_channels_edit.setText(str(vac_channels))
        self.vac_factor_spin.setValue(float(config.get("vac_factor", 2.0)))
        self.vac_window_spin.setValue(float(config.get("vac_window_s", 3.0)))

    def _acknowledge_alarms(self) -> None:
        if self._acknowledge is not None:
            self._acknowledge()
        self._refresh()

    def _reload(self) -> None:
        if self._reload_config is not None:
            try:
                self._reload_config()
            except (OSError, ValueError):
                self.status_label.setText("Config reload failed")
                return
        self._load_config_fields()
        self._refresh()

    def _save_settings(self) -> None:
        if self._save_config is None:
            self.status_label.setText("No config writer connected")
            return
        updates = {
            "enabled": self.enabled_box.isChecked(),
            "log_events": self.log_events_box.isChecked(),
            "rf_channel": self.rf_channel_edit.text(),
            "rf_dkv": self.rf_delta_spin.value(),
            "rf_window_s": self.rf_window_spin.value(),
            "vac_channels": self.vac_channels_edit.text(),
            "vac_factor": self.vac_factor_spin.value(),
            "vac_window_s": self.vac_window_spin.value(),
        }
        try:
            self._save_config(updates)
        except (OSError, ValueError):
            self.status_label.setText("Config save failed")
            return
        self._load_config_fields()
        self._refresh()

    def _refresh(self) -> None:
        alarms = self._get_alarms() if self._get_alarms is not None else []
        config = self._get_config() if self._get_config is not None else {}
        enabled = bool(config.get("enabled", True))
        if not enabled:
            self.status_label.setText("Alarm engine off")
        elif alarms:
            self.status_label.setText(f"{len(alarms)} active alarm(s)")
        else:
            self.status_label.setText("No active alarms")
        self.table.setRowCount(len(alarms))
        for row, alarm in enumerate(alarms):
            state = "Acknowledged" if alarm.get("acknowledged") else "Active"
            values = [
                alarm.get("code", "--"),
                alarm.get("channel", "--"),
                alarm.get("severity", "--"),
                state,
                alarm.get("message", "--"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
