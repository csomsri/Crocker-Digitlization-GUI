"""Shared failure recovery coordinator. Never enables a disabled output."""
import math
import time

from .ga_recovery import GARecoveryManager
from .ga_backend_adapter import GABackendAdapter


class FailureRecovery:
    def __init__(self, backend):
        self.backend = backend
        self.adapter = GABackendAdapter(backend)
        self.planner = GARecoveryManager()
        self.reference = None
        self.active = False
        self.status = 'No recovery reference captured'
        self.last_sample = None

    def capture(self, index, beam, *, beam_required, limits):
        self.reference = None
        if not 0 <= index < 12:
            raise ValueError('Automatic reference recovery supports TC1–TC12 only')
        snapshot = self._snapshot(index)
        commands = self.backend.PendingCommand()
        target = float(commands[index]['target'])
        if not commands[index]['on'] or not commands[index]['enabled'] or not limits[0] <= target <= limits[1]:
            raise ValueError('Reference requires an enabled command within limits')
        if beam_required and not math.isfinite(beam):
            raise ValueError('Reference requires fresh beam feedback')
        self.reference = self.planner.capture(
            targets_a=[float(c['target']) for c in commands],
            actual_values_a=[float(c['actual']) for c in snapshot['channels']],
            beam_nA=beam if beam_required else 0., channel_indices=[index], timestamp_s=time.time())
        self.index, self.limits, self.beam_required = index, limits, beam_required
        self.status = f'Reference captured: channel {index + 1}, {target:g} A'

    def _snapshot(self, index):
        snapshot = self.backend.LatestSnapshot()
        age = time.time() - float(snapshot['timestamp'])
        channel = snapshot['channels'][index]
        if not math.isfinite(age) or not 0 <= age <= 1 or str(self.backend.Health()['connection']).lower() != 'connected':
            raise ValueError('Fresh connected telemetry required')
        if channel.get('interlocked') or channel.get('status') in ('Fault', 'Interlocked'):
            raise ValueError('Hardware fault or interlock blocks recovery')
        if not channel.get('on') or not channel.get('enabled'):
            raise ValueError('Output disabled; recovery will not re-enable it')
        if not math.isfinite(float(channel['actual'])):
            raise ValueError('Invalid coil readback')
        return snapshot

    def start(self, *, authorized, dry_run, reason, config=None):
        self.active = False
        self.reason = reason
        try:
            if self.reference is None:
                raise ValueError('No verified session reference')
            if not authorized or dry_run:
                raise ValueError('Recovery requires armed output and dry run off')
            self._snapshot(self.index)
            self.planner.start(reference=self.reference)
            self.last_sample = None
            self.last_command_time = float('-inf')
            self.active = True
            self.status = f'{reason}: restoring reference'
        except Exception as exc:
            self.status = f'{reason}: recovery blocked — {exc}'
        return self.active

    def poll(self, *, authorized, beam, beam_valid, beam_timestamp=None):
        if not self.active:
            return
        try:
            if not authorized:
                raise ValueError('Output authorization removed')
            self._snapshot(self.index)
            targets = [float(c['target']) for c in self.backend.PendingCommand()]
            proposal = self.planner.next_command(targets)
            if proposal:
                if not self.adapter.apply_delta(proposal.channel_index, proposal.delta_a, self.limits,
                        authorized=authorized, max_age_s=1, fresh_decision=False):
                    raise ValueError('Target reset rejected')
                target = float(self.backend.PendingCommand()[proposal.channel_index]['target'])
                if round(target, 2) != round(proposal.reference_target_a, 2):
                    raise ValueError('Captured target was not restored')
                return
            self.status = f'{self.reason}: captured target restored; PID and tuning stopped'
            self.active = False
        except Exception as exc:
            self.active = False
            self.status = f'{self.reason}: recovery stopped — {exc}'
