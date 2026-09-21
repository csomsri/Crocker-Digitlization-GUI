"""Command boundary for GA pages using an existing C++ ControlService instance."""
import math
import time


class GABackendAdapter:
    def __init__(self, backend):
        self.backend = backend
        self.last_command_stamp = {}

    def enable_channel(self, index, limits, *, authorized, max_age_s):
        """Power and enable the selected coil without changing its target."""
        if not authorized or self.backend is None or not 0 <= index < 12:
            raise ValueError('Channel enable is unavailable in this mode')
        snapshot = self.backend.LatestSnapshot()
        age = time.time() - float(snapshot.get('timestamp', 0))
        if not 0 <= age <= max_age_s or str(self.backend.Health().get('connection', '')).lower() != 'connected':
            raise ValueError('Fresh connected telemetry is required')
        channel = snapshot['channels'][index]
        if channel.get('interlocked') or channel.get('status') in ('Fault', 'Interlocked'):
            raise ValueError('Clear the channel fault or interlock before enabling')
        previous = self.backend.PendingCommand()[index]
        target = float(previous['target'])
        if not math.isfinite(target) or not limits[0] <= target <= limits[1]:
            raise ValueError('Current target is outside the PID output limits')
        try:
            self.backend.SetChannelCommand(index, target, True, True)
            if self.backend.ApplyCommand():
                return
        except Exception:
            self.backend.SetChannelCommand(index, previous['target'], previous['on'], previous['enabled'])
            raise
        self.backend.SetChannelCommand(index, previous['target'], previous['on'], previous['enabled'])
        raise ValueError('Control service rejected the enable command')

    def apply_delta(self, index, delta, limits, *, authorized, max_age_s):
        if not authorized or self.backend is None or not 0 <= index < 12:
            return False
        snapshot = self.backend.LatestSnapshot()
        stamp = float(snapshot.get('timestamp',0))
        age = time.time()-stamp
        health = self.backend.Health()
        if not math.isfinite(age) or not 0 <= age <= max_age_s or str(health.get('connection','')).lower() != 'connected':
            return False
        channel = snapshot['channels'][index]
        if (not channel.get('on') or not channel.get('enabled') or channel.get('interlocked')
                or channel.get('status') in ('Fault','Interlocked') or not math.isfinite(float(channel['actual']))):
            return False
        previous = self.backend.PendingCommand()[index]
        target = float(previous['target'])+delta
        low, high = limits
        if not math.isfinite(target) or not low <= target <= high or not previous.get('on') or not previous.get('enabled'):
            return False
        # A faster recovery/display timer must not repeat commands for a held packet.
        if stamp <= self.last_command_stamp.get(index, float('-inf')):
            return True
        try:
            self.backend.SetChannelCommand(index,target,True,True)
            if self.backend.ApplyCommand():
                self.last_command_stamp[index] = stamp
                return True
        except Exception:
            self.backend.SetChannelCommand(index,previous['target'],previous['on'],previous['enabled'])
            raise
        self.backend.SetChannelCommand(index,previous['target'],previous['on'],previous['enabled'])
        return False
