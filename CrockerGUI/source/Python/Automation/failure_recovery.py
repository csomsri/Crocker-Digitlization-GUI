"""Shared failure recovery coordinator. Never enables a disabled output."""
import math
import time

from .reference_recovery import RecoveryManager, RecoveryConfig
from .ga_backend_adapter import GABackendAdapter


class FailureRecovery:
    def __init__(self, backend):
        self.backend = backend
        self.adapter = GABackendAdapter(backend)
        self.planner = RecoveryManager()
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
            config = config or RecoveryConfig()
            if not self.beam_required:
                from dataclasses import replace
                config = replace(config, minimum_beam_nA=0., minimum_beam_fraction=0., beam_reference_tolerance_nA=0.)
            self.planner.start(reference=self.reference, config=config, timestamp_s=time.monotonic())
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
            if time.monotonic() - self.planner.start_time >= self.planner.config.timeout_s:
                raise ValueError('Recovery timed out')
            snapshot = self._snapshot(self.index)
            if self.beam_required and (not beam_valid or not math.isfinite(beam) or
                    beam_timestamp is None or not math.isfinite(beam_timestamp) or
                    not 0 <= time.time() - beam_timestamp <= 1):
                raise ValueError('Fresh beam telemetry required')
            sample = (float(snapshot['timestamp']), beam_timestamp if self.beam_required else None)
            if self.last_sample is not None and (sample[0] <= self.last_sample[0] or
                    (self.beam_required and (sample[1] is None or sample[1] <= self.last_sample[1]))):
                return
            self.last_sample = sample
            targets = [float(c['target']) for c in self.backend.PendingCommand()]
            proposal = self.planner.next_command(targets)
            if proposal:
                if time.monotonic() - self.last_command_time < .05:
                    return
                if not self.adapter.apply_delta(proposal.channel_index, proposal.delta_a, self.limits,
                                                authorized=authorized, max_age_s=1):
                    raise ValueError('Recovery command rejected')
                self.last_command_time = time.monotonic()
                targets = [float(c['target']) for c in self.backend.PendingCommand()]
            state = self.planner.observe(timestamp_s=time.monotonic(), current_targets_a=targets,
                actual_values_a=[float(c['actual']) for c in snapshot['channels']],
                beam_nA=beam if self.beam_required else 0.)
            self.status = f'{self.reason}: {state.status}; PID and tuning stopped'
            if state.complete:
                self.active = False
        except Exception as exc:
            self.active = False
            self.status = f'{self.reason}: recovery stopped — {exc}'
