"""Matching GA workspaces using the existing C++ or Python NLAPID engines."""
from PySide6.QtCore import QTimer
from python.app.PageShell import DetailPage
from python.app.Automation.GA.ControllerContext import ControllerContext
from python.app.Automation.GA.PIDGAControlTab import PIDGAControlTab
from python.app.Automation.ControlOwnership import active_controller
from python.app.Automation.PIDRecording import recording
from source.Python.Control.NLAPID import NLAPID
from source.Python.Control.CppPIDAdapter import CppPIDAdapter
from source.Python.Automation.ga_backend_adapter import GABackendAdapter


class _Workspace(PIDGAControlTab):
    def __init__(self, page, engine):
        self.page = page
        super().__init__(page.context, page.apply_delta, pid_engine=engine)

    def start_pid(self):
        if self.page.engine_error:
            self.pid_status_label.setText(self.page.engine_error)
            return
        if active_controller(self.page.backend,self.page) is not None:
            self.pid_status_label.setText('Another PID/GA/BO page is using this backend')
            return
        super().start_pid()
        if self._pid_running:
            recording(self.page, 'started', config=dict(measurement_channel=self._pid_channel,
                setpoint=self.setpoint_spin.value(), kp=self.kp_spin.value(), ki=self.ki_spin.value(),
                kd=self.kd_spin.value(), hardware_armed=self.arm_output_check.isChecked(),
                dry_run=not self.arm_output_check.isChecked()))

    def stop_pid(self, *, reason='PID STOPPED', restore_manual=True):
        super().stop_pid(reason=reason, restore_manual=restore_manual)
        recording(self.page, reason=reason)

    def _start_automatic_candidate(self, candidate):
        try:
            recording(self.page, 'check_trial')
        except RuntimeError as exc:
            self._abort_automatic_ga(str(exc), attempt_restore=True)
            return
        super()._start_automatic_candidate(candidate)

    def _log_pid_sample(self, **sample):
        super()._log_pid_sample(**sample)
        r = sample['result']
        gains = sample['gains']
        recording(self.page, 'configure', config=dict(setpoint=self.setpoint_spin.value(),
            kp=gains.kp, ki=gains.ki, kd=gains.kd, hardware_armed=self.arm_output_check.isChecked(),
            dry_run=not self.arm_output_check.isChecked()))
        recording(self.page, sample=dict(feedback=sample['snapshot']['value_nA'],
            beam_na=sample['snapshot']['value_nA'], error=r.error, controller_output=r.output,
            tc_actual_a=sample['measured_tc'], tc_command_a=sample['applied_target'],
            beam_timestamp=sample['sample_timestamp']+self.context._epoch,
            sample_kind='controller_update', status=sample['status_text']))

    def _log_ga_result(self, result):
        recording(self.page, 'trial', result=result)
        super()._log_ga_result(result)

    def _finalize_automatic_ga(self, success, reason):
        super()._finalize_automatic_ga(success, reason)
        recording(self.page, reason=reason)

    def _refresh_live_readouts(self):
        super()._refresh_live_readouts()
        recorder = getattr(self.page, '_database_recorder', None)
        if recorder is not None and hasattr(self, 'pid_sqlite_status_display'):
            status = recorder.database.writer.status()
            self.pid_sqlite_status_display.setText('ERROR' if status['error'] or status['rejected']
                else 'RECORDING' if recorder.session else 'READY')
            self.pid_sqlite_status_display.setToolTip(str(recorder.database.writer.path)
                +f"\nQueued: {status['queue_depth']}; lost: {status['rejected']}\n{status['error']}")

    def start_ga(self):
        if self.page.engine_kind == 'cpp':
            self.context.refresh()
        if active_controller(self.page.backend,self.page) is not None:
            self.ga_status_label.setText('Another PID/GA/BO page is using this backend')
            return
        if not self.manual_ga_mode_check.isChecked() and (not self.page.tuning_enabled or self.page.engine_error):
            self.ga_status_label.setText(self.page.engine_error or 'Automatic GA is enabled only in simulation, matching existing tuning restrictions')
            return
        super().start_ga()


class GAPIDPage(DetailPage):
    engine_kind = 'cpp'
    page_title = 'GA + C++ PID'

    def __init__(self, go_back, backend_mode, zmq_endpoint='', shared_backend=None,
                 tuning_enabled=None, manage_backend=False, simulation_mode=None, get_beam_state=None):
        super().__init__(self.page_title, 'Genetic gain tuning with calibrated beam feedback', 'Back to Automation', go_back)
        self.backend = shared_backend
        self.backend_mode, self.simulation_mode = backend_mode, simulation_mode
        self.command_adapter = GABackendAdapter(self.backend)
        self.tuning_enabled = bool(tuning_enabled) if tuning_enabled is not None else backend_mode == 'simulation'
        self.engine_error = ''
        try:
            engine = CppPIDAdapter() if self.engine_kind == 'cpp' else NLAPID()
        except RuntimeError as exc:
            self.engine_error = str(exc)
            # Display-only placeholder; start_pid is blocked and never falls back to Python execution.
            engine = NLAPID()
        self.context = ControllerContext(self.backend,get_beam_state,self)
        _, layout = self.add_workspace()
        self.workspace = _Workspace(self,engine)
        if self.engine_kind == 'cpp':
            from python.app.Automation.GA.CppLayout import install_cpp_layout, style_cpp_shell
            install_cpp_layout(self.workspace)
            style_cpp_shell(self, go_back, layout)
        else:
            self.workspace.setStyleSheet('QWidget { color: #e8edf2; }')
        layout.addWidget(self.workspace)
        self.workspace.setMinimumHeight(650)
        if self.engine_error:
            self.workspace.pid_status_label.setText(self.engine_error)
            self.workspace.start_pid_button.setEnabled(False)
        self.workspace.arm_output_check.setEnabled(self.tuning_enabled and not self.engine_error)
        self.workspace.auto_ga_arm_check.setEnabled(self.tuning_enabled and not self.engine_error)
        if not self.tuning_enabled:
            self.workspace.arm_output_check.setToolTip('Output on the GA workspace is restricted to simulation until beam-feedback hardware commissioning is completed.')
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.context.refresh)
        self.timer.timeout.connect(lambda: recording(self))
        if self.engine_kind == 'cpp':
            self.timer.timeout.connect(self._refresh_channel_enable)
            self._refresh_channel_enable()
        self.timer.start(100)

    def _refresh_channel_enable(self):
        w = self.workspace
        index = w._actuator_index
        name = self.context.channel_name(index)
        on, enabled = self.context.power_states[index], self.context.enable_states[index]
        w.channel_state_label.setText(f'{name}: {"on" if on else "off"} / {"enabled" if enabled else "disabled"}')
        w.enable_channel_button.setText(f'Enable {name}')
        busy = self.pid_enabled or self.tuning_session_active or active_controller(self.backend, self) is not None
        w.enable_channel_button.setEnabled(self.tuning_enabled and self.backend is not None and not busy
                                          and w._pending_actuator_index == index and not (on and enabled))

    def enable_selected_channel(self):
        w = self.workspace
        try:
            if self.pid_enabled or self.tuning_session_active or active_controller(self.backend, self) is not None:
                raise ValueError('Stop PID/GA before enabling the channel')
            if w._pending_actuator_index != w._actuator_index:
                raise ValueError('Confirm the selected actuator first')
            self.command_adapter.enable_channel(
                w._actuator_index, (w.tc_min_spin.value(), w.tc_max_spin.value()),
                authorized=self.engine_kind == 'cpp' and self.tuning_enabled,
                max_age_s=w._beam_stale_limit())
            message = f'{self.context.channel_name(w._actuator_index)} enable requested; waiting for on/enabled readback'
        except Exception as exc:
            message = f'Enable failed: {exc}'
        w.pid_status_label.setText(message)
        w.ga_status_label.setText(message)
        self.context.refresh()
        self._refresh_channel_enable()

    @property
    def pid_enabled(self):
        return hasattr(self,'workspace') and self.workspace._pid_running

    @property
    def tuning_session_active(self):
        return hasattr(self,'workspace') and (self.workspace._ga_auto_active or (self.workspace.ga_tuner is not None and not self.workspace.ga_tuner.finished and self.context.active_mode.value == 'GA_TUNING'))

    def apply_delta(self,index,delta,result):
        w = self.workspace
        if not self.tuning_enabled or self.engine_error or not w.arm_output_check.isChecked() or self.backend is None:
            return False
        if active_controller(self.backend,self) is not None:
            return False
        if not self.context.beam_snapshot(w._beam_stale_limit())['valid']:
            return False
        accepted = self.command_adapter.apply_delta(index,delta,self.context.target_limits[index],
                                                    authorized=True,max_age_s=w._beam_stale_limit())
        if accepted:
            self.context.targets[index] = float(self.backend.PendingCommand()[index]['target'])
        return accepted

    def stop_backend(self):
        self.timer.stop()
        w = self.workspace
        w._ga_auto_active = False
        w.ga_evaluator.active = False
        w.stop_pid(reason='Page closed')
        w._pid_timer.stop()
        w._ga_sequence_timer.stop()
        w._display_timer.stop()
        w.arm_output_check.setChecked(False)
        w.auto_ga_arm_check.setChecked(False)
        recording(self, 'close')
        for name in ('settings_dialog', 'ga_settings_dialog'):
            dialog = getattr(w, name, None)
            if dialog is not None:
                dialog.close()

    def closeEvent(self,event):
        self.stop_backend()
        super().closeEvent(event)


class PythonGAPIDPage(GAPIDPage):
    engine_kind = 'python'
    page_title = 'GA + Python PID'
