"""Cruise workflow coordination; existing PID/BO methods own transport and trials."""
import time
import math
import json
from dataclasses import dataclass
from source.Python.Automation.cruise_supervisor import CruiseSupervisor
from source.Python.Optimization.pid_gain_adapter import PidGainCandidate
from python.app.Automation.ControlOwnership import active_controller
from python.app.Automation.HardwareProfileDialog import PROFILE_PATH
from python.app.widgets.MagneticFieldWidgets import CHANNEL_NAMES


@dataclass(frozen=True)
class CruiseRunSettings:
    channel: int
    target: float
    gains: PidGainCandidate
    minimum: float
    maximum: float
    controller: dict


class CruiseControllerMixin:
    def _initialize_cruise(self):
        self.cruise = CruiseSupervisor()
        self._cruise_pending = False
        self._cruise_auto_validate = False
        self._cruise_previous: CruiseRunSettings | None = None
        self._cruise_context = None
        self._cruise_costs = []
        self._cruise_message = 'Ready to start'
        self._cruise_stop_failed = False

    def _cruise_ramp_settled(self):
        try:
            target = float(self.backend.PendingCommand()[self.selected_index]['target'])
            actual = self.actual_values[self.selected_index]
            return math.isfinite(actual) and abs(target-actual) <= self.cruise_workspace.ramp_tolerance.value()
        except (AttributeError, TypeError, ValueError, RuntimeError, KeyError):
            return False

    def _cruise_search_complete(self):
        w = self.cruise_workspace
        if time.perf_counter()-self.coil_session_started >= w.search_minutes.value()*60:
            return True
        # Leave enough observations for GP-guided trials before using plateau detection.
        initial = self.tuning_optimizer.optimizer.initial_safe_trials
        eligible = [r.score for r in self.tuning_results if r.safe and not (r.metrics and r.metrics.sustained_oscillation)]
        patience = w.patience.value()
        if len(eligible) < initial+patience:
            return False
        previous = min(eligible[:-patience])
        improvement = previous-min(eligible[-patience:])
        return improvement <= max(abs(previous)*.01, 1e-9)

    def _show_cruise_advanced(self):
        self.page_stack.setCurrentWidget(self._advanced_control_page)

    def _cruise_snapshot(self):
        return CruiseRunSettings(self.selected_index, self.setpoint_input.value(),
                PidGainCandidate(self.kp_input.value(), self.ki_input.value(), self.kd_input.value()),
                self.min_output_input.value(), self.max_output_input.value(), self._controller_config())

    def _cruise_fingerprint(self):
        profile = PROFILE_PATH.read_bytes() if (self.backend_mode != 'simulation' and self.simulation_mode != 'first-order') else b''
        return (self.selected_index, self.setpoint_input.value(), self._feedback_identity,
                self.dry_run_check.isChecked(), profile)

    def _cruise_ready(self):
        if not self.backend_available or self.backend is None:
            raise RuntimeError('Control backend unavailable')
        if active_controller(self.backend, self) is not None:
            raise RuntimeError('Another controller owns this backend')
        self._refresh_beam()
        if not self.beam_valid:
            raise RuntimeError('Fresh calibrated beam feedback required')
        health = self.backend.Health()
        channel = self.backend.LatestSnapshot()['channels'][self.selected_index]
        if (str(health['connection']).lower() != 'connected'
                or float(health['packet_age_ms']) > 1000
                or channel.get('interlocked') or channel.get('status') in {'Fault', 'Interlocked'}):
            raise RuntimeError('Connection, telemetry or coil interlock check failed')
        if (self.backend_mode != 'simulation' and self.simulation_mode != 'first-order'):
            from source.Python.Automation.hardware_profile import HardwareProfile
            source = PROFILE_PATH.read_bytes()
            cached = getattr(self, '_cruise_profile_cache', None)
            if cached is None or cached[0] != source:
                self._cruise_profile_cache = (source, HardwareProfile.from_data(json.loads(source), CHANNEL_NAMES))
            limits = self._cruise_profile_cache[1].allocation_for(CHANNEL_NAMES[self.selected_index])
            current = float(self.backend.PendingCommand()[self.selected_index]['target'])
            if not limits.minimum_command[self.selected_index] <= current <= limits.maximum_command[self.selected_index]:
                raise RuntimeError('Current command outside the selected hardware profile')
            lower = max(limits.minimum_command[self.selected_index], self.min_output_input.value())
            upper = min(limits.maximum_command[self.selected_index], self.max_output_input.value())
            self._cruise_limits_text = (f'Effective current {lower:g}–{upper:g} A · '
                f'Correction ≤ {min(limits.max_control_output, self.max_step_input.value()):g} A/update · '
                f'Error abort {limits.max_absolute_error:g} nA · '
                f'{"LabVIEW ramping" if limits.external_ramp else "Local slew limit"}')
        else:
            self._cruise_limits_text = 'Simulation · No real hardware output'
        return True

    def _start_cruise(self):
        if self.cruise.active or self.tuning_session_active or self.pid_enabled or self._cruise_stop_failed:
            return
        try:
            self._cruise_ready()
            # A single explicit Start authorizes arming and live selected-coil control.
            self.arm_button.setChecked(True)
            self.dry_run_check.setChecked(False)
            self.output_on_check.setChecked(True)
            self.control_enabled_check.setChecked(True)
            self.enable_button.setChecked(True)
            if not self.pid_enabled:
                raise RuntimeError(self.last_safety_message)
            self.cruise.start(time.perf_counter(), self.cruise_workspace.cooldown.value())
            self._cruise_pending = False
            self.apply_tuned_gains_button.setProperty('approvedCandidate', None)
            self.apply_tuned_gains_button.setEnabled(False)
            self._cruise_message = 'Monitoring tracking; Tune now is available'
        except Exception as exc:
            self.last_safety_message = f'Start blocked: {exc}'
        self._refresh_status()

    def _stop_cruise(self):
        if active_controller(self.backend, self) is not None:
            self.last_safety_message = 'Another controller owns this backend; Stop from its owning page.'
            self._refresh_status()
            return
        self.cruise.stop()
        self._cruise_auto_validate = self._cruise_pending = False
        self.apply_tuned_gains_button.setEnabled(False)
        self.apply_tuned_gains_button.setProperty('approvedCandidate', None)
        failures = []
        # Attempt every stop action even when an earlier transport call fails.
        actions = [self._stop_tuning_session, lambda: self._stop_pid('Operator Stop')]
        if self.backend is not None:
            actions.append(lambda: self.backend.StopPidTrial(True))
            def transmit_disable():
                command = self.backend.PendingCommand()[self.selected_index]
                self.backend.SetChannelCommand(self.selected_index, float(command['target']), False, False)
                if not self.backend.ApplyCommand():
                    raise RuntimeError('Output-disable command was rejected')
            actions.append(transmit_disable)
        for action in actions:
            try:
                action()
            except Exception as exc:
                failures.append(str(exc))
        if not failures:
            self.channel_on[self.selected_index] = False
            self.channel_enabled[self.selected_index] = False
            self._sync_channel_toggles()
            self.arm_button.setChecked(False)
            self._cruise_stop_failed = False
            self.last_safety_message = 'Control stopped; output-disable sent. Verify actual current; LabVIEW owns physical ramping.'
        else:
            self._cruise_stop_failed = True
            self.last_safety_message = f'Stop could not be confirmed: {"; ".join(failures)}. Check hardware; Stop is available to retry.'
        self._refresh_status()

    def _begin_cruise_tuning(self):
        if not self.cruise.active or not self.pid_enabled or self.tuning_session_active or self._cruise_pending:
            return
        try:
            self._cruise_ready()
            self._cruise_previous = self._cruise_snapshot()
            self._cruise_context = self._cruise_fingerprint()
            self.tuner_channel.setCurrentIndex(self.selected_index)
            self.tuner_target.setValue(self.setpoint_input.value())
            for gain in ('Kp', 'Ki', 'Kd'):
                value = getattr(self._cruise_previous.gains, gain.lower())
                lower, upper = self.tuner_gain_bounds[gain]
                if not lower.value() <= value <= upper.value():
                    raise RuntimeError(f'Current {gain} is outside BO bounds; adjust Advanced PID / BO bounds')
            self._cruise_auto_validate = True
            self._start_auto_tuning()
            if not self.tuning_session_active:
                raise RuntimeError(self.tuner_status.text())
            self.cruise.sessions += 1
            self._cruise_message = 'BO search running'
        except Exception as exc:
            self._cruise_auto_validate = False
            self._cruise_message = f'Tuning blocked: {exc}'
            self.cruise.rearm(time.perf_counter(), self.cruise_workspace.cooldown.value())
        self._refresh_status()

    def _restore_cruise_previous(self):
        if self._cruise_previous is None:
            return
        previous = self._cruise_previous
        self._restore_controller_config(previous.controller)
        self.channel_select.setCurrentIndex(previous.channel)
        self.setpoint_input.setValue(previous.target)
        for widget, value in ((self.kp_input, previous.gains.kp), (self.ki_input, previous.gains.ki), (self.kd_input, previous.gains.kd),
                              (self.min_output_input, previous.minimum), (self.max_output_input, previous.maximum)):
            widget.setValue(value)

    def _finish_cruise_validation(self, *, valid, safe):
        if not self.cruise.active:
            return
        if not safe:
            self._stop_cruise()
            if not self._cruise_stop_failed:
                self.last_safety_message = 'BO validation faulted; automatic recovery suspended. Review trial history.'
            return
        approved = self.apply_tuned_gains_button.property('approvedCandidate')
        self._restore_cruise_previous()
        self.apply_tuned_gains_button.setProperty('approvedCandidate', approved if valid else None)
        self.apply_tuned_gains_button.setEnabled(valid)
        self._cruise_pending = valid
        self._resume_cruise()
        self._cruise_message = ('Validated BO ready · Apply BO to adopt it; previous PID gains remain active'
                               if valid else 'BO validation did not pass the comparison; previous PID gains restored')

    def _resume_cruise(self):
        try:
            self._cruise_ready()
            self.enable_button.setChecked(True)
            if not self.pid_enabled:
                raise RuntimeError(self.last_safety_message)
            self.cruise.rearm(time.perf_counter(), self.cruise_workspace.cooldown.value())
        except Exception as exc:
            self._stop_cruise()
            self.last_safety_message = f'Resume blocked: {exc}'

    def _rollback_cruise(self):
        if not self.cruise.active or self.tuning_session_active or self._cruise_previous is None:
            return
        self._stop_pid('Restoring previous gains')
        self._restore_cruise_previous()
        self._cruise_pending = False
        self.apply_tuned_gains_button.setProperty('approvedCandidate', None)
        self.apply_tuned_gains_button.setEnabled(False)
        self._resume_cruise()
        self._cruise_message = 'Previous gains restored'

    def _apply_cruise_gains(self):
        if (not self.cruise.active or not self._cruise_pending or self.tuning_session_active
                or not self.apply_tuned_gains_button.isEnabled()
                or self.apply_tuned_gains_button.property('approvedCandidate') is None):
            return
        try:
            self._cruise_ready()
            if self._cruise_fingerprint() != self._cruise_context:
                raise RuntimeError('Target, feedback calibration, mode or hardware limits changed; retune before applying')
            self._stop_pid('Applying validated BO gains')
            self._applying_cruise = True
            try:
                self._apply_tuned_gains()
            finally:
                self._applying_cruise = False
            self._cruise_pending = False
            self.apply_tuned_gains_button.setEnabled(False)
            self.apply_tuned_gains_button.setProperty('approvedCandidate', None)
            self._resume_cruise()
            self._cruise_message = 'BO gains applied; settling before drift monitoring resumes'
        except Exception as exc:
            self._cruise_pending = False
            self.apply_tuned_gains_button.setEnabled(False)
            self._cruise_message = f'Apply blocked: {exc}'
        self._refresh_status()

    def _poll_cruise(self):
        if not hasattr(self, 'cruise_workspace') or not self.cruise.active:
            return
        if self._cruise_auto_validate and not self.tuning_session_active and not self.pid_enabled:
            # Faulted searches never cause automatic recovery or re-enable outputs.
            self._stop_cruise()
            if not self._cruise_stop_failed:
                self.last_safety_message = 'BO stopped without a validated result. Review trial history before Start.'
            return
        if not self.pid_enabled and not self.tuning_session_active:
            reason = self.last_safety_message
            self._stop_cruise()
            if not self._cruise_stop_failed:
                self.last_safety_message = f'Controller stopped: {reason}; automatic recovery suspended'
            return
        if self.pid_enabled:
            try:
                self._cruise_ready()
            except Exception as exc:
                self._stop_cruise()
                if not self._cruise_stop_failed:
                    self.last_safety_message = str(exc)
                return
        w = self.cruise_workspace
        if self.cruise.should_tune(now=time.perf_counter(), stamp=self.beam_timestamp,
                error=self.setpoint_input.value()-self._feedback_value(),
                ready=self.pid_enabled and (not w.wait_for_ramp.isChecked() or self._cruise_ramp_settled()),
                pending=self._cruise_pending, automatic=w.automatic.isChecked(),
                band=w.band.value(), persistence=w.persistence.value(), maximum_sessions=w.max_sessions.value()):
            self._begin_cruise_tuning()
