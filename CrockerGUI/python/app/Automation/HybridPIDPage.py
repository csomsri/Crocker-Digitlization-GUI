"""Hybrid search workspace; C++ owns PID trials, Python owns search/recovery sequencing."""
import csv
from source.Python.Data.file_writer import file_writer, write_csv, write_text
import json
import math
import time
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QSpinBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
    QWidget, QScrollArea, QFileDialog, QAbstractItemView)
from python.app.Automation.PidControlPage import PidControlPage
from python.app.Automation.ControlOwnership import active_controller
from python.app.widgets.PidDialog import setup_pid_dialog
from source.Python.Optimization.hybrid_pid_optimizer import HybridPIDOptimizer, HybridConfig
from source.Python.Optimization.pid_gain_adapter import PidGainCandidate, PidTrialResult
from source.Python.Optimization.trial_metrics import evaluate_trial, trial_cost
from source.Python.Automation.ga_recovery import GARecoveryManager, GARecoveryConfig
from source.Python.Automation.ga_backend_adapter import GABackendAdapter


class HybridCostPlot(QWidget):
    """Measured costs are colored by origin; model predictions have separate error bars."""
    def __init__(self, records, parent=None):
        super().__init__(parent)
        self.records = records
        self.setMinimumSize(500, 230)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor('#101a29'))
        colors = {'Baseline':'#a5b4fc','GA':'#fb923c','BO':'#38bdf8','Confirm':'#4ade80'}
        p.setPen(QColor('#dce7f5'))
        p.drawText(16,24,'Measured cost: baseline (purple), GA (orange), BO (blue), confirmation (green)')
        p.drawText(16,44,'Prediction: hollow gray point ±1 model standard deviation. Failed trials have no comparable cost.')
        rows = [r for r in self.records if r['cost'] is not None]
        values = [r['cost'] for r in rows]
        values += [max(0,r['prediction']+r['prediction_std']) for r in rows if r['prediction'] is not None]
        high = max(values,default=1)*1.1 or 1
        rect = QRectF(70,64,self.width()-90,self.height()-105)
        n = max(1,len(self.records))
        def point(i,v):
            return QPointF(rect.left()+(i-1)*rect.width()/max(1,n-1),rect.bottom()-max(0,v)/high*rect.height())
        for i in range(5):
            y = rect.bottom()-rect.height()*i/4
            p.setPen(QColor('#29394e'))
            p.drawLine(QPointF(rect.left(),y),QPointF(rect.right(),y))
            p.setPen(QColor('#cbd5e1'))
            p.drawText(QRectF(0,y-9,64,18),Qt.AlignRight,f'{high*i/4:.3g}')
        p.drawText(70,self.height()-15,f'Trial 1 → {n}     Lower cost is better')
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
        self.phase_label = QLabel('Baseline → GA → BO challenger → Confirmation → BO → Validation')
        self.phase_label.setStyleSheet('color: #dce7f5; padding: 4px;')
        self.phase_label.setWordWrap(True)
        row.addWidget(self.phase_label,1)
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
        if not self.armed or not self.beam_valid:
            raise ValueError('Arming or calibrated beam watchdog failed')
        if self._session_fingerprint != self._fingerprint():
            raise ValueError('Trial settings or beam calibration changed; start a new session')
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
            phase = 'Recovery' if self.recovering else 'Validation' if self._validating_gains else self.hybrid.phase
            g,pop,index,total = self.hybrid.ga.progress()
            prediction = ''
            if self.hybrid.prediction and (self.tuning_trial_candidate or self.tuning_candidate):
                mu,sigma = self.hybrid.prediction
                prediction = f' · BO prediction {mu:.4g} ± {sigma:.3g}'
            self.phase_label.setText(f'{phase} · Trial {len(self.hybrid.results)}/{self.hybrid.config.budget} · GA generation {g}, candidate {index}/{total}{prediction}\n{self.hybrid.reason}')
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
            metrics = evaluate_trial(samples,self.tuner_target.value(),deadband=self._tuning_controller_config['nla_deadband'])
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
            self.phase_label.setText('Validation passed · applying gains leaves PID stopped.' if self.apply_tuned_gains_button.isEnabled()
                                    else 'Validation failed · gains cannot be applied.')
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
        self.restore_button.setEnabled(False)
        self.phase_label.setText('Search complete · Validate best gains before applying')
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
            self.hybrid.reason = 'Session stopped; restart creates a new comparison history.'
            self.phase_label.setText('Stopped · no further trials will run. '+self.last_safety_message)
            self._save_session()

    def _save_session(self,samples=None):
        if self._session_path is None or self.hybrid is None:
            return
        try:
            payload = dict(self._session_metadata,config=asdict(self.hybrid.config),trial_settings=self._settings,
                records=self.hybrid.records,events=self.hybrid.events,
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
            self.phase_label.setText(f'Export failed: {exc}')

    def _show_hybrid_history(self):
        records = list(self.hybrid.records) if self.hybrid else []
        dialog = QDialog(self)
        layout = setup_pid_dialog(dialog,'Hybrid measured history',window_controls=False)
        tabs = QTabWidget()
        tabs.addTab(HybridCostPlot(records),'Measured costs / predictions')
        keys = ['trial','source','phase','kp','ki','kd','cost','beam_mae_nA','steady_error_nA','safe','settled','prediction','prediction_std','beam_error_gate','reason']
        table = QTableWidget(len(records),len(keys))
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setHorizontalHeaderLabels(keys)
        for i,r in enumerate(records):
            for j,k in enumerate(keys):
                table.setItem(i,j,QTableWidgetItem('—' if r[k] is None else str(r[k])))
        table.resizeColumnsToContents()
        tabs.addTab(table,'Trials')
        decisions = QLabel('\n\n'.join(f"After trial {e['after_trial']} · {e['phase']}\n{e['reason']}" for e in self.hybrid.events) if self.hybrid else 'No decisions yet')
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
        if hasattr(self,'hybrid_settings'):
            self.hybrid_settings.close()
        super().stop_backend()

    def _show_gain_model(self):
        self._request_surrogate_grid()
        super()._show_gain_model()

    def _apply_tuned_gains(self):
        super()._apply_tuned_gains()
        self.run_metrics.method.setCurrentText('Hybrid GA + BO')
