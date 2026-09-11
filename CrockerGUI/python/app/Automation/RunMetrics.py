"""Continuous-control response measurements, independent of tuning trials."""
import csv
import json
import math
import time
from datetime import datetime, timezone
from dataclasses import asdict
from uuid import uuid4
from itertools import islice
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QWidget, QFrame, QSizePolicy, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QSpinBox, QDialog, QTableWidget, QTableWidgetItem,
                              QDateEdit, QFileDialog, QHeaderView)
from source.Python.Optimization.trial_metrics import evaluate_trial
from python.app.widgets.PidDialog import setup_pid_dialog
from python.app.widgets.ScreenSafeComboBox import ScreenSafeComboBox as QComboBox


class RunMetrics(QFrame):
    def __init__(self, directory):
        super().__init__()
        self.setObjectName('responseRecordingPanel')
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.setStyleSheet('''
            QFrame#responseRecordingPanel { background: #131f30; border: 1px solid #34465d; border-radius: 8px; }
            QLabel#recordingTitle { color: #e7eef8; font-weight: 600; font-size: 14px; }
            QLabel#recordingNote { color: #91a6bf; font-size: 12px; }
            QFrame#recordingStatus { background: #101a29; border: none; border-radius: 4px; }
            QComboBox#recordingMethod, QSpinBox#recordingDuration { background: #192a40; color: #e7eef8;
                border: 1px solid #3b526e; border-radius: 5px; padding: 0 10px; font-family: "Segoe UI"; font-size: 13px; }
            QPushButton#recordingAction { padding: 0 14px; font-family: "Segoe UI"; font-size: 13px; }
            QLabel { color: #cbd5e1; font-family: "Segoe UI"; font-size: 13px; }
            QDialog { background: #101a29; }
            QTableWidget { background: #142235; alternate-background-color: #1b2c42;
                color: #e7eef8; selection-background-color: #315477; font-family: "Segoe UI"; font-size: 13px; }
            QHeaderView::section { background: #24364c; color: #b9cce1; padding: 8px; border: none; }
        ''')
        self.directory = directory
        self.active = False
        self.samples = []
        self.records = []
        self._file = None
        self._stem = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        title = QLabel('Response recording')
        title.setObjectName('recordingTitle')
        row.addWidget(title)
        row.addSpacing(8)
        self.method = QComboBox()
        self.method.setEditable(True)
        self.method.setObjectName('recordingMethod')
        self.method.setMinimumWidth(190)
        self.method.setToolTip('Tuning method used for this recording')
        self.method.addItems(['Manual / baseline', 'Bayesian optimization', 'Random search', 'Zieglerâ€“Nichols'])
        row.addWidget(self.method)
        self.duration = QSpinBox()
        self.duration.setObjectName('recordingDuration')
        self.duration.setFixedWidth(120)
        self.duration.setToolTip('Recording duration; PID continues after recording ends')
        self.duration.setRange(10, 600)
        self.duration.setValue(60)
        self.duration.setSuffix(' s')
        row.addWidget(self.duration)
        self.record_button = QPushButton('Record again')
        self.record_button.setToolTip('Start another measurement window while PID is running')
        self.record_button.setEnabled(False)
        self.record_button.clicked.connect(lambda: self.start(self.config))
        row.addWidget(self.record_button)
        history = QPushButton('Run History / CSV')
        history.clicked.connect(self.show_history)
        row.addStretch()
        row.addWidget(history)
        for control in (self.method, self.duration, self.record_button, history):
            control.setFixedHeight(36)
        for button in (self.record_button, history):
            button.setObjectName('recordingAction')
        layout.addLayout(row)
        status = QFrame()
        status.setObjectName('recordingStatus')
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(10, 6, 10, 6)
        self.display = QLabel('Ready Â· Enable PID to record')
        self.display.setWordWrap(True)
        status_layout.addWidget(self.display, 3)
        self.note = QLabel('Settling is provisional while running. Steady error/RMS use the latest 20% of the interval. '
                           'Oscillation is monitored at the GUI sampling rate; BO penalties do not stop continuous control.')
        self.note.setWordWrap(True)
        self.note.setObjectName('recordingNote')
        self.note.setToolTip(self.note.text())
        self.note.setText('CSV autosave Â· Metric details on hover')
        status_layout.addWidget(self.note, 1)
        layout.addWidget(status)

    def start(self, config):
        self.finish('New interval')
        self.config = dict(config, method=self.method.currentText())
        self.window_seconds = self.duration.value()
        self.started = time.perf_counter()
        self.started_utc = datetime.now(timezone.utc).isoformat()
        self.samples = []
        self.last_stamp = None
        self.active = True
        self.method.setEnabled(False)
        self.duration.setEnabled(False)
        self.record_button.setEnabled(False)
        self.display.setText('Running â€” waiting for fresh response samples')
        self._stem = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._stem = self.directory / uuid4().hex
            self._file = self._stem.with_suffix('.csv').open('w', newline='', encoding='utf-8')
            self._writer = csv.writer(self._file)
            self._writer.writerow(['elapsed_seconds', 'measurement', 'error'])
            self._file.flush()
            self._stem.with_suffix('.json').write_text(json.dumps(dict(
                self.config, started_utc=self.started_utc, reason='Recording / incomplete',
                measurement_window_seconds=self.window_seconds), indent=2), encoding='utf-8')
        except OSError as exc:
            if self._file:
                self._file.close()
            self._file = None
            self.note.setText(f'Live save unavailable: {exc}. Will retry saving at the end.')

    def sample(self, stamp, measurement):
        if self.active and time.perf_counter() - self.started >= self.window_seconds:
            self.finish('Measurement window complete')
            self.record_button.setEnabled(True)
            return
        if not self.active or not all(math.isfinite(v) for v in (stamp, measurement)):
            return
        if self.last_stamp is not None and stamp <= self.last_stamp:
            return
        self.last_stamp = stamp
        elapsed = time.perf_counter() - self.started
        self.samples.append((elapsed, measurement, self.config['setpoint']-measurement, 0.0))
        if self._file:
            try:
                self._writer.writerow(self.samples[-1][:3])
                self._file.flush()
            except OSError as exc:
                self._file.close()
                self._file = None
                self.note.setText(f'Live save failed: {exc}. Will retry saving at the end.')
        self.refresh()
        if len(self.samples) >= 10000:
            self.finish('Sample limit reached')
            self.record_button.setEnabled(True)

    def metrics(self):
        try:
            return evaluate_trial(self.samples, self.config['setpoint'],
                                  deadband=self.config.get('nla_deadband', 0))
        except ValueError:
            return None

    def refresh(self, final=False):
        m = self.metrics()
        if m is None:
            self.display.setText('Insufficient fresh samples')
            return
        settling = f'{m.settling_time:.2f} s' if m.settled else 'Not settled'
        transient = f'{m.transient_time:.2f} s' if m.entered_tolerance else 'Not reached'
        cells = [('Settling', settling), ('Transient', transient), ('Steady error', f'{m.steady_state_error:.4g}'),
                 ('RMS error', f'{m.steady_state_rms:.4g}'), ('Overshoot', f'{m.overshoot:.4g}'),
                 ('Osc. amplitude', f'{m.oscillation_amplitude:.4g}')]
        self.display.setText('<table width="100%" cellspacing="6"><tr>' + ''.join(
            f'<td width="16%"><span style="color:#91a6bf;font-size:11px">{name}</span><br>'
            f'<b>{value}</b></td>' for name, value in cells) + '</tr></table>')
        self.note.setText(f"{'Final' if final else 'Live'} Â· " +
                          ('Sustained oscillation' if m.sustained_oscillation else 'No sustained oscillation') +
                          f'\n{m.oscillation_cycles:g} cycles Â· Tolerance Â±{m.tolerance:.4g}')

    def finish(self, reason):
        self.record_button.setEnabled(False)
        if not self.active:
            return
        self.active = False
        self.method.setEnabled(True)
        self.duration.setEnabled(True)
        self.refresh(final=True)
        m = self.metrics()
        record = dict(self.config, started_utc=self.started_utc,
                      duration_seconds=time.perf_counter()-self.started, reason=reason,
                      metrics=asdict(m) if m else None, sample_count=len(self.samples))
        record['measurement_window_seconds'] = self.window_seconds
        if record['metrics'] is not None:
            # This monitor measures response, not actuator effort or BO cost.
            record['metrics'].pop('control_effort')
        record['sampling'] = 'Fresh telemetry at GUI polling rate (nominally 8 Hz)'
        self.records.append(record)
        self.records[:] = self.records[-100:]
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            stem = self._stem or self.directory / uuid4().hex
            if self._file:
                self._file.close()
                self._file = None
            else:
                with stem.with_suffix('.csv').open('w', newline='', encoding='utf-8') as handle:
                    writer = csv.writer(handle)
                    writer.writerow(['elapsed_seconds', 'measurement', 'error'])
                    writer.writerows(row[:3] for row in self.samples)
            stem.with_suffix('.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
            self.note.setText('Recording saved Â· Open Run History / CSV')
            self.note.setToolTip(str(stem))
        except OSError as exc:
            self.note.setText(f'Could not save run: {exc}. Results remain in memory.')

    def show_history(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('PID Run History')
        dialog.resize(1180, 620)
        layout = setup_pid_dialog(dialog, 'PID Run History', window_controls=False)
        filters = QHBoxLayout()
        start_date, end_date = QDateEdit(), QDateEdit()
        for date in (start_date, end_date):
            date.setCalendarPopup(True)
            date.setDisplayFormat('yyyy-MM-dd')
            date.setFixedSize(160, 36)
        start_date.setDate(QDate(2000, 1, 1))
        end_date.setDate(QDate.fromString(datetime.now(timezone.utc).strftime('%Y-%m-%d'), 'yyyy-MM-dd'))
        for title, control in [('From (UTC)', start_date), ('To (UTC)', end_date)]:
            field = QVBoxLayout()
            field.setSpacing(4)
            field.addWidget(QLabel(title))
            field.addWidget(control)
            filters.addLayout(field)
        filters.addStretch()
        export = QPushButton('Export visible summaries')
        export.setFixedHeight(36)
        filters.addWidget(export)
        layout.addLayout(filters)
        table = QTableWidget(0, 9)
        table.setHorizontalHeaderLabels(['Started (UTC)', 'Method', 'Controller', 'Samples', 'End reason',
                                        'Settling (s)', 'Transient (s)', 'Steady |error|', 'Sustained oscillation'])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.verticalHeader().setDefaultSectionSize(36)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.verticalHeader().hide()
        layout.addWidget(table)
        paths = sorted(self.directory.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        valid = []
        for path in paths:
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            row = table.rowCount()
            table.insertRow(row)
            valid.append(path.with_suffix('.csv'))
            for col, key in enumerate(['started_utc', 'method', 'controller_kind', 'sample_count', 'reason']):
                raw = str(data.get(key, 'â€”'))
                value = raw
                if key == 'started_utc':
                    value = raw[:19].replace('T', ' ')
                if key == 'controller_kind':
                    value = {'python_nla': 'Python NLA', 'nla': 'C++ NLA', 'conventional': 'Conventional'}.get(raw, raw)
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, raw)
                item.setToolTip(raw)
                table.setItem(row, col, item)
            metrics = data.get('metrics') or {}
            values = [metrics.get('settling_time') if metrics.get('settled') else 'Not settled',
                      metrics.get('transient_time') if metrics.get('entered_tolerance') else 'Not reached',
                      metrics.get('steady_state_error', 'â€”'), metrics.get('sustained_oscillation', 'â€”')]
            if not metrics:
                values = ['â€”'] * 4
            for col, value in enumerate(values, 5):
                table.setItem(row, col, QTableWidgetItem(f'{value:.4g}' if isinstance(value, float) else str(value)))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for col, width in enumerate([160, 150, 110, 65, 160, 95, 95, 100, 110]):
            table.setColumnWidth(col, width)
        table.horizontalHeader().setStretchLastSection(True)
        for row in range(table.rowCount()):
            for col in (3, 5, 6, 7, 8):
                table.item(row, col).setTextAlignment(Qt.AlignCenter)
        table.setToolTip('Double-click a recording to view and export its samples.')
        def filter_rows():
            for row in range(table.rowCount()):
                date = QDate.fromString(table.item(row, 0).text()[:10], 'yyyy-MM-dd')
                table.setRowHidden(row, not (start_date.date() <= date <= end_date.date()))
        start_date.dateChanged.connect(filter_rows)
        end_date.dateChanged.connect(filter_rows)
        filter_rows()
        def export_summaries():
            path, _ = QFileDialog.getSaveFileName(dialog, 'Export run summaries', 'pid-run-summaries.csv', 'CSV (*.csv)')
            if not path:
                return
            try:
                with open(path, 'w', newline='', encoding='utf-8') as handle:
                    writer = csv.writer(handle)
                    writer.writerow(table.horizontalHeaderItem(col).text() for col in range(table.columnCount()))
                    for row in range(table.rowCount()):
                        if not table.isRowHidden(row):
                            writer.writerow(table.item(row, col).data(Qt.UserRole) or table.item(row, col).text() for col in range(table.columnCount()))
                export.setText('Exported âœ“')
            except OSError as exc:
                export.setText('Export failed')
                export.setToolTip(str(exc))
        export.clicked.connect(export_summaries)
        footer = QHBoxLayout()
        footer.addWidget(QLabel('Double-click a run to view samples'))
        footer.addStretch()
        close = QPushButton('Close')
        close.setFixedSize(100, 36)
        close.clicked.connect(dialog.close)
        footer.addWidget(close)
        layout.addLayout(footer)
        table.cellDoubleClicked.connect(lambda row, col: self.show_csv(valid[row]))
        dialog.exec()
        dialog.deleteLater()

    def show_csv(self, path):
        dialog = QDialog(self)
        dialog.setWindowTitle('PID response CSV')
        dialog.resize(800, 550)
        layout = setup_pid_dialog(dialog, 'PID Response Samples', window_controls=False)
        label = QLabel('Select an inclusive sample range')
        label.setToolTip(str(path))
        label.setWordWrap(True)
        layout.addWidget(label)
        controls = QHBoxLayout()
        first, last = QSpinBox(), QSpinBox()
        for spin in (first, last):
            spin.setRange(1, 1000000000)
            spin.setFixedSize(140, 36)
        first.setValue(1)
        last.setValue(100)
        for title, control in [('First point', first), ('Last point', last)]:
            field = QVBoxLayout()
            field.addWidget(QLabel(title))
            field.addWidget(control)
            controls.addLayout(field)
        controls.addStretch()
        apply = QPushButton('View range')
        export = QPushButton('Export range CSV')
        controls.addWidget(apply)
        controls.addWidget(export)
        layout.addLayout(controls)
        table = QTableWidget()
        table.setShowGrid(False)
        table.verticalHeader().setDefaultSectionSize(32)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(table)
        next_button = QPushButton('Next 1,000 rows')
        layout.addWidget(next_button)
        close = QPushButton('Close')
        close.setFixedSize(100, 36)
        close.clicked.connect(dialog.close)
        layout.addWidget(close, 0, Qt.AlignRight)
        offset = [0]
        def load():
            try:
                with path.open(newline='', encoding='utf-8') as handle:
                    reader = csv.reader(handle)
                    header = next(reader)
                    rows = list(islice(reader, offset[0], min(last.value(), offset[0]+1001)))
                table.setColumnCount(len(header))
                table.setHorizontalHeaderLabels(header)
                table.setRowCount(min(len(rows), 1000))
                table.setVerticalHeaderLabels([str(offset[0]+i+1) for i in range(min(len(rows),1000))])
                for i, row in enumerate(rows[:1000]):
                    for j, value in enumerate(row[:len(header)]):
                        table.setItem(i, j, QTableWidgetItem(value))
                next_button.setEnabled(len(rows) > 1000)
                offset[0] += 1000
                table.resizeColumnsToContents()
            except (OSError, StopIteration, csv.Error) as exc:
                label.setText(f'Cannot read CSV: {exc}')
                next_button.setEnabled(False)
        next_button.clicked.connect(load)
        def view_range():
            if first.value() > last.value():
                label.setText('First point must be less than or equal to last point.')
                return
            offset[0] = first.value()-1
            load()
        apply.clicked.connect(view_range)
        def export_range():
            if first.value() > last.value():
                label.setText('Invalid point range')
                return
            destination, _ = QFileDialog.getSaveFileName(dialog, 'Export selected points', 'pid-samples.csv', 'CSV (*.csv)')
            if not destination:
                return
            from pathlib import Path
            if Path(destination).resolve() == path.resolve():
                label.setText('Choose a different file to preserve the original recording.')
                return
            try:
                count = export_sample_range(path, Path(destination), first.value(), last.value())
                label.setText(f'Exported {count} samples Â· {destination}')
            except (OSError, ValueError, csv.Error) as exc:
                label.setText(f'Export failed: {exc}')
        export.clicked.connect(export_range)
        load()
        dialog.exec()
        dialog.deleteLater()


def export_sample_range(source, destination, first, last):
    """Export one-based inclusive data rows, excluding the CSV header."""
    if first < 1 or last < first or source.resolve() == destination.resolve():
        raise ValueError('Invalid range or destination')
    with source.open(newline='', encoding='utf-8') as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            raise ValueError('Empty source CSV')
        with destination.open('w', newline='', encoding='utf-8') as output:
            writer = csv.writer(output)
            writer.writerow(header)
            count = 0
            for row in islice(reader, first-1, last):
                writer.writerow(row)
                count += 1
    return count
