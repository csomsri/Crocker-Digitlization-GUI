"""GUI-side extraction of small PID records. Workers never read Qt widgets."""
import time
from uuid import uuid4

from source.Python.Data.pid_database import json_text
from source.Python.Data.telemetry_database import snapshot_id


def recording(page, action='poll', **kwargs):
    recorder = getattr(page, '_database_recorder', None)
    if recorder is not None:
        return getattr(recorder, action)(**kwargs)


class PagePIDRecorder:
    def __init__(self, page, database, database_a, beam_provider):
        self.page, self.database, self.database_a = page, database, database_a
        self.beam_provider = beam_provider
        self.session = None
        self.config = {}
        self.trial_id = None
        self.last_sample = None
        self.last_mode = None
        self.last_config = None
        self.result_count = 0
        self.event_count = 0
        self.error = ''

    def check_trial(self):
        status = self.database.writer.status()
        if status['error'] or status['queue_depth'] >= 512 or status['rejected']:
            raise RuntimeError('Database B recording is unhealthy; resolve recording status before another trial')

    def started(self, config):
        config = dict(config)
        quality = getattr(self.page, '_tuning_quality_settings', None)
        if quality is not None and not config.get('continuous'):
            from dataclasses import asdict
            config['tuning_quality'] = asdict(quality)
        self.config = dict(config)
        self.last_sample = None
        if self.session is None:
            p = self.page
            self.result_count = len(getattr(p, 'tuning_results', []))
            self.event_count = len(getattr(getattr(p, 'hybrid', None), 'events', []))
            self.session = self.database.start(
                a_session_id=self.database_a.session_id if self.database_a.started else None,
                page=type(p).__name__, engine='python' if 'python' in type(p).__name__.lower() else 'cpp',
                feedback_source='coil_current' if not getattr(p, 'beam_feedback', True) else 'calibrated_beam',
                environment=self.environment(), configuration=config)
            if self.session is None:
                self.error = 'Database B rejected session start'
                return
        self.trial_id = uuid4().hex
        self.database.event(self.session, 'pid_started', dict(trial_id=self.trial_id, configuration=config))

    def environment(self):
        p = self.page
        if 'dry_run' in self.config and self.config['dry_run']:
            return 'dry_run'
        return 'simulation' if getattr(p, 'simulation_mode', None) or getattr(p, 'backend_mode', '') == 'simulation' else 'hardware'

    def mode(self):
        p = self.page
        w = getattr(p, 'workspace', None)
        running = bool(p.pid_enabled or getattr(p, 'tuning_trial_candidate', None) is not None)
        tuning = bool(p.tuning_session_active)
        search = 'hybrid' if getattr(p, 'hybrid', None) and tuning else 'GA' if w and tuning else 'BO' if tuning else 'manual'
        recovery = getattr(p, 'recovering', False) or bool(w and getattr(w, '_ga_sequence_state', '') == 'RESTORING')
        state = 'recovery' if recovery else 'validation' if getattr(p, '_validating_gains', False) else 'tuning' if tuning and running else 'PID' if running else 'waiting' if tuning else 'idle'
        return state, search, running, tuning

    def event(self, event, details):
        if self.session:
            self.database.event(self.session, event, details)

    def configure(self, config):
        self.config.update(config)

    def trial(self, result, source='GA'):
        if self.session:
            self.database.trial(self.session, self.trial_id or uuid4().hex, source, result)
            self.trial_id = None

    def poll(self, reason=None, sample=None):
        if self.session is None:
            return  # Navigation, initial recovery and arming alone never activate B.
        try:
            self._poll(reason, sample)
        except Exception as exc:
            self.error = f'PID recording: {exc}'

    def _poll(self, reason, sample):
        p = self.page
        state, search, running, tuning = self.mode()
        mode = state, search
        if mode != self.last_mode:
            self.event('state_changed', dict(controller_state=state, search_mode=search))
            self.last_mode = mode
        results = getattr(p, 'tuning_results', [])
        hybrid = getattr(p, 'hybrid', None)
        for i in range(self.result_count, len(results)):
            extra = hybrid.records[i] if hybrid and i < len(hybrid.records) else {}
            self.trial(dict(result=results[i], comparison=extra), extra.get('source', 'BO'))
        self.result_count = len(results)
        if hybrid:
            for event in hybrid.events[self.event_count:]:
                self.event('optimizer_transition', event)
            self.event_count = len(hybrid.events)
        if reason:
            self.event('pid_stopped', dict(reason=reason))
        if not running and not tuning:
            self.database.stop(self.session, reason or getattr(p, 'last_safety_message', 'PID stopped'))
            self.session = None
            self.last_mode = self.last_config = None
            return
        w = getattr(p, 'workspace', None)
        # GA sends the actual evaluated sample directly from its PID step.
        if w and sample is None and state != 'recovery':
            return
        snapshot = p.backend.LatestSnapshot() if p.backend is not None else {}
        beam = self.beam_provider() if self.beam_provider else {}
        config = self.config
        if not tuning and not w:
            config = p._run_metrics_config()
        serialized = json_text(config)
        if serialized != self.last_config:
            self.event('configuration', config)
            self.last_config = serialized
        index = int(config.get('measurement_channel', config.get('channel', 0)))
        channel = snapshot.get('channels', [])[index] if index < len(snapshot.get('channels', [])) else {}
        target = config.get('setpoint')
        feedback_beam = getattr(p, 'beam_feedback', True)
        feedback = beam.get('current_ua', float('nan')) * 1000 if feedback_beam else channel.get('actual')
        status = {}
        if not w and (getattr(p, '_service_pid_active', False) or getattr(p, 'tuning_trial_candidate', None) is not None):
            status = p._trial_status()
            if status.get('iterations', 0):
                feedback = status.get('measured_field')
        command = None
        if p.backend is not None:
            command = p.backend.PendingCommand()[index].get('target')
        row = dict(timestamp=time.time(), trial_id=self.trial_id,
            snapshot_id=snapshot_id(snapshot), telemetry_timestamp=snapshot.get('timestamp'),
            beam_timestamp=beam.get('timestamp'), beam_quality=beam.get('quality'),
            calibration_revision=beam.get('calibration_revision'), tc_channel=index+1,
            tc_actual_a=channel.get('actual'), tc_command_a=status.get('command_target', command),
            beam_na=beam.get('current_ua', float('nan'))*1000,
            beam_target_na=target if feedback_beam else None, feedback=feedback, target=target,
            error=status.get('error', target-feedback if target is not None and feedback is not None else None),
            feedback_unit='nA' if feedback_beam else 'A',
            kp=config.get('kp'), ki=config.get('ki'), kd=config.get('kd'),
            controller_output=status.get('control_output'), controller_state=state, search_mode=search,
            environment=self.environment(), enabled=int(bool(channel.get('enabled'))),
            armed=int(bool(config.get('hardware_armed', getattr(p, 'armed', False)))),
            status=status.get('message', channel.get('status')), controller_iteration=status.get('iterations'),
            controller_elapsed=status.get('elapsed_seconds'), sample_kind='status_poll')
        if sample:
            row.update(sample)
        key = (self.trial_id, row['telemetry_timestamp'], row['controller_iteration'], row['controller_state'], row['sample_kind'])
        if key != self.last_sample:
            if not self.database.sample(self.session, **row):
                self.error = 'Database B sample queue full; recording gap'
            self.last_sample = key

    def close(self):
        self.poll(reason='Page closed')
        if self.session:
            self.database.stop(self.session, 'Page closed')
            self.session = None
