"""Python NLAPID trial worker using ControlService only for transport."""
import math
import threading
import time
from .NLAPID import NLAPID, PIDGains, PIDLimits, AdaptiveDirectionSettings


class PythonNLATrial:
    def __init__(self, backend):
        self.backend = backend
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._config = None
        self._status = dict(state="Idle", message="Idle", iterations=0)

    def start(self, config):
        self.stop(False)
        c = dict(config)
        channel = int(c['measurement_channel'])
        if not c['dry_run'] and not c['hardware_armed']:
            raise ValueError("Python NLA trial requires arming")
        if c['duration_seconds'] <= 0 or c['update_rate_hz'] <= 0:
            raise ValueError("Trial duration and rate must be positive")
        self._pid = NLAPID(
            PIDGains(c['kp'], c['ki'], c['kd']),
            PIDLimits(output_min=0, output_max=c.get('nla_output_max', 100)),
            AdaptiveDirectionSettings(
                deadband=c.get('nla_deadband', 0),
                trend_tolerance=c.get('nla_trend_tolerance', 0),
                direction_check_interval=c.get('nla_direction_check_interval', 1),
                initial_direction=c.get('nla_initial_direction', 1),
                integral_memory_s=c.get('nla_integral_memory_s', 20),
            ))
        self._target = float(self.backend.PendingCommand()[channel]['target'])
        if not c['minimum_command'][channel] <= self._target <= c['maximum_command'][channel]:
            raise ValueError("Current target outside trial bounds")
        self._config = c
        self._stop.clear()
        with self._lock:
            self._status = dict(state="Running", message="Python NLAPID running", iterations=0,
                                elapsed_seconds=0.0, measured_field=0.0, error=0.0,
                                control_output=0.0, control_rate=0.0, controller_kind="python_nla")
        self._thread = threading.Thread(target=self._run, name="python-nlapid-trial", daemon=True)
        self._thread.start()

    def status(self):
        with self._lock:
            return dict(self._status)

    def _update(self, **values):
        with self._lock:
            self._status.update(values)

    def stop(self, disable=True):
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        if self.status().get('state') == 'Running':
            self._update(state='Stopped', message='Operator stop')
        if disable and self._config and not self._config['dry_run']:
            channel = self._config['measurement_channel']
            self.backend.SetChannelCommand(channel, self._target, False, False)
            if not self.backend.ApplyCommand():
                self._update(state='Faulted', message='Stop command rejected')

    def _run(self):
        c = self._config
        channel = c['measurement_channel']
        start = time.perf_counter()
        last_stamp = None
        last_fresh = start
        hold = False
        saturation_seconds = 0.0
        iterations = 0
        try:
            while not self._stop.is_set():
                now = time.perf_counter()
                if now-start >= c['duration_seconds']:
                    self._update(state='Completed', message='Python NLA trial completed')
                    return
                snapshot = self.backend.LatestSnapshot()
                health = self.backend.Health()
                ch = snapshot['channels'][channel]
                stamp, measurement = float(snapshot['timestamp']), float(ch['actual'])
                if not math.isfinite(stamp) or not math.isfinite(measurement):
                    raise ValueError('Invalid telemetry')
                if str(health['connection']).lower() != 'connected':
                    raise RuntimeError('Transport disconnected')
                age = float(health.get('packet_age_ms', max(0, time.time()-stamp)*1000))
                if age > c['telemetry_timeout_seconds']*1000 or now-last_fresh > c['telemetry_timeout_seconds']:
                    raise RuntimeError('Telemetry watchdog expired')
                if ch.get('interlocked') or ch.get('status') in {'Fault','Interlocked'}:
                    raise RuntimeError('Channel fault or interlock')
                if last_stamp is not None and stamp < last_stamp:
                    raise RuntimeError('Out-of-order telemetry')
                if last_stamp is None:
                    self._pid.reset(setpoint=c['setpoint'], measurement=measurement)
                    last_stamp = stamp
                    self._update(elapsed_seconds=now-start, measured_field=measurement,
                                 error=c['setpoint']-measurement)
                elif stamp > last_stamp:
                    dt = stamp-last_stamp
                    last_stamp, last_fresh = stamp, now
                    error = c['setpoint']-measurement
                    if abs(error) > c['max_absolute_error'] or -error > c['max_overshoot']:
                        raise RuntimeError('Trial error abort limit exceeded')
                    result = self._pid.update(c['setpoint'], measurement, dt, hold_integrator=hold)
                    if not math.isfinite(result.output) or abs(result.output) > c['max_control_output']:
                        raise RuntimeError('Control output abort limit exceeded')
                    requested = self._target + result.output
                    bounded = max(c['minimum_command'][channel], min(c['maximum_command'][channel], requested))
                    saturation_seconds = saturation_seconds + dt if bounded != requested else 0.0
                    if saturation_seconds > c['max_saturation_seconds']:
                        raise RuntimeError('Command saturation persisted beyond abort limit')
                    step = c['maximum_slew_per_second'][channel]*dt
                    target = max(self._target-step, min(self._target+step, bounded))
                    hold = target != requested
                    if not c['dry_run']:
                        self.backend.SetChannelCommand(channel, target, True, True)
                        if not self.backend.ApplyCommand():
                            raise RuntimeError('Control command rejected')
                    self._target = target
                    iterations += 1
                    self._update(iterations=iterations, elapsed_seconds=now-start,
                                 measured_field=measurement, error=error,
                                 control_output=result.output, control_rate=result.output/min(dt,.25))
                self._stop.wait(1/c['update_rate_hz'])
        except Exception as exc:
            self._update(state='Faulted', message=str(exc))
            if not c['dry_run']:
                try:
                    self.backend.SetChannelCommand(channel, self._target, False, False)
                    self.backend.ApplyCommand()
                except Exception:
                    pass
