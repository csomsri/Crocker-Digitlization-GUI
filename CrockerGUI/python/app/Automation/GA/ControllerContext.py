"""Qt presentation bridge to the application's shared C++ ControlService."""
from enum import Enum
import math
import time
from PySide6.QtCore import QObject, Signal
from python.app.widgets.MagneticFieldWidgets import CHANNEL_NAMES


class ControlMode(str, Enum):
    MANUAL = 'MANUAL'
    PID = 'PID'
    GA_TUNING = 'GA_TUNING'


class ControllerContext(QObject):
    target_changed = Signal(int, float)
    mode_changed = Signal(str)

    def __init__(self, backend, beam_provider, parent=None):
        super().__init__(parent)
        self.backend, self.beam_provider = backend, beam_provider
        self.channel_names = list(CHANNEL_NAMES)
        self.actual_values = [float('nan')]*len(self.channel_names)
        self.targets = [0.0]*len(self.channel_names)
        self.power_states = [False]*len(self.channel_names)
        self.enable_states = [False]*len(self.channel_names)
        self.target_limits = [(0.,100.) for _ in self.channel_names]
        self.active_mode = ControlMode.MANUAL
        self.snapshot = {}
        self.health = {}
        self._beam = {}
        self._beam_identity = None
        self._epoch = time.time()-time.monotonic()
        self.refresh()

    def refresh(self):
        try:
            self.snapshot = self.backend.LatestSnapshot()
            self.health = self.backend.Health()
            commands = self.backend.PendingCommand()
            for i, channel in enumerate(self.snapshot['channels'][:len(self.channel_names)]):
                self.actual_values[i] = float(channel['actual'])
                self.power_states[i] = bool(channel.get('on',False))
                self.enable_states[i] = bool(channel.get('enabled',False))
                value = float(commands[i]['target'])
                if value != self.targets[i]:
                    self.targets[i] = value
                    self.target_changed.emit(i,value)
            self._beam = self.beam_provider() if self.beam_provider else {}
        except Exception:
            self.snapshot, self.health, self._beam = {}, {}, {}
            self.power_states = [False]*len(self.channel_names)
            self.enable_states = [False]*len(self.channel_names)

    def beam_snapshot(self, max_age_s=2):
        self.refresh()
        try:
            stamp = float(self._beam.get('timestamp',0))
            age = time.time()-stamp
            value = float(self._beam.get('current_ua',float('nan')))*1000
            transport_age = time.time()-float(self.snapshot.get('timestamp',0))
        except (TypeError, ValueError, OverflowError, AttributeError):
            return dict(value_nA=float('nan'), timestamp=0., age_s=float('inf'),
                        valid=False, status='INVALID BEAM FEEDBACK')
        identity = tuple(self._beam.get(k) for k in ('range_index','calibration_revision','select_mode'))
        changed = self._beam_identity is not None and identity != self._beam_identity
        valid = (self._beam.get('quality') == 'ok' and math.isfinite(value)
                 and 0 <= age <= max_age_s and 0 <= transport_age <= max_age_s
                 and str(self.health.get('connection','')).lower() == 'connected' and not changed)
        return dict(value_nA=value, timestamp=stamp-self._epoch, age_s=age,
                    valid=valid, status=('BEAM CALIBRATION CHANGED' if changed else
                                         'LIVE' if valid else 'NO FRESH CALIBRATED BEAM'))

    def beam_current(self, max_age_s=2):
        sample = self.beam_snapshot(max_age_s)
        return sample['value_nA'] if sample['valid'] else float('nan')

    def target(self,index): return self.targets[index]
    def actual(self,index): return self.actual_values[index]
    def channel_name(self,index): return self.channel_names[index]
    def targets_snapshot(self): return list(self.targets)
    def can_write(self,mode): return self.active_mode == mode

    def set_mode(self, mode):
        if ControlMode(mode) == ControlMode.MANUAL:
            self._beam_identity = None
        elif self.active_mode == ControlMode.MANUAL:
            self._beam_identity = tuple(self._beam.get(k) for k in
                                        ('range_index','calibration_revision','select_mode'))
        self.active_mode = ControlMode(mode)
        self.mode_changed.emit(self.active_mode.value)

    def set_target_limits(self,index,low,high):
        if not all(math.isfinite(v) for v in (low,high)) or low >= high:
            raise ValueError('Invalid trim-coil limits')
        self.target_limits[index] = low,high

    def clamp_target(self,index,value):
        lo,hi = self.target_limits[index]
        return max(lo,min(hi,value))
