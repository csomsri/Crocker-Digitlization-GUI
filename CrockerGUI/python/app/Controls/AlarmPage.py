from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
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

        _, workspace = self.add_workspace()

        actions = QHBoxLayout()
        self.acknowledge_button = QPushButton("Acknowledge")
        self.acknowledge_button.setCursor(Qt.PointingHandCursor)
        self.acknowledge_button.clicked.connect(self._acknowledge_alarms)
        self.reload_button = QPushButton("Reload Config")
        self.reload_button.setCursor(Qt.PointingHandCursor)
        self.reload_button.clicked.connect(self._reload)
        actions.addWidget(self.acknowledge_button)
        actions.addWidget(self.reload_button)
        actions.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        workspace.addLayout(actions)

        self.status_label = QLabel("No active alarms")
        self.status_label.setObjectName("pidStatusCard")
        workspace.addWidget(self.status_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Code", "Channel", "Severity", "State", "Message"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        workspace.addWidget(self.table, 1)

        self._refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(250)

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
