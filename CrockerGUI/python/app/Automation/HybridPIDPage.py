"""Hybrid search workspace; C++ owns PID trials, Python owns search/recovery sequencing."""
import csv
from source.Python.Data.file_writer import file_writer, write_csv, write_text
import json
import math
import time
from html import escape
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QWidget,
    QScrollArea,
    QAbstractItemView,
    QFrame,
    QSizePolicy,
    QGraphicsOpacityEffect,
)
from python.app.widgets.AppDialogs import AppDialog as QDialog, AppFileDialog as QFileDialog
from python.app.Automation.PidControlPage import PidControlPage
from python.app.ResponsiveLayout import ResponsiveRow
from python.app.Automation.ControlOwnership import active_controller
from python.app.widgets.PidDialog import setup_pid_dialog
from python.app.widgets.DisplayNumbers import display_number
from source.Python.Optimization.hybrid_pid_optimizer import HybridPIDOptimizer, HybridConfig
from source.Python.Optimization.pid_gain_adapter import PidGainCandidate, PidTrialResult
from source.Python.Optimization.trial_metrics import evaluate_trial, trial_cost
from source.Python.Automation.ga_recovery import GARecoveryManager, GARecoveryConfig
from source.Python.Automation.ga_backend_adapter import GABackendAdapter


class OperatorDecimalSpinBox(QDoubleSpinBox):
    def textFromValue(self, value):
        return display_number(value, significant=12, grouping=False, max_decimals=12)


class HybridCostPlot(QWidget):
    """Measured costs are colored by origin; model predictions have separate error bars."""
    def __init__(self, records, parent=None, *, compact=False):
        super().__init__(parent)
        self.records = records
        self.compact = compact
        self.setMinimumSize(500, 230)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setFont(QFont('Segoe UI', 10))
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor('#101a29'))
        colors = {'Baseline':'#c5a0ff','Reference':'#c5a0ff','Exploration':'#ffcf82','GA':'#ffbf78','BO':'#65cfff','Confirm':'#52d6b1'}
        p.setPen(QColor('#dce7f5'))
        p.drawText(16,24,'Measured performance · Lower is better' if self.compact else 'Baseline/reference: purple · Exploration: yellow · GA: orange · BO: blue · Confirmation: green')
        p.drawText(16,44,'Solid: measured · Hollow: predicted' if self.compact else 'Prediction: hollow gray point ±1 model standard deviation. Failed trials have no comparable cost.')
        rows = [r for r in self.records if r['cost'] is not None]
        values = [r['cost'] for r in rows]
        values += [max(0,r['prediction']+r['prediction_std']) for r in rows if r['prediction'] is not None]
        high = max(values,default=1)*1.1 or 1
        ticks = [display_number(high*i/4) for i in range(5)]
        left = max(70, max(p.fontMetrics().horizontalAdvance(t) for t in ticks)+16)
        rect = QRectF(left,64,max(1,self.width()-left-20),self.height()-105)
        n = max((r['trial'] for r in self.records), default=1)
        def point(i,v):
            return QPointF(rect.left()+(i-1)*rect.width()/max(1,n-1),rect.bottom()-max(0,v)/high*rect.height())
        for i in range(5):
            y = rect.bottom()-rect.height()*i/4
            p.setPen(QColor('#29394e'))
            p.drawLine(QPointF(rect.left(),y),QPointF(rect.right(),y))
            p.setPen(QColor('#cbd5e1'))
            p.drawText(QRectF(0,y-9,left-10,18),Qt.AlignRight,ticks[i])
        p.drawText(left,self.height()-15,f'Trial 1 → {n}     Lower cost is better')
        p.setClipRect(rect.adjusted(-5,-5,5,5))
        for r in rows:
            if r['prediction'] is not None:
                mu,sd = r['prediction'],r['prediction_std']
                p.setPen(QPen(QColor('#94a3b8'),1))
                p.setBrush(Qt.NoBrush)
                p.drawLine(point(r['trial'],mu-sd),point(r['trial'],mu+sd))
                p.drawEllipse(point(r['trial'],mu),4,4)
            color = next((v for k,v in colors.items() if r['source'].startswith(k)), '#ffffff')
            p.setPen(QColor(color))
            p.setBrush(QColor(color))
            p.drawEllipse(point(r['trial'],r['cost']),3,3)


class HybridPIDPage(PidControlPage):
    engine_kind = 'hybrid_cpp'

    def _make_spinbox(self, lower, upper, step, suffix=''):
        spinbox = OperatorDecimalSpinBox()
        spinbox.setObjectName('pidSpin')
        spinbox.setRange(lower, upper)
        spinbox.setDecimals(3 if step < .1 else 2)
        spinbox.setSingleStep(step)
        spinbox.setSuffix(suffix)
        return spinbox

    def __init__(self, *args, **kwargs):
        self.recovering = False
        self.reference = None
        self.hybrid = None
        self._recovery_action = None
        self._validation_result = None
        self._session_fingerprint = None
        self._session_path = None
        super().__init__(*args, **kwargs)
        self.log_path = self.log_path.with_name('hybrid_beam_pid_commands.csv')
        self.header.title = 'HYBRID GA + BO PID'
        self.header.update()
        self.tuner_trials.setRange(12,500)
        self.tuner_trials.setValue(48)
        self.tuner_engine_label.setText('Hybrid GA + BO — C++ beam PID')
        self.open_tuner_button.setText('Hybrid GA + BO tuner')
        self.auto_tuning_button.setText('Run hybrid budget')
        self.stop_tuning_button.setText('Stop / disable output')
        self.hybrid_settings = QDialog(self)
        self.hybrid_settings.setWindowTitle('Hybrid settings and recovery')
        layout = setup_pid_dialog(self.hybrid_settings, 'Hybrid settings and recovery', window_controls=False)
        self.hybrid_settings.setStyleSheet(self.hybrid_settings.styleSheet()+'''
            QScrollArea, QScrollArea > QWidget > QWidget, QTabWidget::pane { background: #101a29; border: none; }
            QTabBar::tab { background: #1b2c42; color: #cbd5e1; padding: 9px 16px; }
            QTabBar::tab:selected { background: #315477; color: white; }
        ''')
        tabs = QTabWidget()
        layout.addWidget(tabs)
        self.hybrid_fields = {}
        fields = [
            ('GA', [('population','Population',6,4,30,0),('baseline_repeats','Baseline repeats',3,2,10,0),
                    ('mutation_probability','Mutation probability',.25,0,1,3),('mutation_scale','Mutation scale / gain span',.1,0,1,3),('seed','Random seed',1729,0,999999,0)]),
            ('Handover', [('minimum_distinct','Distinct points before BO',12,4,100,0),('coverage','Minimum span / gain bound',.35,.05,1,3),
                    ('improvement_fraction','Minimum improvement: cost AND beam MAE',.05,.001,1,3),('confirmation_pairs','Paired confirmations',3,3,10,0),('plateau_trials','BO trials without improvement',5,1,30,0)]),
            ('Data quality', [('reference_interval','Trials between reference batches',8,1,100,0),
                    ('exploration_interval','Search trials between exploration points',5,1,100,0),
                    ('drift_fraction','Reference drift fraction',.2,.001,1,3)]),
            ('Trials and recovery', [('warmup','Warmup within trial (s)',5,0,120,2),('max_error','Beam error abort (nA)',3,.01,1000,3),
                    ('excursion','Maximum TC excursion from baseline (A)',.5,.01,100,3),('saturation','Saturation abort (s)',5,.1,60,2),
                    ('recovery_step','Recovery command step (A)',.02,.001,1,3),('recovery_hold','Baseline stable hold (s)',2,.1,30,2),
                    ('recovery_timeout','Recovery timeout (s)',20,1,300,2),('beam_tolerance','Baseline beam tolerance (nA)',.05,.001,10,3),
                    ('actual_tolerance','Baseline TC actual tolerance (A)',.1,.001,10,3)])]
        for title,entries in fields:
            content = QWidget()
            form = QFormLayout(content)
            for key,label,value,low,high,decimals in entries:
                control = QDoubleSpinBox() if decimals else QSpinBox()
                control.setRange(low,high)
                if decimals:
                    control.setDecimals(decimals)
                    control.setSingleStep(10**-decimals)
                control.setValue(value)
                self.hybrid_fields[key] = control
                form.addRow(label,control)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(content)
            tabs.addTab(scroll,title)
        note = QLabel('One shared cost profile and fixed trial window for GA and BO. All candidates restore the same baseline.\n'
                      'BO predicts cost. Handover requires measured cost AND beam MAE improvement beyond their separate noise margins.\n'
                      'Final validation lasts at least 60 seconds and is separate from the search budget.\n'
                      'Stock smoke/smoke2/cyclotron simulations do not couple TC current to beam output.')
        note.setWordWrap(True)
        layout.addWidget(note)
        close = QPushButton('Close settings')
        close.clicked.connect(self.hybrid_settings.close)
        layout.addWidget(close)
        for label in self.hybrid_settings.findChildren(QLabel):
            if label.text() == 'Hybrid settings and recovery':
                label.setMinimumWidth(350)
                label.setWordWrap(False)
        self.hybrid_settings.resize(660,510)
        strip = QWidget()
        row = QHBoxLayout(strip)
        self.state_label = QLabel('Baseline → GA → BO challenger → Confirmation → BO → Validation')
        self.state_label.setStyleSheet('color: #dce7f5; padding: 4px;')
        self.state_label.setWordWrap(True)
        row.addWidget(self.state_label,1)
        settings = QPushButton('Hybrid settings')
        settings.clicked.connect(self.hybrid_settings.show)
        row.addWidget(settings)
        history = QPushButton('Shared history / costs')
        history.clicked.connect(self._show_hybrid_history)
        row.addWidget(history)
        self.restore_button = QPushButton('Abort and restore baseline')
        self.restore_button.clicked.connect(self._abort_restore)
        self.restore_button.setEnabled(False)
        row.addWidget(self.restore_button)
        enable = QPushButton('Enable selected TC')
        enable.clicked.connect(self._enable_selected_tc)
        row.addWidget(enable)
        self.tuner_page.layout().insertWidget(0,strip)
        content = self.tuner_page
        self.page_stack.removeWidget(content)
        self.tuner_page = QScrollArea()
        self.tuner_page.setWidgetResizable(True)
        self.tuner_page.setWidget(content)
        self.tuner_page.setFrameShape(QScrollArea.NoFrame)
        self.page_stack.addWidget(self.tuner_page)
        self.recovery = GARecoveryManager()
        for label in self.findChildren(QLabel):
            if label.text() == 'PID Control':
                label.setText('Hybrid GA + BO PID')
        self._build_operator_workspace()

    def _build_operator_workspace(self):
        """Keep the execution widgets, but put everyday actions before configuration."""
        self.setStyleSheet(self.styleSheet() + '''
            QLabel { color: #e8eaed; font-family: "Segoe UI"; font-size: 13px; }
            QFrame#hybridDashboardCard { background: #18222f; border: 1px solid #344357; border-radius: 16px; }
            QLabel#hybridHeading { font-size: 24px; font-weight: 600; }
            QLabel#hybridCaption { color: #9da3ad; font-size: 12px; }
            QLabel#hybridReadout { font-size: 19px; font-weight: 600; padding: 8px; }
            QPushButton { font-family: "Segoe UI"; background: #292c31; color: #f4f4f4;
                border: 1px solid #454950; border-radius: 9px; padding: 10px 18px; }
            QPushButton:hover { background: #3a3e44; }
            QPushButton:disabled { color: #767c86; background: #22252a; }
            QPushButton#hybridStart { background: #52d6b1; color: #102b25; border: 1px solid #72e9c7;
                font-size: 16px; font-weight: 700; padding: 12px 24px; }
            QPushButton#hybridStart:hover { background: #79e7c9; }
            QPushButton#hybridStart:disabled { background: #213f3c; color: #9ccec0; border-color: #345c54; }
            QPushButton#hybridStop { background: #d63750; color: #ffffff; border: 1px solid #ff7689;
                font-size: 16px; font-weight: 700; padding: 12px 24px; }
            QPushButton#hybridStop:hover { background: #ee4963; }
            QComboBox, QAbstractSpinBox { font-family: "Segoe UI"; font-size: 15px;
                background: #17191d; color: #f2f3f5; border: 1px solid #454950;
                border-radius: 9px; padding: 8px 12px; min-height: 26px; }
        ''')
        self.operator_settings = QDialog(self)
        settings = setup_pid_dialog(self.operator_settings, 'PID settings', window_controls=False)
        settings_content = QWidget()
        settings_body = QVBoxLayout(settings_content)
        settings_body.addWidget(self.control_panel)
        settings_body.addWidget(self.run_metrics)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(settings_content)
        settings.addWidget(settings_scroll, 1)
        self.operator_settings_close = QPushButton('Done')
        self.operator_settings_close.setMinimumHeight(42)
        self.operator_settings_close.clicked.connect(self.operator_settings.reject)
        settings.addWidget(self.operator_settings_close, 0, Qt.AlignRight)
        self.operator_settings.resize(760, 620)
        self.control_panel.show()
        self.control_panel.findChild(QPushButton, 'pidTunerOpen').hide()
        self.enable_button.hide()
        self.stop_button.hide()
        control = self.page_stack.widget(0)
        layout = control.layout()
        intro = ResponsiveRow()
        title = QLabel('Beam control')
        title.setObjectName('hybridHeading')
        intro.addWidget(title, 1)
        subtitle = QLabel('HYBRID  /  LIVE RESPONSE')
        subtitle.setObjectName('hybridCaption')
        intro.addWidget(subtitle)
        layout.insertLayout(0, intro)
        bar = QFrame()
        bar.setObjectName('hybridDashboardCard')
        row = ResponsiveRow(bar)
        row.setContentsMargins(18, 16, 18, 16)
        for text, widget in (('Trim coil', self.channel_select), ('Beam set (nA)', self.setpoint_input)):
            field = QVBoxLayout()
            field.addWidget(QLabel(text))
            field.addWidget(widget)
            widget.show()
            row.addLayout(field)
        self.operator_start = QPushButton('START')
        self.operator_start.setObjectName('hybridStart')
        self._operator_start_deadline = None
        self._operator_start_timer = QTimer(self)
        self._operator_start_timer.setInterval(100)
        self._operator_start_timer.timeout.connect(self._advance_operator_start)
        self.operator_start.clicked.connect(self._operator_start_pid)
        self.operator_stop = QPushButton('STOP')
        self.operator_stop.setObjectName('hybridStop')
        self.operator_stop.clicked.connect(self._operator_stop)
        self._action_animations = {}
        for button in (self.operator_start, self.operator_stop):
            self._install_action_animation(button)
        for button in (self.operator_start, self.operator_stop):
            button.setMinimumHeight(52)
            row.addWidget(button)
        for text, callback in (('AI tuning', self._show_tuner), ('Settings', self.operator_settings.show)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.insertWidget(1, bar)
        gains = QFrame()
        gains.setObjectName('hybridDashboardCard')
        gain_row = ResponsiveRow(gains)
        gain_row.setContentsMargins(18, 12, 18, 12)
        gain_title = QVBoxLayout()
        gain_title.addWidget(QLabel('Response tuning'))
        hint = QLabel('Adjust gains before starting')
        hint.setObjectName('hybridCaption')
        gain_title.addWidget(hint)
        gain_row.addLayout(gain_title, 1)
        for name, description, widget in (
                ('Kp', 'Proportional', self.kp_input),
                ('Ki', 'Integral', self.ki_input),
                ('Kd', 'Derivative', self.kd_input)):
            field = QVBoxLayout()
            field.addWidget(QLabel(f'{name} · {description}'))
            field.addWidget(widget)
            gain_row.addLayout(field, 1)
            widget.show()
        layout.insertWidget(2, gains)
        readouts = QFrame()
        readouts.setObjectName('hybridDashboardCard')
        readings = ResponsiveRow(readouts)
        self.operator_readouts = {}
        for name in ('Beam actual', 'Beam set', 'TC target', 'TC actual'):
            field = QVBoxLayout()
            caption = QLabel({'Beam actual': 'Measured beam current', 'Beam set': 'Requested beam current',
                             'TC target': 'Commanded TC current', 'TC actual': 'Measured TC current'}[name])
            caption.setWordWrap(True)
            caption.setObjectName('hybridCaption')
            value = QLabel('—')
            value.setObjectName('hybridReadout')
            accent = {'Beam actual': '#52d6b1', 'Beam set': '#65cfff',
                      'TC target': '#c5a0ff', 'TC actual': '#ffbf78'}[name]
            value.setStyleSheet(f'color: {accent};')
            self.operator_readouts[name] = value
            field.addWidget(caption)
            field.addWidget(value)
            readings.addLayout(field, 1)
        layout.insertWidget(3, readouts)
        self.operator_status = QLabel('Choose your beam target, then press START.')
        self.operator_status.setWordWrap(True)
        self.operator_status.setMinimumHeight(50)
        layout.insertWidget(4, self.operator_status)
        self.time_plot.beam.series_labels = ('Beam set', 'Beam actual')
        self.time_plot.coil.series_labels = ('TC target', 'TC actual')
        self.time_plot.beam.setAccessibleName('Beam set versus beam actual')
        self.time_plot.coil.setAccessibleName('TC target versus TC actual')
        for plot in (self.time_plot, self.coil_plot):
            plot.beam.colors = ('#65cfff', '#52d6b1')
            plot.coil.colors = ('#c5a0ff', '#ffbf78')

        # Preserve the complete original configuration in a secondary dialog.
        old = self.tuner_page.takeWidget()
        self.ai_settings = QDialog(self)
        advanced = setup_pid_dialog(self.ai_settings, 'AI tuning settings', window_controls=False)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(old)
        advanced.addWidget(scroll)
        self.ai_settings_close = QPushButton('Done')
        self.ai_settings_close.setMinimumHeight(42)
        self.ai_settings_close.clicked.connect(self.ai_settings.reject)
        advanced.addWidget(self.ai_settings_close, 0, Qt.AlignRight)
        self.ai_settings.resize(1000, 720)
        self.tuner_viewport.hide()
        self.close_tuner_button.hide()
        self.auto_tuning_button.setFixedWidth(160)
        page = QWidget()
        ai = QVBoxLayout(page)
        heading = ResponsiveRow()
        ai_title = QLabel('AI tuning')
        ai_title.setObjectName('hybridHeading')
        heading.addWidget(ai_title, 1)
        for text, callback in (('Tuning settings', self.ai_settings.show), ('Back to control', self._show_pid_control)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            heading.addWidget(button)
        ai.addLayout(heading)
        setup = ResponsiveRow()
        for text, widget in (('Trim coil', self.tuner_channel), ('Beam set', self.tuner_target), ('Trials', self.tuner_trials)):
            field = QVBoxLayout()
            field.addWidget(QLabel(text))
            field.addWidget(widget)
            setup.addLayout(field)
            widget.show()
        self.auto_tuning_button.setText('START TUNING')
        self.auto_tuning_button.setObjectName('hybridStart')
        self.auto_tuning_button.clicked.disconnect()
        self.auto_tuning_button.clicked.connect(self._operator_start_tuning)
        self.stop_tuning_button.setText('STOP')
        self.stop_tuning_button.setObjectName('hybridStop')
        for button in (self.auto_tuning_button, self.stop_tuning_button):
            self._install_action_animation(button)
        setup.addWidget(self.auto_tuning_button)
        setup.addWidget(self.stop_tuning_button)
        ai.addLayout(setup)
        ai.addWidget(self.tuner_status)
        ai.addWidget(self.state_label)
        columns = ResponsiveRow()
        self.search_summaries = {}
        self.search_plots = {}
        for name, description, color in (
            ('GA', 'Explore different gain combinations', '#ffbf78'),
            ('BO', 'Predict and refine the best response', '#65cfff')):
            card = QFrame()
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            card.setObjectName('hybridDashboardCard')
            box = QVBoxLayout(card)
            title = QLabel(name + ' · ' + description)
            title.setStyleSheet(f'color: {color}; font-size: 18px; font-weight: 600;')
            title.setWordWrap(True)
            box.addWidget(title)
            summary = QLabel('Waiting for tuning to start')
            summary.setWordWrap(True)
            self.search_summaries[name] = summary
            box.addWidget(summary)
            plot = HybridCostPlot([], compact=True)
            plot.setMinimumWidth(200)
            self.search_plots[name] = plot
            box.addWidget(plot, 1)
            if name == 'GA':
                button = QPushButton('Exploration settings')
                button.clicked.connect(self.hybrid_settings.show)
            else:
                button = self.gain_model_button
                button.setText('View prediction model')
            box.addWidget(button)
            columns.addWidget(card, 1)
        ai.addLayout(columns, 1)
        actions = ResponsiveRow()
        history = QPushButton('Results and history')
        history.clicked.connect(self._show_hybrid_history)
        actions.addWidget(history)
        actions.addWidget(self.approve_gains_button)
        actions.addWidget(self.apply_tuned_gains_button)
        ai.addLayout(actions)
        self.tuner_page.setWidget(page)
        self.tuner_status.setText('Choose a target and press START TUNING. Review gain limits in Tuning settings.')
        self.state_label.setText('Explore with GA → Refine with BO → Validate the best response')
        self._build_error_sidebar()

    def _install_action_animation(self, button):
        effect = QGraphicsOpacityEffect(button)
        button.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b'opacity', button)
        animation.setDuration(450)
        animation.setStartValue(.35)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        self._action_animations[button] = animation
        button.pressed.connect(lambda b=button: self._animate_action(b))

    def _animate_action(self, button):
        animation = self._action_animations[button]
        animation.stop()
        animation.start()

    def _build_error_sidebar(self):
        self._error_messages = []
        self._seen_error_messages = set()
        self._status_messages = []
        self._activity_snapshot = None
        self._activity_optimizer = None
        self._activity_trial_count = 0
        self._activity_search_state = None
        self.error_sidebar = QFrame()
        self.error_sidebar.setObjectName('hybridDashboardCard')
        self.error_sidebar.setMinimumWidth(270)
        self.error_sidebar.setMaximumWidth(340)
        box = QVBoxLayout(self.error_sidebar)
        title = QLabel('Activity center')
        title.setStyleSheet('font-size: 18px; font-weight: 600; color: #e8eaed;')
        box.addWidget(title)
        self.activity_summary = QLabel('● Ready')
        self.activity_summary.setWordWrap(True)
        self.activity_summary.setStyleSheet('background: #20352f; color: #72e9c7; padding: 10px; border-radius: 8px;')
        box.addWidget(self.activity_summary)
        self.activity_tabs = QTabWidget()
        self.activity_tabs.setStyleSheet('''
            QTabWidget::pane { border: none; background: transparent; }
            QTabBar::tab { background: #202b3a; color: #aebbd0; padding: 10px 12px; border-radius: 6px; }
            QTabBar::tab:selected { background: #344357; color: #ffffff; }
        ''')
        box.addWidget(self.activity_tabs, 1)
        status_page = QWidget()
        status_box = QVBoxLayout(status_page)
        status_box.setContentsMargins(0, 10, 0, 0)
        self.status_activity = QLabel()
        self.status_activity.setTextFormat(Qt.RichText)
        self.status_activity.setWordWrap(True)
        self.status_activity.setAlignment(Qt.AlignTop)
        self.status_activity.setTextInteractionFlags(Qt.TextSelectableByMouse)
        status_scroll = QScrollArea()
        status_scroll.setWidgetResizable(True)
        status_scroll.setWidget(self.status_activity)
        status_scroll.setStyleSheet('QScrollArea { border: none; background: transparent; }')
        status_box.addWidget(status_scroll, 1)
        clear_status = QPushButton('Clear status history')
        clear_status.clicked.connect(self._clear_status_history)
        status_box.addWidget(clear_status)
        self.activity_tabs.addTab(status_page, 'Status')
        error_page = QWidget()
        error_box = QVBoxLayout(error_page)
        error_box.setContentsMargins(0, 10, 0, 0)
        self.error_explanation = QLabel('No errors reported.\n\nSTART requests PID control after a three-second countdown. The running banner confirms a successful start.')
        self.error_explanation.setTextFormat(Qt.RichText)
        self.error_explanation.setWordWrap(True)
        self.error_explanation.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.error_explanation.setAlignment(Qt.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.error_explanation)
        scroll.setStyleSheet('QScrollArea { border: none; background: transparent; }')
        error_box.addWidget(scroll, 1)
        clear = QPushButton('Clear error history')
        clear.clicked.connect(self._clear_error_history)
        error_box.addWidget(clear)
        self.activity_tabs.addTab(error_page, 'Errors · 0')
        self._log_activity('Ready', 'Choose a beam target and gains. START includes a cancellable three-second countdown.', '#65cfff')
        workspace = self.page_stack.parentWidget().layout()
        workspace.removeWidget(self.page_stack)
        row = ResponsiveRow()
        row.addWidget(self.page_stack, 1)
        row.addWidget(self.error_sidebar)
        workspace.addLayout(row, 1)

    @staticmethod
    def _activity_cards(entries):
        cards = []
        for timestamp, title, detail, color in entries:
            cards.append(f'<table width="100%" cellpadding="10" cellspacing="0" bgcolor="#202b3a">'
                         f'<tr><td><span style="color:{color}">● <b>{escape(title)}</b></span><br>'
                         f'<span style="color:#9daec5;font-size:11px">{escape(timestamp)}</span><br><br>'
                         f'{escape(detail).replace(chr(10), "<br>")}</td></tr></table><br>')
        return ''.join(cards)

    def _log_activity(self, title, detail, color='#65cfff'):
        if not hasattr(self, 'status_activity'):
            return
        self._status_messages.insert(0, (time.strftime('%H:%M:%S'), title, detail, color))
        self._status_messages = self._status_messages[:60]
        self.status_activity.setText(self._activity_cards(self._status_messages))

    def _clear_status_history(self):
        self._status_messages.clear()
        self.status_activity.setText('No status events yet. New activity will appear here.')

    def _update_activity_status(self):
        if not hasattr(self, 'activity_summary'):
            return
        pending = self._operator_start_deadline is not None or getattr(self, '_operator_starting', False)
        phase = 'Starting PID' if pending else 'PID running' if self.pid_enabled else 'Validation' if self._validating_gains else 'AI tuning' if self.tuning_session_active else 'PID stopped'
        mode = 'Dry Run' if self.dry_run_check.isChecked() else 'Live'
        snapshot = (phase, self.backend_connection, self.beam_valid, mode)
        previous = self._activity_snapshot
        color = '#ffcf82' if pending else '#72e9c7' if self.pid_enabled or self.tuning_session_active else '#aebbd0'
        self.activity_summary.setText(f'● {phase}\n{mode} · {self.backend_connection}')
        self.activity_summary.setStyleSheet(f'background: #202b3a; color: {color}; padding: 10px; border-radius: 8px;')
        if previous is not None:
            if snapshot[0] != previous[0]:
                self._log_activity(phase, self.last_safety_message if not pending else 'PID start requested. STOP cancels the countdown.', color)
            if snapshot[1] != previous[1]:
                self._log_activity('Connection changed', self.backend_connection)
            if snapshot[2] != previous[2]:
                self._log_activity('Beam feedback', 'Fresh calibrated beam is available.' if self.beam_valid else 'Waiting for fresh calibrated beam feedback.', '#72e9c7' if self.beam_valid else '#ffcf82')
            if snapshot[3] != previous[3]:
                self._log_activity('Mode changed', mode)
        self._activity_snapshot = snapshot
        if self.hybrid is not self._activity_optimizer:
            self._activity_optimizer = self.hybrid
            self._activity_trial_count = 0
            self._activity_search_state = None
        if self.hybrid:
            if self.hybrid.state != self._activity_search_state:
                self._log_activity('Search stage changed', f'{self.hybrid.state}\n{self.hybrid.reason}', '#c5a0ff')
                self._activity_search_state = self.hybrid.state
            records = self.hybrid.records
            for record in records[self._activity_trial_count:]:
                cost = record.get('cost')
                score = display_number(cost) if cost is not None else 'No comparable score'
                self._log_activity(f'Trial {record["trial"]} completed', f'{record["source"]} · Performance score: {score}', '#c5a0ff')
            self._activity_trial_count = len(records)

    def _clear_error_history(self):
        self._error_messages.clear()
        self.error_explanation.setText('No errors reported. New errors will appear here with suggested next steps.')
        self.activity_tabs.setTabText(1, 'Errors · 0')

    def _report_operator_error(self, message):
        if not hasattr(self, 'error_explanation') or message in self._seen_error_messages:
            return
        self._seen_error_messages.add(message)
        lower = message.lower()
        if 'beam' in lower and any(word in lower for word in ('fresh', 'calibrated', 'watchdog', 'measurement')):
            help_text = 'The controller needs a calibrated beam sample less than one second old. Check beam monitoring, calibration and simulator telemetry. Smoke2 supplies a synthetic beam signal, but it does not respond to TC commands.'
        elif 'native simulated' in lower or 'hardware commissioning' in lower:
            help_text = 'Automatic Hybrid search currently supports native simulated transport. Smoke2 uses ZMQ, so this search is blocked. Dry Run can preview candidates, but cannot validate final gains.'
        elif 'interlock' in lower or 'fault' in lower:
            help_text = 'The channel or controller reported a fault. Check the channel status and clear the underlying fault before retrying START.'
        elif 'telemetry' in lower or 'transport' in lower or 'connected' in lower:
            help_text = 'Fresh connected telemetry is required. Check that the simulator is running and its endpoint matches the app connection settings.'
        elif 'another' in lower or 'active controller' in lower or 'owns' in lower:
            help_text = 'Another controller is using this connection. Stop it on its control page before starting this PID.'
        elif 'recovery' in lower or 'baseline' in lower:
            help_text = 'The starting conditions could not be restored or captured. Check TC limits, beam stability and recovery settings before preparing a new session.'
        elif 'enable' in lower or 'output is off' in lower or 'control is disabled' in lower:
            help_text = 'The selected TC could not be enabled. Check the connection, channel status, output limits and whether PID is allowed in this mode.'
        elif 'dry run' in lower:
            help_text = 'Dry Run does not validate a physical beam response. Final validation requires a supported simulation with TC-to-beam coupling.'
        else:
            help_text = 'Review the message and the associated settings. Correct the condition, then retry the action. PID startup is confirmed only by the PID RUNNING banner.'
        self._error_messages.insert(0, (time.strftime('%H:%M:%S'), message, help_text, '#ff879a'))
        self._error_messages = self._error_messages[:30]
        self.error_explanation.setText(self._activity_cards(self._error_messages))
        self.activity_tabs.setTabText(1, f'Errors · {len(self._error_messages)}')
        self.activity_tabs.setCurrentIndex(1)

    def _operator_enable(self, channel):
        if self.pid_enabled or self.tuning_session_active or active_controller(self.backend, self) is not None:
            raise ValueError('Stop the active controller first')
        self._refresh_beam()
        if not self.beam_valid:
            raise ValueError('Waiting for a fresh beam measurement')
        self.arm_button.setChecked(True)
        GABackendAdapter(self.backend).enable_channel(channel,
            (self.min_output_input.value(), self.max_output_input.value()),
            authorized=self.armed and self.tuning_enabled, max_age_s=1)
        # The adapter changes backend commands outside the checkbox path. Keep
        # the desired-state cache aligned so startup does not read stale Off.
        command = self.backend.PendingCommand()[channel]
        self.channel_on[channel] = bool(command['on'])
        self.channel_enabled[channel] = bool(command['enabled'])
        self.command_values[channel] = float(command['target'])
        self._tick_feedback()

    def _operator_start_pid(self):
        if self.pid_enabled or self.tuning_session_active or self._operator_start_deadline is not None:
            return
        self._refresh_beam()
        if not self.beam_valid:
            self.last_safety_message = 'Waiting for a fresh beam measurement'
            self._report_operator_error(self.last_safety_message)
            self._refresh_status()
            return
        self._operator_start_deadline = time.monotonic() + 3
        self._log_activity('Start requested', 'PID will begin in three seconds. Press STOP to cancel.', '#ffcf82')
        self._lock_controller_inputs(True)
        self._operator_start_timer.start()
        self._refresh_status()

    def _advance_operator_start(self):
        if self._operator_start_deadline is None:
            return
        if time.monotonic() < self._operator_start_deadline:
            self._refresh_status()
            return
        self._operator_start_deadline = None
        self._operator_starting = True
        self._operator_start_timer.stop()
        self._lock_controller_inputs(False)
        try:
            self._operator_enable(self.selected_index)
            self._set_pid_enabled(True)
        except Exception as exc:
            self.last_safety_message = str(exc)
        self._operator_starting = False
        if self.pid_enabled:
            self._animate_action(self.operator_start)
        else:
            self._report_operator_error(self.last_safety_message)
        self._refresh_status()

    def _operator_start_tuning(self):
        if self._operator_start_deadline is not None:
            self.tuner_status.setText('PID start is pending. Press STOP on Beam control to cancel it first.')
            return
        try:
            self._operator_enable(self.tuner_channel.currentIndex())
            self._start_auto_tuning()
        except Exception as exc:
            self.tuner_status.setText(str(exc))
            self._report_operator_error(str(exc))

    def _operator_stop(self):
        self._log_activity('Stop requested', 'Cancel pending startup and stop the active controller.', '#ff879a')
        self._cancel_operator_start()
        if self.tuning_session_active:
            self._stop_tuning_session()
        self._stop_pid('Stopped by operator')

    def _stop_pid(self, reason):
        self._cancel_operator_start()
        super()._stop_pid(reason)
        routine = {'Operator stop', 'Stopped by operator', 'Controller changed',
                   'Channel changed', 'Disarmed', 'Zero command', 'Page closed',
                   'Preparing hybrid baseline', 'Starting hybrid session', 'Starting tuning session'}
        if reason not in routine:
            self._report_operator_error(reason)

    def _cancel_operator_start(self):
        if getattr(self, '_operator_start_deadline', None) is not None:
            self._operator_start_deadline = None
            self._operator_start_timer.stop()
            self._lock_controller_inputs(False)

    def _refresh_status(self):
        super()._refresh_status()
        if not hasattr(self, 'operator_status'):
            return
        pending = self._operator_start_deadline is not None
        self.operator_start.setEnabled(not self.pid_enabled and not self.tuning_session_active and not pending)
        if pending:
            seconds = max(1, math.ceil(self._operator_start_deadline-time.monotonic()))
            self.operator_start.setText(f'STARTING IN {seconds}')
            message = f'START REQUESTED · PID begins in {seconds}s · Press STOP to cancel'
            color, background = '#ffcf82', '#382e20'
            self.operator_stop.setText('CANCEL START')
        elif self.pid_enabled:
            self.operator_start.setText('PID RUNNING')
            self.operator_stop.setText('STOP PID')
            mode = 'DRY RUN' if self.dry_run_check.isChecked() else 'LIVE'
            message = f'● PID RUNNING · {mode} · Beam set {display_number(self.setpoint_input.value())} nA'
            color, background = '#72e9c7', '#183b35'
        else:
            self.operator_start.setText('START PID')
            self.operator_stop.setText('STOP')
            message = '● PID STOPPED · ' + self.last_safety_message
            color, background = '#c6d1e0', '#202b3a'
        self.operator_status.setText(message)
        self.operator_status.setStyleSheet(f'color: {color}; background: {background}; border-radius: 10px; padding: 12px 16px; font-size: 15px; font-weight: 600;')
        self._update_activity_status()
        for text in (self.last_safety_message, self.tuner_status.text(), self.state_label.text()):
            lower = text.lower()
            if any(term in lower for term in ('failed', 'fault', 'error:', 'rejected', 'watchdog',
                                              'not started:', 'not connected', 'not started.',
                                              'validation not started', 'timed out', 'drift detected')):
                self._report_operator_error(text)
        values = {'Beam actual': (self._feedback_value(), 'nA'),
                  'Beam set': (self.setpoint_input.value(), 'nA'),
                  'TC target': (self.command_values[self.selected_index], 'A'),
                  'TC actual': (self.actual_values[self.selected_index], 'A')}
        for name, (value, unit) in values.items():
            self.operator_readouts[name].setText(f'{display_number(value)} {unit}' if math.isfinite(value) else 'Unavailable')
            self.operator_readouts[name].setToolTip(f'Values smaller than 0.000001 {unit} are shown as ≈ 0. Display rounding does not change telemetry or PID calculations.')
        if self.hybrid:
            generation, population, index, total = self.hybrid.ga.progress()
            self.search_summaries['GA'].setText(f'Generation {generation} · Candidate {index} of {total}\nExplores the allowed gain range using measured results.')
            prediction = self.hybrid.prediction
            self.search_summaries['BO'].setText(
                f'Predicted performance score: {display_number(prediction[0])}\nPrediction uncertainty: ± {display_number(prediction[1])}\nMeasured confirmation is required before taking over.'
                if prediction else 'Learning from measured trials.\nA proposal appears once enough diverse results are available.')
            for name, plot in self.search_plots.items():
                sources = ('GA', 'Exploration') if name == 'GA' else ('BO', 'Confirm')
                plot.records = [r for r in self.hybrid.records if r['source'].startswith(sources)]
                plot.update()

    def _show_tuner(self):
        super()._show_tuner()
        self.tuner_engine_label.setText('Hybrid GA + BO — C++ beam PID')

    def _enable_selected_tc(self):
        if self.tuning_session_active or self.pid_enabled or active_controller(self.backend,self) is not None:
            self.tuner_status.setText('Stop controllers before enabling a TC')
            return
        try:
            GABackendAdapter(self.backend).enable_channel(self.tuner_channel.currentIndex(),
                (self.min_output_input.value(),self.max_output_input.value()),
                authorized=self.armed and self.tuning_enabled,max_age_s=1)
            self.tuner_status.setText('Selected TC enabled; its command target was preserved.')
        except Exception as exc:
            self.tuner_status.setText(f'TC enable failed: {exc}')

    def _field_values(self):
        return {k:w.value() for k,w in self.hybrid_fields.items()}

    def _fingerprint(self):
        beam = self.get_beam_state() if self.get_beam_state else {}
        return (self.tuner_channel.currentIndex(),self.tuner_target.value(),self.tuner_duration.value(),
                self.tuner_profile.currentText(),self.min_output_input.value(),self.max_output_input.value(),
                self.max_step_input.value(),tuple(sorted(self._controller_config().items())),
                self.dry_run_check.isChecked(),tuple(sorted(self._field_values().items())),
                tuple((a.value(),b.value()) for a,b in self.tuner_gain_bounds.values()),
                beam.get('range_index'),beam.get('calibration_revision'),beam.get('select_mode'))

    def _lock_controller_inputs(self, locked):
        super()._lock_controller_inputs(locked)
        for widget in getattr(self,'hybrid_fields',{}).values():
            widget.setEnabled(not locked)
        if hasattr(self,'tuner_profile'):
            self.tuner_profile.setEnabled(not locked)

    def _set_auto_tuning(self, enabled):
        super()._set_auto_tuning(enabled)
        if self.tuning_session_active:
            self._lock_controller_inputs(True)

    def _prepare_tuning_session(self):
        if self.tuning_session_active:
            return
        try:
            if active_controller(self.backend,self) is not None:
                raise ValueError('Another PID/GA/BO page owns this backend')
            if not self.armed or not self.tuning_enabled:
                raise ValueError('Arm PID in simulation before preparing a hybrid session')
            if self.pid_enabled:
                self._stop_pid('Preparing hybrid baseline')
            self._refresh_beam()
            if not self.beam_valid:
                raise ValueError('Fresh calibrated beam feedback is required')
            self._settings = self._field_values()
            config = HybridConfig(**{k:self._settings[k] for k in HybridConfig.__dataclass_fields__ if k != 'budget'}, budget=self.tuner_trials.value())
            bounds = [(a.value(),b.value()) for a,b in self.tuner_gain_bounds.values()]
            if self.tuner_duration.value() < self._settings['warmup']+1:
                raise ValueError('Trial duration must exceed warmup by at least one second')
            error = abs(self.tuner_target.value()-self.beam_value)
            if error <= self.nla_deadband_input.value() or error > self._settings['max_error']:
                raise ValueError('Initial beam error must exceed PID deadband and stay within the beam abort limit')
            snapshot = self.backend.LatestSnapshot()
            if not snapshot.get('simulated',False) and not self.dry_run_check.isChecked():
                raise ValueError('Live hybrid trials require native simulated transport; hardware commissioning is not enabled')
            self._channel = self.tuner_channel.currentIndex()
            commands = self.backend.PendingCommand()
            ch = snapshot['channels'][self._channel]
            if not ch['on'] or not ch['enabled']:
                raise ValueError('Enable the selected TC before capturing its baseline')
            self._limits = (self.min_output_input.value(),self.max_output_input.value())
            baseline = float(commands[self._channel]['target'])
            if not self._limits[0] < self._limits[1] or not self._limits[0] <= baseline <= self._limits[1]:
                raise ValueError('Baseline TC command must lie within ordered output limits')
            step = min(self._settings['recovery_step'],self.max_step_input.value())
            if self._settings['excursion']/step*.125+self._settings['recovery_hold'] >= self._settings['recovery_timeout']:
                raise ValueError('Recovery timeout is too short for the excursion, step and stable hold')
            # A rejected new setup must never overwrite the previous session's export.
            self._session_path = None
            self.apply_tuned_gains_button.setEnabled(False)
            self.apply_tuned_gains_button.setProperty('approvedCandidate',None)
            self.hybrid = HybridPIDOptimizer(bounds,PidGainCandidate(self.kp_input.value(),self.ki_input.value(),self.kd_input.value()),config)
            self.reference = GARecoveryManager.capture(targets_a=[c['target'] for c in commands],
                actual_values_a=[c['actual'] for c in snapshot['channels']],beam_nA=self.beam_value,
                channel_indices=[self._channel],timestamp_s=time.monotonic())
            self._recovery_config = GARecoveryConfig(command_step_a=step,
                actual_tolerance_a=self._settings['actual_tolerance'],minimum_beam_nA=0,
                minimum_beam_fraction=0,beam_reference_tolerance_nA=self._settings['beam_tolerance'],
                stable_hold_s=self._settings['recovery_hold'],timeout_s=self._settings['recovery_timeout'])
            self._recovery_config.validated()
            self._session_fingerprint = self._fingerprint()
            beam_state = self.get_beam_state()
            self._beam_identity = {k:beam_state.get(k) for k in ('range_index','range_label','calibration_revision','select_mode')}
            self.adapter = GABackendAdapter(self.backend)
            self._check_hybrid_telemetry()
        except Exception as exc:
            self.tuner_status.setText(f'Hybrid not started: {exc}')
            return
        self._stop_pid('Starting hybrid session')
        self._tuning_controller_config = self._controller_config()
        self._tuning_quality_settings = self.tuning_quality_dialog.snapshot()
        self._session_metadata = dict(target_nA=self.tuner_target.value(),channel=self._channel,
            profile=self.tuner_profile.currentText(),dry_run=self.dry_run_check.isChecked(),
            feedback_units='nA',actuator_units='A',beam_calibration=dict(self._beam_identity),
            controller=dict(self._tuning_controller_config),reference=asdict(self.reference))
        self.tuning_optimizer = self.hybrid
        self.tuning_results = []
        self.tuning_samples = []
        self.tuning_candidate = self.tuning_trial_candidate = None
        self.coil_session_samples = []
        self.coil_session_started = time.perf_counter()
        self.coil_session_stamp = None
        self.coil_plot.trial_markers = []
        self.coil_plot.set_samples([],self.tuner_target.value())
        self.tuning_session_active = True
        self._lock_controller_inputs(True)
        self._session_path = Path(__file__).resolve().parents[3]/'Exports'/'Hybrid'/uuid4().hex
        self._validation_result = None
        self.prepare_tuning_button.setEnabled(False)
        self.auto_tuning_button.setEnabled(False)
        self.apply_tuned_gains_button.setEnabled(False)
        self.apply_tuned_gains_button.setProperty('approvedCandidate',None)
        self.approve_gains_button.setEnabled(False)
        self.review_history_button.setEnabled(False)
        self.stop_tuning_button.setEnabled(True)
        self.restore_button.setEnabled(True)
        self._begin_recovery('next')

    def _check_hybrid_telemetry(self):
        self._refresh_beam(publish=True)
        if self._session_fingerprint != self._fingerprint():
            raise ValueError('Trial settings or beam calibration changed; start a new session')
        if not self.armed or not self.beam_valid:
            raise ValueError('Arming or calibrated beam watchdog failed')
        snapshot = self.backend.LatestSnapshot()
        age = time.time()-float(snapshot['timestamp'])
        ch = snapshot['channels'][self._channel]
        if not 0 <= age <= 1 or str(self.backend.Health()['connection']).lower() != 'connected':
            raise ValueError('Transport watchdog failed')
        if ch.get('interlocked') or ch.get('status') in ('Fault','Interlocked') or not ch['on'] or not ch['enabled']:
            raise ValueError('TC fault, interlock or disabled output')
        if not math.isfinite(float(ch['actual'])):
            raise ValueError('Invalid TC feedback')
        if self.reference and abs(float(ch['actual'])-self.reference.actual_map[self._channel]) > self._settings['excursion']+self._settings['actual_tolerance']:
            raise ValueError('Measured TC excursion exceeded the baseline limit')
        return snapshot

    def _request_tuning_candidate(self):
        if not self.tuning_session_active:
            return
        if len(self.hybrid.results) >= self.hybrid.config.budget:
            self._finish_tuning_session()
            return
        self.tuning_candidate = None
        self.run_tuning_trial_button.setEnabled(False)
        self.tuner_status.setText('Preparing hybrid candidate; baseline held.')
        self.tuning_proposal = self.tuning_executor.submit(self.hybrid.propose_batch,1)

    def _start_trial(self, config):
        if getattr(self,'_continuous_start',False):
            return super()._start_trial(config)
        self._check_hybrid_telemetry()
        base = self.reference.target_map[self._channel]
        excursion = self._settings['excursion']
        config['minimum_command'][self._channel] = max(self._limits[0],base-excursion)
        config['maximum_command'][self._channel] = min(self._limits[1],base+excursion)
        config['max_absolute_error'] = config['max_overshoot'] = self._settings['max_error']
        config['max_saturation_seconds'] = self._settings['saturation']
        super()._start_trial(config)

    def _start_service_nla(self):
        # Normal PID retains the parent page's independent continuous-control path.
        # Its virtual dispatch must not require a hybrid recovery reference.
        self._continuous_start = True
        try:
            super()._start_service_nla()
        finally:
            self._continuous_start = False

    def _poll_tuning_workflow(self):
        if not self.tuning_session_active:
            super()._poll_tuning_workflow()
            return
        try:
            self._check_hybrid_telemetry()
            if self.recovering:
                self._poll_recovery()
            else:
                super()._poll_tuning_workflow()
            if not self.tuning_session_active:
                return
            state = 'Recovery' if self.recovering else 'Validation' if self._validating_gains else self.hybrid.state
            friendly = {'Baseline': 'Measuring starting response', 'GA': 'Exploring gains',
                        'BO challenger': 'Testing a BO suggestion', 'Confirmation': 'Confirming improvement',
                        'BO': 'Refining gains', 'Recovery': 'Returning to starting conditions',
                        'Validation': 'Validating the best response'}
            self.state_label.setText(f'{friendly.get(str(state), str(state))} · Trial {len(self.hybrid.results)}/{self.hybrid.config.budget}')
        except Exception as exc:
            self.hybrid._transition('Stopped',f'Experiment stopped: {exc}')
            self._stop_tuning_session()
            self.tuner_status.setText(f'Hybrid stopped: {exc}')

    def _complete_tuning_trial(self, safe):
        candidate = self.tuning_trial_candidate
        if candidate is None:
            return
        trial_message = self._trial_status().get('message','')
        self._stop_trial(False)
        self._tuning_output_held = True
        metrics = None
        duration = max(60,self.tuner_duration.value()) if self._validating_gains else self.tuner_duration.value()
        warmup = self._settings['warmup']
        samples = [r for r in self.tuning_samples if r[0] >= warmup]
        complete = bool(samples and samples[-1][0] >= duration-.5 and len(samples) >= 3)
        safe = safe and complete and not self._oscillation_stopped
        try:
            metrics = evaluate_trial(samples,self.tuner_target.value(),deadband=self._tuning_controller_config['nla_deadband'],
                                     quality=self._tuning_quality_settings)
            score = trial_cost(metrics,self.tuner_profile.currentText())
        except ValueError:
            safe,score = False,1e12
        if self._validating_gains:
            self._validation_result = (candidate,metrics,safe)
            self.tuning_trial_candidate = None
            if safe:
                self._begin_recovery('validation')
            else:
                super()._finish_gain_validation(candidate,metrics,False)
                self._save_session()
            return
        result = PidTrialResult(candidate,score if safe else 1e12,metrics.settling_time if metrics else 0,
            metrics.overshoot if metrics else 0,metrics.steady_state_error if metrics else 0,
            metrics.control_effort if metrics else 0,safe,metrics=metrics,
            termination_reason='Completed' if safe else f'Fault, oscillation or incomplete trial: {trial_message}')
        self.hybrid.record_results([result])
        self.tuning_results.append(result)
        self.tuning_trial_candidate = None
        self.review_history_button.setEnabled(True)
        self._save_session(samples)
        if self.hybrid.reference_drift_detected:
            reason = self.hybrid.reason
            self._stop_tuning_session()
            self.tuner_status.setText(reason)
            self.apply_tuned_gains_button.setEnabled(False)
            self.approve_gains_button.setEnabled(False)
            return
        if not safe:
            self._stop_tuning_session()
            self.tuner_status.setText('Hybrid stopped: failed trials are excluded from performance training.')
            return
        self._begin_recovery('next')

    def _begin_recovery(self, action):
        self.recovery.start(reference=self.reference,config=self._recovery_config,timestamp_s=time.monotonic())
        self._last_recovery_sample = None
        self.recovering = True
        self._recovery_action = action
        self.run_tuning_trial_button.setEnabled(False)
        self.tuner_status.setText('Restoring baseline TC command and waiting for beam/TC stability.')

    def _poll_recovery(self):
        snapshot = self._check_hybrid_telemetry()
        now = time.monotonic()
        if now-self.recovery.start_time >= self._recovery_config.timeout_s:
            raise ValueError('Recovery timed out; no next trial was started')
        stamp = (float(snapshot['timestamp']),self.beam_timestamp)
        if self._last_recovery_sample and (stamp[0] <= self._last_recovery_sample[0] or stamp[1] <= self._last_recovery_sample[1]):
            return
        self._last_recovery_sample = stamp
        targets = [c['target'] for c in self.backend.PendingCommand()]
        proposal = self.recovery.next_command(targets)
        if proposal and not self.dry_run_check.isChecked():
            if not self.adapter.apply_delta(proposal.channel_index,proposal.delta_a,self._limits,authorized=self.armed,max_age_s=1):
                raise ValueError('Recovery command rejected')
            targets = [c['target'] for c in self.backend.PendingCommand()]
        state = self.recovery.observe(timestamp_s=now,current_targets_a=targets,
            actual_values_a=[c['actual'] for c in snapshot['channels']],beam_nA=self.beam_value)
        if not state.complete:
            self.tuner_status.setText(f'Recovery · {state.elapsed_s:.1f}s · {state.status}')
            return
        self.recovering = False
        action = self._recovery_action
        self._recovery_action = None
        if action == 'next':
            self._request_tuning_candidate()
        elif action == 'start_validation':
            super()._run_tuning_trial()
        elif action == 'validation':
            super()._finish_gain_validation(*self._validation_result)
            self.state_label.setText('Validation passed · applying gains leaves PID stopped.' if self.apply_tuned_gains_button.isEnabled()
                                    else 'Validation failed · gains cannot be applied.')
            self._log_activity('Validation complete', self.state_label.text(), '#72e9c7' if self.apply_tuned_gains_button.isEnabled() else '#ff879a')
            self._save_session()
        else:
            self._stop_tuning_session()
            self.tuner_status.setText('Baseline restored; output disabled.')

    def _validate_best_gains(self):
        if self.tuning_session_active or self.hybrid is None or self.hybrid.best_result is None:
            return
        if active_controller(self.backend,self) is not None:
            self.tuner_status.setText('Another controller owns this backend')
            return
        try:
            if self.dry_run_check.isChecked():
                raise ValueError('Dry run cannot validate beam response; run a new coupled simulation session with Dry Run off')
            self._check_hybrid_telemetry()
        except Exception as exc:
            self.tuner_status.setText(f'Validation not started: {exc}. Enable the TC and retain the session settings.')
            return
        self._validating_gains = True
        self._validation_result = None
        self.tuning_session_active = True
        self.tuning_candidate = self.hybrid.best_result.candidate
        self._lock_controller_inputs(True)
        self._set_auto_tuning(False)
        self.apply_tuned_gains_button.setEnabled(False)
        self.apply_tuned_gains_button.setProperty('approvedCandidate',None)
        self.stop_tuning_button.setEnabled(True)
        self._begin_recovery('start_validation')

    def _abort_restore(self):
        if not self.tuning_session_active or self.reference is None:
            return
        if self.tuning_proposal:
            self.tuning_proposal.cancel()
            self.tuning_proposal = None
        self._record_abort('Operator abort and restore')
        self._stop_trial(False)
        self._tuning_output_held = True
        self.tuning_trial_candidate = None
        self.tuning_candidate = None
        self._validating_gains = False
        self._begin_recovery('stop')

    def _finish_tuning_session(self):
        super()._finish_tuning_session()
        self._log_activity('Search complete', 'Validate the best gains before applying them to PID.', '#72e9c7')
        self.restore_button.setEnabled(False)
        self.state_label.setText('Search complete · Validate best gains before applying')
        self._save_session()

    def _record_abort(self, reason):
        if self._validating_gains and self.tuning_trial_candidate is not None:
            self._validation_result = (self.tuning_trial_candidate,None,False)
            self._save_session()
        if not self._validating_gains and self.hybrid and self.tuning_trial_candidate is not None and self.hybrid.pending == self.tuning_trial_candidate:
            candidate = self.tuning_trial_candidate
            result = PidTrialResult(candidate,1e12,0,0,0,0,False,termination_reason=reason)
            self.hybrid.record_results([result])
            self.tuning_results.append(result)
            self._save_session(self.tuning_samples)

    def _stop_tuning_session(self):
        owned = self.tuning_session_active
        if owned:
            self._record_abort('Aborted by operator or watchdog')
        if owned and self.backend is not None and hasattr(self,'_channel'):
            # This also covers stopping during initial recovery, before the
            # native trial worker has acquired any allocation.
            try:
                self._stop_trial(False)
                if not self.dry_run_check.isChecked():
                    previous = self.backend.PendingCommand()[self._channel]
                    self.backend.SetChannelCommand(self._channel,previous['target'],False,False)
                    if not self.backend.ApplyCommand():
                        self.last_safety_message = 'Stop command rejected'
            except Exception as exc:
                self.last_safety_message = f'Stop failed: {exc}'
            self.tuning_trial_candidate = None
            self._tuning_output_held = False
        self.recovering = False
        self._recovery_action = None
        super()._stop_tuning_session()
        if hasattr(self,'restore_button'):
            self.restore_button.setEnabled(False)
        if self.hybrid:
            if not self.hybrid.reference_drift_detected:
                self.hybrid.reason = 'Session stopped; restart creates a new comparison history.'
            self.state_label.setText('Stopped · no further trials will run. '+self.last_safety_message)
            self._save_session()

    def _save_session(self,samples=None):
        if self._session_path is None or self.hybrid is None:
            return
        try:
            payload = dict(self._session_metadata,config=asdict(self.hybrid.config),trial_settings=self._settings,
                records=self.hybrid.records,events=self.hybrid.events,
                feasibility_observations=self.hybrid.feasibility_observations,
                validation_passed=self.apply_tuned_gains_button.isEnabled(),
                validation_candidate=asdict(self._validation_result[0]) if self._validation_result else None,
                validation_metrics=asdict(self._validation_result[1]) if self._validation_result and self._validation_result[1] else None)
            file_writer.submit(write_text, self._session_path/'session.json', json.dumps(payload,indent=2,allow_nan=False))
            header = ('seconds','beam_nA','error_nA','control_rate_A_s','TC_command_A','saturated')
            if samples is not None:
                file_writer.submit(write_csv, self._session_path/f'trial-{len(self.hybrid.records):03d}.csv',
                                   tuple(tuple(r) for r in samples), header)
            if self._validation_result:
                file_writer.submit(write_csv, self._session_path/'validation.csv',
                                   tuple(tuple(r) for r in self.tuning_samples), header)
        except (OSError,ValueError) as exc:
            self.state_label.setText(f'Export failed: {exc}')

    def _show_hybrid_history(self):
        records = list(self.hybrid.records) if self.hybrid else []
        dialog = QDialog(self)
        layout = setup_pid_dialog(dialog,'Hybrid measured history',window_controls=False)
        tabs = QTabWidget()
        tabs.addTab(HybridCostPlot(records),'Measured costs / predictions')
        keys = ['trial','source','state','kp','ki','kd','cost','beam_mae_nA','steady_error_nA','safe','valid_response','settled','prediction','prediction_std','beam_error_gate','reference_check','confirmation_order','reason']
        table = QTableWidget(len(records),len(keys))
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setHorizontalHeaderLabels(keys)
        for i,r in enumerate(records):
            for j,k in enumerate(keys):
                value = r.get(k)
                text = '—' if value is None else display_number(value) if isinstance(value, float) else str(value)
                table.setItem(i,j,QTableWidgetItem(text))
        table.resizeColumnsToContents()
        tabs.addTab(table,'Trials')
        decisions = QLabel('\n\n'.join(f"After trial {e['after_trial']} · {e['state']}\n{e['reason']}" for e in self.hybrid.events) if self.hybrid else 'No decisions yet')
        decisions.setWordWrap(True)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(decisions)
        tabs.addTab(scroll,'Handover decisions')
        layout.addWidget(tabs)
        export = QPushButton('Export shared history CSV')
        def save():
            path,_=QFileDialog.getSaveFileName(dialog,'Export shared history','hybrid-history.csv','CSV (*.csv)')
            if path:
                try:
                    with open(path,'w',newline='',encoding='utf-8') as f:
                        w=csv.DictWriter(f,fieldnames=keys)
                        w.writeheader()
                        w.writerows(records)
                except OSError as exc:
                    export.setText(f'Export failed: {exc}')
        export.clicked.connect(save)
        layout.addWidget(export)
        close = QPushButton('Close history')
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.resize(1050,600)
        dialog.exec()

    def stop_backend(self):
        self._cancel_operator_start()
        for name in ('operator_settings', 'ai_settings'):
            if hasattr(self, name):
                getattr(self, name).close()
        if hasattr(self,'hybrid_settings'):
            self.hybrid_settings.close()
        super().stop_backend()

    def _show_gain_model(self):
        self._request_surrogate_grid()
        super()._show_gain_model()

    def _apply_tuned_gains(self):
        super()._apply_tuned_gains()
        self.run_metrics.method.setCurrentText('Hybrid GA + BO')
