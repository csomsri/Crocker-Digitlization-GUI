"""Operator workspace composed from the existing PID and BO tools."""
import math
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QCheckBox, QSpinBox, QFormLayout, QStackedWidget, QScrollArea, QStyle
from python.app.ResponsiveLayout import ResponsiveRow
from python.app.widgets.AppDialogs import AppDialog
from python.app.widgets.PidDialog import setup_pid_dialog
from python.app.Automation.GA.TrendPlot import AxisTrendPlot
from python.app.Automation.GA.CppTrendPlot import CppTrendPlot
from python.app.Automation.SurrogatePlotWidget import SurrogatePlotWidget


class CruisePageStack(QStackedWidget):
    """Hidden engineering pages must not force a desktop minimum width."""
    def minimumSizeHint(self):
        current = self.currentWidget()
        return QSize(0, current.minimumSizeHint().height() if current else 0)


class ControlActivity(QWidget):
    """Quiet activity animation, independent of controller execution."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 24)
        self.busy = False
        self.phase = 0
        self.timer = QTimer(self)
        self.timer.setInterval(160)
        self.timer.timeout.connect(self.advance)
        self.setAccessibleName('Control stopped')

    def set_activity(self, busy, label):
        self.busy = busy
        self.setAccessibleName(label)
        self.setToolTip(label)
        if busy and self.isVisible():
            if not self.timer.isActive():
                self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def advance(self):
        self.phase = (self.phase+1) % 3
        self.update()

    def showEvent(self, event):
        if self.busy:
            self.timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        for index in range(3):
            color = QColor('#91b9e6' if self.busy else '#71869f')
            color.setAlpha(255 if self.busy and index == self.phase else 85)
            painter.setBrush(color)
            painter.drawEllipse(3+index*12, 8, 6, 6)


class CruiseWorkspace(QWidget):
    def __init__(self, page):
        super().__init__()
        self.setObjectName('cruiseWorkspace')
        self.setStyleSheet('''
            QWidget#cruiseWorkspace { background: #0d1726; }
            QWidget#cruiseWorkspace QLabel { color: #c5d6e9; }
            QFrame#cruiseSection { background: #101d2d; border: 1px solid #2c4058; border-radius: 8px; }
            QWidget#cruiseWorkspace QPushButton { background: #1d324b; color: #e9f1fa; border: 1px solid #3d5878;
                border-radius: 6px; padding: 9px 14px; font-size: 13px; font-weight: 600; }
            QWidget#cruiseWorkspace QPushButton:hover { background: #294764; }
            QWidget#cruiseWorkspace QPushButton:disabled { color: #71869f; background: #162337; border-color: #293b50; }
            QWidget#cruiseWorkspace QPushButton#cruiseStart:enabled { border-color: #91b9e6; }
            QWidget#cruiseWorkspace QPushButton#cruiseApply:enabled { border-color: #91b9e6; }
            QWidget#cruiseWorkspace QPushButton#cruiseStop:enabled { border-color: #91b9e6; }
            QWidget#cruiseWorkspace QDoubleSpinBox { background: #182b40; color: #edf4fc; border: 1px solid #3d5878;
                border-radius: 6px; padding: 7px; min-height: 24px; }
        ''')
        self.page = page
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        control_section = QFrame()
        control_section.setObjectName('cruiseSection')
        control_layout = QVBoxLayout(control_section)
        control_layout.setContentsMargins(14, 12, 14, 12)
        controls = ResponsiveRow()
        for label, widget in [('Trim coil', page.channel_select), ('Beam target (nA)', page.setpoint_input)]:
            field = QVBoxLayout()
            field.addWidget(QLabel(label))
            field.addWidget(widget)
            controls.addLayout(field, 1)
        self.start = QPushButton('Start')
        self.start.setObjectName('cruiseStart')
        self.start.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.start.clicked.connect(page._start_cruise)
        self.stop = QPushButton('Stop')
        self.stop.setObjectName('cruiseStop')
        self.stop.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.stop.setToolTip('Cancel BO and PID, disable control/output on the selected coil; current follows the hardware stop behavior.')
        self.stop.clicked.connect(page._stop_cruise)
        self.apply = QPushButton('Apply BO')
        self.apply.setObjectName('cruiseApply')
        self.apply.clicked.connect(page._apply_cruise_gains)
        self.apply.setEnabled(False)
        action_field = QVBoxLayout()
        action_field.addWidget(QLabel('Control'))
        actions = QHBoxLayout()
        actions.setSpacing(8)
        for button in (self.start, self.stop, self.apply):
            button.setMinimumHeight(42)
            button.setMinimumWidth(104)
            actions.addWidget(button, 1)
        action_field.addLayout(actions)
        controls.addLayout(action_field)
        control_layout.addLayout(controls)
        layout.addWidget(control_section)
        self.status = QLabel('Stopped · Set the beam target, then Start.')
        self.status.setWordWrap(True)
        self.status.setStyleSheet('color: #e5edf7; padding: 4px;')
        state_row = ResponsiveRow()
        self.activity = ControlActivity()
        state_row.addWidget(self.activity)
        state_row.addWidget(self.status, 1)
        self.connection = QLabel()
        self.connection.setWordWrap(False)
        state_row.addWidget(self.connection)
        control_layout.addLayout(state_row)
        self.limits = QLabel('Hardware limits come from the selected coil profile · Start engages live control')
        self.limits.setWordWrap(True)
        self.limits.hide()
        layout.addWidget(page.time_plot, 3)
        self.bottom = QGridLayout()
        self.cost = CppTrendPlot(AxisTrendPlot('BO COST', 'Time (s)'),
                                 ('Best eligible', 'Trial cost'), display_y_label='BO cost · lower is better')
        self.cost.setMinimumHeight(290)
        cost_panel = QFrame()
        cost_panel.setObjectName('cruiseSection')
        cost_layout = QVBoxLayout(cost_panel)
        cost_layout.setContentsMargins(12, 10, 12, 10)
        self.cost_note = QLabel('BO cost over time · No trials yet')
        self.cost_note.setWordWrap(True)
        cost_layout.addWidget(self.cost_note)
        cost_layout.addWidget(self.cost, 1)
        model_panel = QFrame()
        model_panel.setObjectName('cruiseSection')
        model_layout = QVBoxLayout(model_panel)
        model_layout.setContentsMargins(12, 10, 12, 10)
        model_heading = ResponsiveRow()
        model_heading.addWidget(QLabel('BO model'))
        # One axis selector controls both the embedded and expanded views.
        model_heading.addWidget(page.surrogate_axis)
        expand = QPushButton('Expand model')
        expand.clicked.connect(page._show_gain_model)
        model_heading.addWidget(expand)
        model_layout.addLayout(model_heading)
        self.surrogate = SurrogatePlotWidget()
        model_layout.addWidget(self.surrogate, 1)
        self.bottom.addWidget(cost_panel, 0, 0)
        self.bottom.addWidget(model_panel, 0, 1)
        self.bottom.setColumnStretch(0, 1)
        self.bottom.setColumnStretch(1, 1)
        self.cost_panel, self.model_panel = cost_panel, model_panel
        layout.addLayout(self.bottom, 2)
        self.tune = QPushButton('Tune now')
        self.tune.clicked.connect(page._begin_cruise_tuning)
        settings = QPushButton('Operator settings')
        settings.clicked.connect(self.show_settings)
        advanced = QPushButton('Diagnostics')
        self.rollback = QPushButton('Restore previous gains')
        self.rollback.clicked.connect(page._rollback_cruise)
        for button in (self.tune, settings):
            button.setMinimumHeight(32)
            state_row.addWidget(button)
        self.diagnostics = AppDialog(page)
        self.diagnostics.resize(780, 450)
        diagnostics_layout = setup_pid_dialog(self.diagnostics, 'Connection and hardware details', window_controls=False)
        diagnostics_layout.addWidget(page.backend_status_panel)
        diagnostics_layout.addWidget(self.limits)
        self.limits.show()
        done = QPushButton('Done')
        done.clicked.connect(self.diagnostics.accept)
        diagnostics_layout.addWidget(done)
        advanced.clicked.connect(lambda: (self.settings.accept(), self.diagnostics.show()))
        self.settings = AppDialog(page)
        self.settings.resize(720, 700)
        content = setup_pid_dialog(self.settings, 'Cruise operator settings', window_controls=False)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(body)
        content.addWidget(scroll, 1)
        self.automatic = QCheckBox('Automatically run BO after persistent drift')
        self.automatic.setChecked(True)
        body_layout.addWidget(self.automatic)
        self.wait_for_ramp = QCheckBox('Wait for coil tracking before automatic BO')
        self.wait_for_ramp.setChecked(False)
        body_layout.addWidget(self.wait_for_ramp)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.band = page._make_spinbox(.001, 100, .05, ' nA')
        self.band.setValue(.3)
        self.persistence = page._make_spinbox(.5, 600, 1, ' s')
        self.persistence.setValue(15)
        self.cooldown = page._make_spinbox(1, 3600, 5, ' s')
        self.cooldown.setValue(15)
        self.max_sessions = QSpinBox()
        self.max_sessions.setRange(0, 100)
        self.max_sessions.setSpecialValueText('Unlimited')
        self.max_sessions.setValue(0)
        page.validation_duration.setValue(20)
        self.ramp_tolerance = page._make_spinbox(.01, 100, .1, ' A')
        self.ramp_tolerance.setValue(.5)
        self.search_minutes = page._make_spinbox(.1, 240, 1, ' min')
        self.search_minutes.setValue(30)
        self.search_minutes.setToolTip('Checked between trials. The active trial finishes; best-gain validation runs separately.')
        self.patience = QSpinBox()
        self.patience.setRange(2, 50)
        self.patience.setValue(5)
        for label, widget in [('Tracking error band', self.band), ('Drift persistence', self.persistence),
                              ('Settling / recovery cooldown', self.cooldown), ('Automatic BO sessions per Start', self.max_sessions),
                              ('Coil ramp tracking tolerance', self.ramp_tolerance),
                              ('Maximum BO search time', self.search_minutes), ('Trials without improvement before stopping', self.patience),
                              ('Validation duration', page.validation_duration)]:
            form.addRow(label, widget)
        body_layout.addLayout(form)
        tools = ResponsiveRow()
        engineering = QPushButton('PID / BO settings')
        engineering.clicked.connect(lambda: (self.settings.accept(), page._show_cruise_advanced()))
        for button in (engineering, advanced, self.rollback):
            tools.addWidget(button)
        body_layout.addLayout(tools)
        body_layout.addStretch()
        close = QPushButton('Done')
        close.clicked.connect(self.settings.accept)
        content.addWidget(close, 0, Qt.AlignRight)

    def show_settings(self):
        self.settings.show()

    def resizeEvent(self, event):
        self.bottom.removeWidget(self.model_panel)
        self.bottom.addWidget(self.model_panel, 1 if self.width() < 760 else 0, 0 if self.width() < 760 else 1)
        super().resizeEvent(event)

    def refresh(self):
        p = self.page
        active = p.cruise.active
        tuning = p.tuning_session_active
        pending = p._cruise_pending
        running = p.pid_enabled or tuning
        self.activity.set_activity(running, 'Validating BO' if p._validating_gains else 'BO running' if tuning else 'PID running' if p.pid_enabled else 'Control stopped')
        self.start.setText('Running' if running else 'Start')
        self.start.setEnabled(not active and not tuning and not p.pid_enabled and not p._cruise_stop_failed)
        self.stop.setEnabled(active or tuning or p.pid_enabled or p._tuning_output_held or p._cruise_stop_failed)
        self.apply.setEnabled(active and not tuning and pending and p.apply_tuned_gains_button.isEnabled())
        self.tune.setEnabled(active and p.pid_enabled and not tuning and not pending)
        self.rollback.setEnabled(active and not tuning and p._cruise_previous is not None)
        p.channel_select.setEnabled(not active and not tuning and not p.pid_enabled)
        p.setpoint_input.setEnabled(not active and not tuning and not p.pid_enabled)
        self.automatic.setEnabled(not tuning)
        p.validation_duration.setEnabled(not tuning)
        self.search_minutes.setEnabled(not tuning)
        self.patience.setEnabled(not tuning)
        if tuning:
            text = ('Validating BO' if p._validating_gains else 'Running BO') + ' · ' + p.tuner_status.text()
        elif active and p.pid_enabled:
            error = p.setpoint_input.value()-p._feedback_value()
            text = f'PID holding · Error {error:+.3f} nA · {p._cruise_message}'
            if not p._cruise_pending and self.wait_for_ramp.isChecked() and not p._cruise_ramp_settled():
                text += ' · Waiting for actual coil current to follow its target'
            elif not p._cruise_pending and self.automatic.isChecked() and self.max_sessions.value() > 0 and p.cruise.sessions >= self.max_sessions.value():
                text += ' · Automatic session cap reached; Tune now remains available'
        else:
            text = p._cruise_message if active else 'Stopped · ' + p.last_safety_message
        self.status.setToolTip(text)
        if tuning:
            state = 'Validating BO' if p._validating_gains else 'BO search'
            text = f'{state} · {len(p.tuning_results)} / {p.tuner_trials.value()} trials'
        elif active and p.pid_enabled:
            text = f'PID running · Error {error:+.3f} nA' + (' · BO ready to apply' if pending else '')
        elif (p._cruise_stop_failed or p.last_safety_message.startswith(('Start blocked', 'Resume blocked'))
              or any(word in p.last_safety_message.lower() for word in ('fault', 'failed', 'expired', 'interlock', 'unavailable', 'stale'))):
            text = p.last_safety_message
        else:
            text = 'Stopped · Set target, then Start'
        self.status.setText(text)
        connected = p.backend_available and p.backend_connection.lower() == 'connected'
        self.connection.setText(('Connected' if connected else 'Disconnected') + ' · ' + ('Hardware' if (p.backend_mode != 'simulation' and p.simulation_mode != 'first-order') else 'Simulation'))
        self.limits.setText(getattr(p, '_cruise_limits_text', 'Hardware limits come from the selected coil profile · Start engages live control'))
        times, best_values, costs = [], [], []
        best = math.inf
        for elapsed, result in p._cruise_costs:
            times.append(elapsed)
            eligible = result.safe
            if eligible:
                best = min(best, result.score)
            best_values.append(best if math.isfinite(best) else math.nan)
            costs.append(result.score if result.safe else math.nan)
        self.cost.set_data(times, best_values, costs)
        aborted = sum(not r.safe for _, r in p._cruise_costs)
        self.cost_note.setText(f'BO cost · {len(costs)} trials')
        self.cost_note.setToolTip(f'{aborted} aborted or invalid trials excluded from the curve')
        baseline = getattr(p, '_cruise_baseline', None)
        validated_cost = getattr(p, '_cruise_validation_cost', None)
        if baseline is not None and baseline.safe and validated_cost is not None:
            self.cost_note.setToolTip(self.cost_note.toolTip()+f' · Baseline {baseline.score:.4g} / validation {validated_cost:.4g}')
        self.surrogate.set_state(grid=p.tuning_surrogate_grid, results=p.tuning_results,
                                candidate=p.tuning_candidate or p.tuning_trial_candidate,
                                best=p.tuning_optimizer.best_result if p.tuning_optimizer else None,
                                axis_x=p.surrogate_axis.currentData())
