"""Editable hardware limits, saved as a draft until explicitly reviewed."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QScrollArea, QWidget, QTabWidget,
    QVBoxLayout, QGridLayout, QFrame, QAbstractSpinBox,
)

from python.app.widgets.PidDialog import setup_pid_dialog
from source.Python.Automation.hardware_profile import HardwareProfile, approve_operator_limits


PROFILE_PATH = Path(__file__).resolve().parents[3] / 'config' / 'pid_hardware_profile.json'
FIELDS = (
    ('minimum_command', 'Minimum current', ' A', 0.0),
    ('maximum_command', 'Maximum current', ' A', 1.0),
    ('max_absolute_error', 'Abort: absolute beam error', ' nA', 1.0),
    ('max_overshoot', 'Abort: beam overshoot', ' nA', 0.5),
    ('max_control_output', 'Abort: PID correction per update', ' A', 0.05),
    ('max_saturation_seconds', 'Abort: time at saturation', ' s', 2.0),
)
PROVENANCE = (
    ('measurement_date', 'Measurement date (YYYY-MM-DD)'),
    ('machine_configuration', 'Machine configuration'),
    ('units', 'Units'), ('operator', 'Operator'), ('reviewer', 'Independent reviewer'),
    ('source_dataset', 'Calibration record / dataset'), ('uncertainty', 'Uncertainty'),
    ('valid_until', 'Valid until (YYYY-MM-DD)'),
)


class ProfileNumber(QDoubleSpinBox):
    def textFromValue(self, value):
        return super().textFromValue(value).rstrip('0').rstrip(self.locale().decimalPoint())


class HardwareProfileDialog(QDialog):
    def __init__(self, parent, channel_names, *, path=PROFILE_PATH, can_save=lambda: True, initial_channel=None):
        super().__init__(parent)
        self.path = Path(path)
        self.channel_names = tuple(channel_names)
        self.can_save = can_save
        self.original = self.path.read_bytes()
        self.data = json.loads(self.original)
        self.current_channel = None
        layout = setup_pid_dialog(self, 'Hardware PID Profile', window_controls=False, resize_grip=False)
        self.setStyleSheet(self.styleSheet() + '''
            QLineEdit, QDoubleSpinBox, QComboBox { background: #111e30; color: #e7eef8;
                border: 1px solid #3b526e; border-radius: 6px; padding: 0 10px;
                min-height: 0; font-family: 'Segoe UI'; font-size: 13px; }
            QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #74a9df; }
            QCheckBox { color: #e7eef8; font-family: 'Segoe UI'; font-size: 12px; }
            QFrame#profileCard { background: #142235; border: 1px solid #2b405a; border-radius: 8px; }
            QLabel#profileSection { color: #8eafd1; font-size: 12px; font-weight: 600; }
            QTabWidget::pane { border: none; }
            QTabBar::tab { background: #142235; color: #9eb3cd; padding: 10px 20px; }
            QTabBar::tab:selected { color: #eef5ff; background: #243e60; }
            QPushButton { min-height: 0; padding: 0 16px; border-radius: 6px;
                background: #23354c; color: #e7eef8; border: 1px solid #405674; font-size: 13px; }
            QPushButton#profileSave { background: #28639a; border-color: #4385bd; }
        ''')
        note = QLabel('Configure current limits and beam abort thresholds. '
                      'Draft values require review before hardware use.')
        note.setWordWrap(True)
        layout.addWidget(note)
        tabs = self.tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        def tab(title):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            contents = QWidget()
            contents.setObjectName('profileTabContents')
            contents.setStyleSheet('QWidget#profileTabContents { background: #101a29; }')
            body = QVBoxLayout(contents)
            body.setContentsMargins(0, 12, 0, 0)
            body.setSpacing(12)
            scroll.setWidget(contents)
            scroll.setStyleSheet('QScrollArea { border: none; }')
            tabs.addTab(scroll, title)
            return body
        limits_tab = tab('Operating limits')
        advanced_tab = tab('Advanced limits')
        review_tab = tab('Calibration & review')
        def card(body, title):
            frame = QFrame()
            frame.setObjectName('profileCard')
            frame.setStyleSheet('QFrame#profileCard { background: #142235; border: 1px solid #2b405a; border-radius: 8px; }')
            grid = QGridLayout(frame)
            grid.setContentsMargins(12, 8, 12, 10)
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(4)
            heading = QLabel(title)
            heading.setObjectName('profileSection')
            heading.setFixedHeight(18)
            heading.setStyleSheet('color: #8eafd1; font-size: 12px; font-weight: 600;')
            grid.addWidget(heading, 0, 0, 1, 2)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            body.addWidget(frame)
            return grid
        def field(grid, index, label, widget, *, wide=False):
            row, column = divmod(index, 2)
            text = QLabel(label)
            text.setWordWrap(True)
            widget.setFixedHeight(32)
            widget.setMinimumWidth(0)
            grid.addWidget(text, row*2+1, column, 1, 2 if wide else 1)
            grid.addWidget(widget, row*2+2, column, 1, 2 if wide else 1)
        identity = card(limits_tab, 'PROFILE')
        self.name = QLineEdit(str(self.data.get('profile_name', 'Hardware PID profile')))
        field(identity, 0, 'Profile name', self.name)
        self.channel = QComboBox()
        self.channel.addItems(list(self.channel_names[:12]))
        field(identity, 1, 'Actuator coil', self.channel)
        self.inputs = {}
        current = card(limits_tab, 'COIL CURRENT')
        abort = card(advanced_tab, 'ABORT THRESHOLDS')
        for index, (key, label, suffix, default) in enumerate(FIELDS):
            widget = ProfileNumber()
            widget.setRange(0, 1e9)
            widget.setDecimals(6)
            widget.setSingleStep(0.01)
            widget.setSuffix(suffix)
            widget.setButtonSymbols(QAbstractSpinBox.NoButtons)
            widget.setKeyboardTracking(False)
            widget.setToolTip(label)
            self.inputs[key] = widget
            short_label = label.replace('Abort: ', '').replace('Recorded baseline (does not move coil)', 'Recorded baseline')
            short_label = short_label[0].upper() + short_label[1:]
            field(current if index < 2 else abort, index if index < 2 else index-2, short_label, widget)
        ramp_note = QLabel('LabVIEW handles current ramping. PID starts from the live coil command.\nGA/hybrid capture their recovery baseline automatically.')
        ramp_note.setWordWrap(True)
        limits_tab.addWidget(ramp_note)
        advanced_tab.addStretch()
        limits_tab.addStretch()
        self.provenance = {}
        provenance_grid = card(review_tab, 'CALIBRATION RECORD')
        for index, (key, label) in enumerate(PROVENANCE):
            widget = QLineEdit(str(self.data.get('provenance', {}).get(key, '')))
            self.provenance[key] = widget
            field(provenance_grid, index*2, label, widget, wide=True)
        review_tab.addStretch()
        self.reviewed = QCheckBox('Independently reviewed for this machine')
        if self.data.get('approval_basis') == 'operator_limits':
            self.reviewed.setText('I approve these operating limits for hardware testing')
        self.reviewed.setChecked(False)
        layout.addWidget(self.reviewed)
        self.status = QLabel(f"Loaded: {self.data.get('approval_status', 'draft')}. Save defaults to draft.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.save_button = QPushButton('Save profile')
        self.save_button.setObjectName('profileSave')
        self.save_button.setStyleSheet('background: #28639a; color: white; border: 1px solid #4385bd; border-radius: 6px; padding: 0; min-height: 0; text-align: center;')
        self.save_button.setFixedSize(140, 36)
        self.save_button.clicked.connect(self.save_profile)
        close = QPushButton('Close')
        close.setFixedSize(100, 36)
        close.clicked.connect(self.close)
        buttons.addStretch()
        buttons.addWidget(close)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)
        existing = self.data.get('measurement_channels', {})
        initial = next((name for name in existing if name in self.channel_names[:12]), self.channel_names[0])
        if initial_channel in self.channel_names[:12]:
            initial = initial_channel
        self.channel.setCurrentText(initial)
        self._change_channel(initial)
        if initial not in existing:
            self.status.setText(f'{initial} has no saved profile. New values are draft examples; enter the operating limits before review.')
        self.channel.currentTextChanged.connect(self._change_channel)
        for widget in (*self.inputs.values(),):
            widget.valueChanged.connect(lambda *_: self.reviewed.setChecked(False))
        for widget in (self.name, *self.provenance.values()):
            widget.textChanged.connect(lambda *_: self.reviewed.setChecked(False))
        self._save_future = None
        self._save_timer = QTimer(self)
        self._save_timer.setInterval(25)
        self._save_timer.timeout.connect(self._finish_save)
        self.resize(700, 620)

    def _store_channel(self):
        if self.current_channel is None:
            return
        name = self.current_channel
        entries = self.data.setdefault('measurement_channels', {})
        entry = entries.setdefault(name, {})
        entry['allocation'] = {name: 1.0}
        entry['ramp_control'] = 'labview'
        entry.pop('command_bias', None)
        entry.pop('maximum_slew_per_second', None)
        for key, _, _, _ in FIELDS:
            if key.startswith('max_'):
                entry.setdefault('abort_limits', {})[key] = self.inputs[key].value()
            else:
                mapping = {channel: 0.0 for channel in self.channel_names}
                mapping[name] = self.inputs[key].value()
                entry[key] = mapping

    def _change_channel(self, name):
        self._store_channel()
        self.current_channel = name
        entry = self.data.get('measurement_channels', {}).get(name, {})
        for key, _, _, default in FIELDS:
            value = (entry.get('abort_limits', {}).get(key, default) if key.startswith('max_')
                     else entry.get(key, {}).get(name, default))
            self.inputs[key].setValue(float(value))
        self.reviewed.setChecked(False)

    def save_profile(self):
        if self._save_future is not None:
            return
        try:
            if not self.can_save():
                raise ValueError('Stop PID and optimization sessions before saving the profile.')
            self._store_channel()
            source = deepcopy(self.data)
            source['profile_name'] = self.name.text().strip()
            source['provenance'] = {key: widget.text().strip() for key, widget in self.provenance.items()}
            source['approval_status'] = 'approved' if self.reviewed.isChecked() else 'draft'
            if self.reviewed.isChecked() and source.get('approval_basis') == 'operator_limits':
                approve_operator_limits(source, approved_by='Operator via PID profile editor',
                                        statement='Explicitly approved the displayed operating limits for hardware testing.')
            self._save_future = _SAVES.submit(_write_profile, self.path, self.original, source, self.channel_names)
            self.tabs.setEnabled(False)
            self.reviewed.setEnabled(False)
            self.save_button.setEnabled(False)
            self.status.setText('Saving… You can close this window; saving will finish in the background.')
            self._save_timer.start()
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.status.setText(f'Not saved: {exc}')

    def _finish_save(self):
        if self._save_future is None or not self._save_future.done():
            return
        self._save_timer.stop()
        try:
            self.data, self.original = self._save_future.result()
            self.status.setText(f"Saved {self.data['approval_status']} profile. Used at the next trial start.")
        except Exception as exc:
            self.status.setText(f'Not saved: {exc}')
        finally:
            self._save_future = None
            self.tabs.setEnabled(True)
            self.reviewed.setEnabled(True)
            self.save_button.setEnabled(True)


# Serial writes also protect against two editors saving the same old version.
_SAVES = ThreadPoolExecutor(max_workers=1, thread_name_prefix='hardware-profile-save')


def _write_profile(path, original, source, channel_names):
    if path.read_bytes() != original:
        raise ValueError('Profile changed elsewhere. Close and reopen this editor before saving.')
    HardwareProfile.from_data(source, channel_names, require_approved=source['approval_status'] == 'approved')
    payload = (json.dumps(source, indent=2, allow_nan=False) + '\n').encode('utf-8')
    output = QSaveFile(str(path))
    if not output.open(QIODevice.WriteOnly):
        raise OSError(output.errorString())
    if output.write(payload) != len(payload):
        output.cancelWriting()
        raise OSError(output.errorString())
    if not output.commit():
        raise OSError(output.errorString())
    return source, payload
