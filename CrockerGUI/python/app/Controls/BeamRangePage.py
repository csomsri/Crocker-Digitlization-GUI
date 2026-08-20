from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpacerItem,
    QSizePolicy,
    QVBoxLayout,
)

from python.app.PageShell import DetailPage


class BeamRangePage(DetailPage):
    def __init__(
        self,
        go_back: Callable[[], None],
        get_beam_state: Callable[[], dict[str, Any]] | None = None,
        get_beam_ranges: Callable[[], list[dict[str, Any]]] | None = None,
        set_manual_range: Callable[[int], dict[str, Any]] | None = None,
        reload_config: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            "Beam Range",
            "Beam range selection/control",
            "Back to Manual Controls",
            go_back,
        )
        self._get_beam_state = get_beam_state
        self._get_beam_ranges = get_beam_ranges
        self._set_manual_range = set_manual_range
        self._reload_config = reload_config
        self._range_rows: list[dict[str, Any]] = []
        self._updating_combo = False

        _, workspace = self.add_workspace()

        actions = QHBoxLayout()
        self.range_select = QComboBox()
        self.range_select.setObjectName("pidTunerProfile")
        self.range_select.setMinimumWidth(240)
        self.range_select.currentIndexChanged.connect(self._range_selected)
        self.reload_button = QPushButton("Reload Config")
        self.reload_button.setCursor(Qt.PointingHandCursor)
        self.reload_button.clicked.connect(self._reload)
        actions.addWidget(QLabel("Manual range"))
        actions.addWidget(self.range_select)
        actions.addWidget(self.reload_button)
        actions.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        workspace.addLayout(actions)

        self.status_label = QLabel("Waiting for transport snapshot")
        self.status_label.setObjectName("pidStatusCard")
        workspace.addWidget(self.status_label)

        self.metric_labels: dict[str, QLabel] = {}
        metric_grid = QGridLayout()
        metric_grid.setSpacing(12)
        for index, (key, title) in enumerate(
            (
                ("display_ua", "Display uA"),
                ("current_ua", "Current uA"),
                ("raw_value", "Raw Value"),
                ("range_label", "Range"),
                ("full_scale_ua", "Full Scale uA"),
                ("select_mode", "Select Mode"),
            )
        ):
            del key
            card = self._metric_card(title, "--")
            metric_grid.addWidget(card, index // 3, index % 3)
        workspace.addLayout(metric_grid)
        workspace.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))

        self._refresh_ranges()
        self._refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(250)

    def _metric_card(self, title: str, value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("pidPanel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        label = QLabel(title)
        label.setObjectName("pidBoundLabel")
        metric = QLabel(value)
        metric.setObjectName("pidBoundTitle")
        metric.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(label)
        layout.addWidget(metric)
        self.metric_labels[title] = metric
        return card

    def _refresh_ranges(self) -> None:
        ranges = self._get_beam_ranges() if self._get_beam_ranges is not None else []
        self._range_rows = ranges
        self._updating_combo = True
        self.range_select.clear()
        for row in ranges:
            label = str(row.get("label", f"Range {row.get('index', 0)}"))
            full_scale = self._format_value(row.get("full_scale_ua"))
            index = int(row.get("index", self.range_select.count()))
            self.range_select.addItem(f"{label}  FS {full_scale} uA", index)
        self._updating_combo = False

    def _range_selected(self) -> None:
        if self._updating_combo or self._set_manual_range is None:
            return
        index = self.range_select.currentData()
        if index is None:
            return
        try:
            state = self._set_manual_range(int(index))
        except (TypeError, ValueError):
            return
        self._apply_state(state)

    def _reload(self) -> None:
        if self._reload_config is not None:
            try:
                self._reload_config()
            except (OSError, ValueError):
                self.status_label.setText("Config reload failed")
                return
        self._refresh_ranges()
        self._refresh()

    def _refresh(self) -> None:
        state = self._get_beam_state() if self._get_beam_state is not None else {}
        self._apply_state(state)

    def _apply_state(self, state: dict[str, Any]) -> None:
        if not state:
            self.status_label.setText("Waiting for transport snapshot")
            return
        quality = str(state.get("quality", "idle"))
        message = str(state.get("message", ""))
        self.status_label.setText(message if message else f"Beam calibration {quality}")
        values = {
            "Display uA": self._format_value(state.get("display_ua")),
            "Current uA": self._format_value(state.get("current_ua")),
            "Raw Value": self._format_value(state.get("raw_value")),
            "Range": str(state.get("range_label", "--")),
            "Full Scale uA": self._format_value(state.get("full_scale_ua")),
            "Select Mode": str(state.get("select_mode", "--")),
        }
        for key, value in values.items():
            label = self.metric_labels.get(key)
            if label is not None:
                label.setText(value)
        range_index = state.get("range_index")
        if range_index is not None:
            combo_index = self.range_select.findData(int(range_index))
            if combo_index >= 0 and combo_index != self.range_select.currentIndex():
                self._updating_combo = True
                self.range_select.setCurrentIndex(combo_index)
                self._updating_combo = False

    def _format_value(self, value: Any) -> str:
        try:
            return f"{float(value):.10g}"
        except (TypeError, ValueError):
            return "--"
