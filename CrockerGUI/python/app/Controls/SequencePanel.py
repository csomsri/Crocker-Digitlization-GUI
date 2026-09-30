"""Field Control sequence editor; all execution stays in the C++ backend."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QGridLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from python.app.ResponsiveLayout import ResponsiveRow
from python.app.Automation.ControlOwnership import active_controller
from python.app.widgets.MagneticFieldWidgets import CHANNEL_NAMES, MAX_GAUGE_VALUE, FIELD_PLOT_SAMPLE_RATE_HZ

ACTIVE_STATES = {"Applying", "Running", "Settling", "Dwelling", "Stopping"}


class SequencePanelMixin:
    def _build_sequencer_panel(self) -> QWidget:
        body = QWidget()
        body.setObjectName("sequencePanel")
        body.setStyleSheet("""
            QWidget#sequencePanel { background: #111827; }
            QWidget#sequencePanel QLabel { color: #cbd5e1; font-size: 14px; }
            QWidget#sequencePanel QLabel#fieldMonitorTitle { color: #f1f5f9; font-size: 18px; }
            QLabel#sequenceStatus { background: #17243a; color: #e2e8f0;
                border: 1px solid #475569; border-radius: 6px; padding: 8px; }
            QTableCornerButton::section { background: #172033; border: 1px solid #334155; }
            QHeaderView { background: #172033; }
            QPushButton#sequenceRun { background: #155e55; color: #f0fdfa; border: 1px solid #2dd4bf; }
            QPushButton#sequenceStop { background: #7f1d1d; color: #fff1f2; border: 1px solid #fb7185; }
            QPushButton:disabled, QPushButton#sequenceRun:disabled, QPushButton#sequenceStop:disabled {
                background: #1e293b; color: #7d8ca3; border: 1px solid #334155;
            }
        """)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        heading = QLabel("Run a sequence of current targets")
        heading.setObjectName("fieldMonitorTitle")
        layout.addWidget(heading)
        explanation = QLabel(
            "Send targets → wait for measured arrival → hold → continue. "
            "The hold starts after all active sequence channels reach their targets. "
            "Channels omitted from later steps keep their previous targets."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.sequence_status_label = QLabel("Ready — add your steps below.")
        self.sequence_status_label.setObjectName("sequenceStatus")
        self.sequence_status_label.setWordWrap(True)
        self.sequence_status_label.setMinimumHeight(44)
        layout.addWidget(self.sequence_status_label)
        self.sequence_table = QTableWidget(0, 2)
        self.sequence_table.setObjectName("scalingTable")
        self.sequence_table.setHorizontalHeaderLabels(["Targets · click to edit", "Hold after arrival (s)"])
        self.sequence_table.setAlternatingRowColors(True)
        self.sequence_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sequence_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.sequence_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.sequence_table.setMinimumHeight(170)
        self.sequence_table.setMaximumHeight(280)
        layout.addWidget(self.sequence_table, 1)
        options = ResponsiveRow()
        options.addWidget(QLabel("If stopped or interrupted:"))
        self.sequence_stop_policy = QComboBox()
        self.sequence_stop_policy.addItems(["Keep last targets", "Disable sequence channels"])
        self.sequence_stop_policy.setToolTip(
            "Keep last targets: currents may continue moving toward those targets. "
            "Disable: send off/disable for every channel used in this sequence. "
            "A lost connection can prevent that command from reaching the machine."
        )
        options.addWidget(self.sequence_stop_policy)
        options.addStretch(1)
        layout.addLayout(options)
        for text in (
            "Each step turns on and enables its selected channels. Manual target changes are locked while running. "
            "On completion, final targets stay applied. Stopping does not ramp currents to zero.",
            "Arrival: within ±0.5 A for 0.2 s · Arrival timeout: 30 s · Feedback timeout: 1 s. "
            "If current leaves tolerance, the hold restarts after arrival.",
        ):
            note = QLabel(text)
            note.setWordWrap(True)
            layout.addWidget(note)
        actions = ResponsiveRow()
        self.sequence_edit_buttons = []
        for label, handler in (
            ("Add step", self._add_sequence_step),
            ("Remove selected", self._remove_sequence_steps),
            ("Move up", lambda: self._move_sequence_step(-1)),
            ("Move down", lambda: self._move_sequence_step(1)),
            ("Run sequence", self._start_sequence),
            ("Stop sequence", self._stop_sequence),
        ):
            button = QPushButton(label)
            button.setObjectName("fieldBulk")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(handler)
            actions.addWidget(button)
            if label == "Run sequence":
                self.sequence_start_button = button
                button.setObjectName("sequenceRun")
            elif label == "Stop sequence":
                self.sequence_stop_button = button
                button.setObjectName("sequenceStop")
                button.setEnabled(False)
            else:
                self.sequence_edit_buttons.append(button)
        # Keep Run and Stop above the table, even when the page needs scrolling.
        layout.insertLayout(3, actions)
        layout.addStretch(1)
        self._sequence_running = False
        self._sequence_needs_sync = False
        self._add_sequence_step()
        return body

    @staticmethod
    def _sequence_target_text(targets: dict[int, float]) -> str:
        return "; ".join(f"{CHANNEL_NAMES[ch]} → {value:g} A" for ch, value in sorted(targets.items()))

    def _add_sequence_step(self, checked=False, *, targets=None, hold=5.0) -> None:
        row = self.sequence_table.rowCount()
        self.sequence_table.insertRow(row)
        edit = QPushButton()
        edit.setObjectName("fieldBulk")
        edit.targets = dict(targets) if targets is not None else {self.selected_index: self.target_values[self.selected_index]}
        edit.setText(self._sequence_target_text(edit.targets))
        edit.setToolTip(edit.text() + "\nClick to choose one or more channel targets for this step.")
        edit.clicked.connect(lambda: self._edit_sequence_targets(edit))
        self.sequence_table.setCellWidget(row, 0, edit)
        hold_spin = QDoubleSpinBox()
        hold_spin.setObjectName("sequenceHoldInput")
        hold_spin.setRange(0, 3600)
        hold_spin.setDecimals(2)
        hold_spin.setSuffix(" s")
        hold_spin.setValue(hold)
        hold_spin.setToolTip("Time to hold after measured arrival. Zero continues immediately after settling.")
        self.sequence_table.setCellWidget(row, 1, hold_spin)
        self.sequence_table.setVerticalHeaderItem(row, QTableWidgetItem(f"Step {row + 1}"))
        self.sequence_table.setRowHeight(row, 54)

    def _edit_sequence_targets(self, button: QPushButton) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Choose targets for this step")
        dialog.setStyleSheet("QDialog { background: #111827; } QLabel, QCheckBox { color: #e2e8f0; }")
        layout = QVBoxLayout(dialog)
        explanation = QLabel("Select channels to change together. Unchecked channels keep their previous targets.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        grid = QGridLayout()
        fields = []
        for channel, name in enumerate(CHANNEL_NAMES):
            selected = QCheckBox(name)
            selected.setChecked(channel in button.targets)
            value = QDoubleSpinBox()
            value.setRange(0, MAX_GAUGE_VALUE)
            value.setDecimals(2)
            value.setSuffix(" A")
            value.setValue(button.targets.get(channel, self.target_values[channel]))
            value.setEnabled(selected.isChecked())
            selected.toggled.connect(value.setEnabled)
            grid.addWidget(selected, channel, 0)
            grid.addWidget(value, channel, 1)
            fields.append((selected, value))
        layout.addLayout(grid)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setText("Use these targets")
        for selected, _ in fields:
            selected.toggled.connect(lambda: save.setEnabled(any(check.isChecked() for check, _ in fields)))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            button.targets = {ch: value.value() for ch, (selected, value) in enumerate(fields) if selected.isChecked()}
            button.setText(self._sequence_target_text(button.targets))
            button.setToolTip(button.text() + "\nClick to edit these targets.")

    def _remove_sequence_steps(self) -> None:
        rows = sorted({index.row() for index in self.sequence_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.sequence_table.removeRow(row)
        if self.sequence_table.rowCount() == 0:
            self._add_sequence_step()
        for row in range(self.sequence_table.rowCount()):
            self.sequence_table.setVerticalHeaderItem(row, QTableWidgetItem(f"Step {row + 1}"))

    def _move_sequence_step(self, direction: int) -> None:
        row = self.sequence_table.currentRow()
        other = row + direction
        if row < 0 or not 0 <= other < self.sequence_table.rowCount():
            return
        steps = self._sequence_steps_from_table()
        steps[row], steps[other] = steps[other], steps[row]
        self.sequence_table.setRowCount(0)
        for step in steps:
            self._add_sequence_step(targets=step["targets"], hold=step["dwell_seconds"])
        self.sequence_table.selectRow(other)

    def _sequence_steps_from_table(self) -> list[dict]:
        return [
            {"targets": dict(self.sequence_table.cellWidget(row, 0).targets),
             "dwell_seconds": self.sequence_table.cellWidget(row, 1).value()}
            for row in range(self.sequence_table.rowCount())
        ]

    def _start_sequence(self) -> None:
        if not self.backend_available or self.backend is None or not hasattr(self.backend, "StartSequence"):
            self._set_sequence_status_text("Connect to the machine or start the simulator before running a sequence.")
            return
        if active_controller(self.backend, self) is not None:
            self._set_sequence_status_text("Stop PID/BO/GA before running a sequence.")
            return
        disable = self.sequence_stop_policy.currentIndex() == 1
        try:
            self.backend.StartSequence({
                "steps": self._sequence_steps_from_table(),
                "update_rate_hz": float(FIELD_PLOT_SAMPLE_RATE_HZ),
                "target_tolerance": 0.5,
                "step_timeout_seconds": 30.0,
                "telemetry_timeout_seconds": 1.0,
                "settle_seconds": 0.2,
                "require_connected": True,
                "disable_channels_on_stop": disable,
                "disable_channels_on_fault": disable,
            })
        except Exception as exc:
            self._set_sequence_status_text(f"Could not start: {exc}")
            return
        self._set_sequence_running(True)
        self._refresh_sequence_status()

    def _stop_sequence(self) -> None:
        if not self.backend_available or self.backend is None:
            return
        try:
            self.backend.StopSequence(self.sequence_stop_policy.currentIndex() == 1)
        except Exception as exc:
            self._set_sequence_status_text(f"Could not stop sequence: {exc}")
            return
        self._refresh_sequence_status()

    def _set_sequence_running(self, running: bool) -> None:
        if running or self._sequence_running:
            self._sequence_needs_sync = True
        self._sequence_running = running
        self.sequence_table.setEnabled(not running)
        self.sequence_stop_policy.setEnabled(not running)
        self.sequence_start_button.setEnabled(not running)
        self.sequence_stop_button.setEnabled(running)
        for button in self.sequence_edit_buttons:
            button.setEnabled(not running)

    def _refresh_sequence_status(self) -> None:
        if not self.backend_available or self.backend is None or not hasattr(self.backend, "SequenceStatus"):
            return
        try:
            status = self.backend.SequenceStatus()
        except Exception as exc:
            self._set_sequence_status_text(f"Cannot read sequence status: {exc}")
            return
        state = str(status.get("state", "Idle"))
        running = state in ACTIVE_STATES
        self._set_sequence_running(running)
        message = str(status.get("message", ""))
        names = {"Idle": "Ready", "Applying": "Sending targets", "Running": "Waiting for arrival",
                 "Settling": "Checking arrival", "Dwelling": "Holding", "Stopping": "Stopping",
                 "Completed": "Complete", "Stopped": "Stopped", "Faulted": "Interrupted"}
        label = names.get(state, state)
        if running:
            step = int(status.get("step_index", 0)) + 1
            count = int(status.get("step_count", 0))
            self.sequence_table.selectRow(step - 1)
            remaining = float(status.get("dwell_remaining_seconds", 0))
            suffix = f" · {remaining:.1f} s left" if state == "Dwelling" else ""
            self._set_sequence_status_text(f"Step {step} of {count} — {label}{suffix}\n{message}")
        else:
            self._set_sequence_status_text(f"{label} — {message}")

    def _set_sequence_status_text(self, text: str) -> None:
        if self.sequence_status_label is not None:
            self.sequence_status_label.setText(text)

    def _sync_targets_from_running_sequence(self) -> None:
        if self.backend is None or not hasattr(self.backend, "PendingCommand") or not self._sequence_needs_sync:
            return
        try:
            command = self.backend.PendingCommand()
        except Exception:
            return
        self._sequence_needs_sync = self._sequence_running
        for index, channel in enumerate(command[:len(CHANNEL_NAMES)]):
            if not isinstance(channel, dict):
                continue
            self.target_values[index] = float(channel.get("target", self.target_values[index]))
            self.applied_targets[index] = self.target_values[index]
            self.applied_on[index] = bool(channel.get("on", self.applied_on[index]))
            self.applied_enabled[index] = bool(channel.get("enabled", self.applied_enabled[index]))
            self._set_toggle_from_telemetry(self.on_buttons[index], self.applied_on[index])
            self._set_toggle_from_telemetry(self.enable_buttons[index], self.applied_enabled[index])
        self._refresh_target_display()
