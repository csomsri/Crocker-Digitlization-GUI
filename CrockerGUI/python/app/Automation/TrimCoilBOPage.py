"""Direct-coil BO simulator workspace. The child process has no device adapter."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import uuid

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QSpinBox, QTabWidget, QGridLayout, QFrame, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .TrimCoilBOPlots import TrimCoilBOPlot, TrimCoilPlotData, TrimCoilBeamTimeline, TrimCoilOverview


class TrimCoilBOPage(QWidget):
    def __init__(self, show_parent):
        super().__init__()
        self.setObjectName('trimCoilBOPage')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet('QWidget#trimCoilBOPage { background-color: #17191c; }')
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.readyReadStandardError.connect(self._read_error)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self.buffer = ''
        self.summary = None
        self.stderr = ''
        self.audit_path = None
        layout = QVBoxLayout(self)
        back = QPushButton('Back to Automation')
        back.clicked.connect(show_parent)
        layout.addWidget(back)
        title = QLabel('MISO · Trim-coil optimization')
        title.setStyleSheet('font-size: 22px; font-weight: 600;')
        layout.addWidget(title)
        description = QLabel('SIMULATION ONLY  ·  Maximize repeatable output beam from the starting operating state.\n'
            'The session captures current coil settings as the fixed recovery reference. No run sheet is used.')
        description.setWordWrap(True)
        layout.addWidget(description)
        self.reference_label = QLabel('Starting reference: waiting for session capture · two simulated coils available')
        self.reference_label.setWordWrap(True)
        layout.addWidget(self.reference_label)
        metrics = QHBoxLayout()
        self.metrics = {}
        for key, title in [('beam', 'MEASURED BEAM'), ('gain', 'CONFIRMED GAIN'),
                           ('cost', 'COST · LOWER IS BETTER'), ('budget', 'CANDIDATES / WINDOWS')]:
            card = QFrame()
            card.setStyleSheet('QFrame { background: #222831; border-radius: 8px; }')
            box = QVBoxLayout(card)
            caption = QLabel(title)
            caption.setStyleSheet('color: #aeb9ca; font-size: 10px;')
            value = QLabel('—')
            value.setStyleSheet('font-size: 19px; font-weight: 600; color: #e3ecfa;')
            box.addWidget(caption)
            box.addWidget(value)
            metrics.addWidget(card)
            self.metrics[key] = value
        layout.addLayout(metrics)
        self.coil_grid = QGridLayout()
        self.coil_cards = {}
        self.reference_targets = {}
        self.reference_readbacks = {}
        self.candidate_count = 0
        self.initial_distinct = 4
        self._ensure_coils(['TC1', 'TC2'])
        layout.addLayout(self.coil_grid)
        self.step_label = QLabel('Capture reference → Baseline → Initialize → Propose → Settle → Measure → Restore')
        self.step_label.setWordWrap(True)
        layout.addWidget(self.step_label)
        form = QFormLayout()
        self.trials = QSpinBox()
        self.trials.setRange(1, 100)
        self.trials.setValue(10)
        form.addRow('Candidate trial budget', self.trials)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2147483647)
        self.seed.setValue(1729)
        form.addRow('Simulation seed', self.seed)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self.start_button = QPushButton('Start simulation')
        self.start_button.clicked.connect(self.start_simulation)
        self.abort_button = QPushButton('Abort and restore reference')
        self.abort_button.setEnabled(False)
        self.abort_button.clicked.connect(self.stop_backend)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.abort_button)
        layout.addLayout(buttons)
        self.status = QLabel('Ready. Hardware execution is unavailable on this page.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.best_label = QLabel('Confirmed best: waiting for baseline measurements')
        self.best_label.setWordWrap(True)
        layout.addWidget(self.best_label)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['Window', 'Purpose', 'TC1 (A)', 'TC2 (A)', 'Beam (nA)', 'Std. dev. (nA)', 'Cost (−nA)'])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.plot_data = TrimCoilPlotData()
        self.plot_tabs = QTabWidget()
        self.plots = {'signals': TrimCoilBeamTimeline(self.plot_data)}
        self.plot_tabs.addTab(self.plots['signals'], 'Trim coils + beam')
        self.layer_checks = {}
        layers = QHBoxLayout()
        layers.addWidget(QLabel('Layers:'))
        for name in ('Reference', 'Confirmed best', 'Window variability', 'Search path'):
            check = QCheckBox(name)
            check.setChecked(True)
            check.toggled.connect(lambda enabled, key=name: self._toggle_layer(key, enabled))
            layers.addWidget(check)
            self.layer_checks[name] = check
        layers.addStretch()
        layout.addLayout(layers)
        for view, label in [('beam', 'Beam progress'), ('search', 'Coil search'), ('confirmation', 'Confirmations')]:
            plot = TrimCoilBOPlot(self.plot_data, view)
            self.plots[view] = plot
            self.plot_tabs.addTab(plot, label)
        for view, label in [('cost', 'Cost / progress'), ('parallel', 'All coil settings')]:
            plot = TrimCoilOverview(self.plot_data, view)
            self.plots[view] = plot
            self.plot_tabs.addTab(plot, label)
        self.plot_tabs.addTab(self.table, 'Measurements')
        layout.addWidget(self.plot_tabs, 1)
        self.log_label = QLabel('Each run saves a JSON audit with raw samples in CrockerGUI/logs/.')
        self.log_label.setWordWrap(True)
        layout.addWidget(self.log_label)

    def _ensure_coils(self, names):
        for name in names:
            if name in self.coil_cards:
                continue
            card = QFrame()
            card.setStyleSheet('QFrame { background: #20252d; border: 1px solid #354354; border-radius: 6px; }')
            box = QVBoxLayout(card)
            heading = QLabel(name)
            heading.setStyleSheet('font-weight: 600; color: #82baff;')
            value = QLabel('Waiting for capture')
            value.setStyleSheet('font-size: 11px; border: none;')
            box.addWidget(heading)
            box.addWidget(value)
            index = len(self.coil_cards)
            self.coil_grid.addWidget(card, index // 5, index % 5)
            self.coil_cards[name] = value

    def _update_dashboard(self, event):
        kind = event.get('event')
        if kind == 'start':
            self.reference_targets = dict(event.get('reference_targets_a', {}))
            self.reference_readbacks = dict(event.get('reference_readbacks_a', {}))
            self.initial_distinct = event.get('initial_distinct_settings', 4)
            self._ensure_coils(self.reference_targets)
            self.reference_label.setText('Starting reference captured for this session · recovery uses these fixed targets · local search ±0.5 A')
        if kind == 'telemetry':
            self._ensure_coils(event.get('readbacks_a', {}))
            valid = event.get('valid', False)
            for name, actual in event.get('readbacks_a', {}).items():
                target = event.get('targets_a', {}).get(name)
                ref = self.reference_targets.get(name)
                captured = self.reference_readbacks.get(name)
                fmt = lambda value: '—' if value is None else f'{value:+.4f} A'
                state = 'INVALID' if not valid else ('Settled' if target is not None and abs(actual-target) <= .01 else 'Settling')
                self.coil_cards[name].setText(f'Current     {fmt(actual)}\nReference  {fmt(ref)}\nStart RB    {fmt(captured)}\nTarget       {fmt(target)}\n{state}')
            self.metrics['beam'].setText(f"{event['beam_nA']:.3f} nA" if valid else 'Invalid signal')
        if kind == 'measurement':
            if event['kind'] == 'candidate':
                self.candidate_count += 1
            self.metrics['cost'].setText(f"{-event['mean_nA']:.3f}")
        if self.plot_data.reference is not None and self.plot_data.best:
            gain = self.plot_data.best[-1][1] - self.plot_data.reference
            percent = 100 * gain / self.plot_data.reference if self.plot_data.reference else 0
            self.metrics['gain'].setText(f'{gain:+.3f} nA ({percent:+.1f}%)')
        self.metrics['budget'].setText(f'{self.candidate_count} / {self.trials.value()} · {len(self.plot_data.windows)} windows')
        distinct = len({tuple(sorted(w['point'].items())) for w in self.plot_data.windows})
        phase = 'Baseline / Sobol initialization' if distinct < self.initial_distinct else 'Model-guided search'
        elapsed = event.get('time_s', 0)
        self.step_label.setText(f'{phase} · {distinct}/{self.initial_distinct} distinct settings to start GP · '
                                f'{elapsed:.1f} s simulation time · {event.get("state", kind or "waiting")}')

    def start_simulation(self):
        if self.process.state() != QProcess.NotRunning:
            return
        self.buffer, self.stderr, self.summary = '', '', None
        self.table.setRowCount(0)
        self.plot_data.reset()
        self.reference_targets.clear()
        self.reference_readbacks.clear()
        self.candidate_count = 0
        for metric in self.metrics.values():
            metric.setText('—')
        for card in self.coil_cards.values():
            card.setText('Waiting for capture')
        self.reference_label.setText('Starting reference: capturing simulator state…')
        for plot in self.plots.values():
            plot.update()
        root = Path(__file__).resolve().parents[3]
        self.audit_path = root / 'logs' / f'trim_coil_bo_{uuid.uuid4().hex}.json'
        self.process.setWorkingDirectory(str(root))
        self.process.setProgram(sys.executable)
        self.process.setArguments(['-u', '-m', 'source.Python.Automation.trim_coil_simulator',
            '--stream', '--trials', str(self.trials.value()), '--seed', str(self.seed.value()),
            '--output', str(self.audit_path)])
        self.start_button.setEnabled(False)
        self.abort_button.setEnabled(True)
        self.trials.setEnabled(False)
        self.seed.setEnabled(False)
        self.best_label.setText('Confirmed best: waiting for baseline measurements')
        self.status.setText('Starting simulator and optimizer…')
        self.process.start()

    @property
    def run_active(self):
        return self.process.state() != QProcess.NotRunning

    def stop_backend(self):
        if self.process.state() != QProcess.NotRunning:
            self.process.write(b'abort\n')
            self.abort_button.setEnabled(False)
            self.status.setText('Abort requested; waiting for model computation and reference restoration…')

    def _read_output(self):
        self.buffer += bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            try:
                message = json.loads(line)
            except ValueError:
                continue
            self._message(message)

    def _message(self, message):
        if 'summary' in message:
            self.summary = message['summary']
            return
        event = message.get('progress', {})
        self.plot_data.consume(event)
        for plot in self.plots.values():
            plot.update()
        label = event.get('event', '')
        self._update_dashboard(event)
        if label == 'measurement':
            row = self.table.rowCount()
            self.table.insertRow(row)
            point = event['point']
            values = [str(row + 1), event['kind'], f"{point['TC1']:.4f}", f"{point['TC2']:.4f}",
                      f"{event['mean_nA']:.4f}", f"{event['stddev_nA']:.4f}", f"{-event['mean_nA']:.4f}"]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
            self.table.scrollToBottom()
            self.status.setText(f"Measured {event['kind']}; returning to reference")
        elif label == 'confirmation':
            result = 'Promoted' if event['promoted'] else 'Kept previous best'
            self.best_label.setText(f"{result}; measured gain {event['gain_nA']:.4f} nA, "
                                    f"lower bound {event['lower_bound_nA']:.4f} nA")
        elif label == 'apply':
            self.status.setText(f"Applying {event['kind']}; waiting for stable readbacks")
        elif label in ('stop', 'recovery_blocked', 'recovery_verified'):
            self.status.setText(event.get('reason', label))

    def _read_error(self):
        self.stderr = (self.stderr + bytes(self.process.readAllStandardError()).decode('utf-8', errors='replace'))[-6000:]

    def _toggle_layer(self, name, enabled):
        for plot in self.plots.values():
            plot.layers[name] = enabled
            plot.update()

    def _process_error(self, error):
        if error == QProcess.FailedToStart:
            self.status.setText('Could not start simulator: ' + self.process.errorString())
            self._reset_buttons()

    def _reset_buttons(self):
        self.start_button.setEnabled(True)
        self.abort_button.setEnabled(False)
        self.trials.setEnabled(True)
        self.seed.setEnabled(True)

    def _finished(self, code, exit_status):
        self._read_output()
        self._read_error()
        self._reset_buttons()
        if self.summary:
            s = self.summary
            self.step_label.setText(f"{s['state'].capitalize()} · {s['simulated_elapsed_s']:.1f} s simulation time · "
                                    + ('Reference restoration verified' if s['reference_restored'] else 'Reference restoration NOT verified'))
            self.status.setText(f"{s['state'].capitalize()}: {s['reason']}. "
                                f"{s['candidate_trials']} candidates, {s['measurement_windows']} windows.")
            value = s['incumbent_mean_nA']
            self.best_label.setText(f"Confirmed best: {value:.4f} nA; {s['incumbent_targets_a']}"
                                   if value is not None else 'No verified baseline measured')
            self.log_label.setText(f'Audit saved: {self.audit_path.name}')
            self.log_label.setToolTip(str(self.audit_path))
        else:
            self.status.setText('Simulator failed: ' + (self.stderr.strip() or f'exit code {code}'))
