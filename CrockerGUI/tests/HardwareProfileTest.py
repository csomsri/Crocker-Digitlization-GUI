"""Validation test for fail-closed PID hardware allocation profiles."""

from __future__ import annotations

import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

CROCKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CROCKER_ROOT))

from source.Python.Automation.hardware_profile import HardwareProfile, apply_hardware_profile, approve_operator_limits


def main() -> int:
    channels = ("TC1", "TC2")
    profile = {
        "profile_name": "test", "approval_status": "approved",
        "provenance": {
            "measurement_date": "2026-01-01", "machine_configuration": "test",
            "units": "A", "operator": "operator", "reviewer": "reviewer",
            "source_dataset": "sha256:test", "uncertainty": "1%", "valid_until": "2099-01-01",
        },
        "measurement_channels": {"TC1": {
            "allocation": {"TC1": 0.5}, "command_bias": {"TC1": 0},
            "minimum_command": {"TC1": 0, "TC2": 0},
            "maximum_command": {"TC1": 10, "TC2": 10},
            "maximum_slew_per_second": {"TC1": 1, "TC2": 1},
            "abort_limits": {"max_absolute_error": 5, "max_overshoot": 2,
                             "max_control_output": 8, "max_saturation_seconds": 0.5},
        }},
    }
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "profile.json"
        path.write_text(json.dumps(profile), encoding="utf-8")
        loaded = HardwareProfile(path, channels).allocation_for("TC1")
        assert loaded.allocation == [0.5, 0.0]
        config = dict(measurement_channel=0, allocation=[1, 0], command_bias=[3, 0],
                      minimum_command=[2, 0], maximum_command=[20, 20],
                      maximum_slew_per_second=[0.5, 2], max_absolute_error=3,
                      allocation_calibrated=False, external_beam_measurement=True)
        try:
            apply_hardware_profile(config, path, channels)
        except ValueError as exc:
            assert "allocation 1.0" in str(exc)
        else:
            raise AssertionError("nonidentity NLA allocation accepted")
        profile['measurement_channels']['TC1']['allocation']['TC1'] = 1.0
        path.write_text(json.dumps(profile), encoding="utf-8")
        applied = apply_hardware_profile(config, path, channels)
        assert applied['allocation_calibrated'] is True
        assert applied['external_beam_measurement'] is True
        assert applied['minimum_command'][0] == 2
        assert applied['maximum_command'][0] == 10
        assert applied['maximum_slew_per_second'][0] == 0.5
        assert applied['max_absolute_error'] == 3
        assert applied['max_overshoot'] == 2
        assert applied['command_bias'] == [0, 0]
        assert config['allocation_calibrated'] is False
        entry = profile['measurement_channels']['TC1']
        entry['ramp_control'] = 'labview'
        del entry['command_bias']
        del entry['maximum_slew_per_second']
        path.write_text(json.dumps(profile), encoding='utf-8')
        external = apply_hardware_profile(config, path, channels)
        assert external['maximum_slew_per_second'] == [0.0, 0.0]
        assert external['minimum_command'][0] == 2
        assert external['maximum_command'][0] == 10
        operator_profile = deepcopy(profile)
        operator_profile['provenance'] = {}
        approve_operator_limits(operator_profile, approved_by='Test operator', statement='Approved fixture limits')
        HardwareProfile.from_data(operator_profile, channels)
        operator_profile['measurement_channels']['TC1']['maximum_command']['TC1'] = 20
        try:
            HardwareProfile.from_data(operator_profile, channels)
        except ValueError as exc:
            assert 'changed since approval' in str(exc)
        else:
            raise AssertionError('modified operating limits retained approval')
        operator_profile['measurement_channels']['TC1']['allocation'] = {'TC1': .5}
        approve_operator_limits(operator_profile, approved_by='Test operator', statement='Invalid allocation fixture')
        try:
            HardwareProfile.from_data(operator_profile, channels)
        except ValueError as exc:
            assert 'identity allocation' in str(exc)
        else:
            raise AssertionError('operator approval permitted a custom allocation')
        for bad_config in (dict(config, minimum_command=[11, 0]),
                           dict(config, measurement_channel=1)):
            try:
                apply_hardware_profile(bad_config, path, channels)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid hardware trial accepted")
        profile["approval_status"] = "draft"
        path.write_text(json.dumps(profile), encoding="utf-8")
        try:
            HardwareProfile(path, channels)
        except ValueError:
            pass
        else:
            raise RuntimeError("draft hardware profile was accepted")
        try:
            apply_hardware_profile(config, path, channels)
        except ValueError:
            pass
        else:
            raise AssertionError("draft profile allowed a hardware trial")
        profile['approval_status'] = 'approved'
        profile['provenance']['valid_until'] = '2000-01-01'
        path.write_text(json.dumps(profile), encoding='utf-8')
        try:
            apply_hardware_profile(config, path, channels)
        except ValueError as exc:
            assert 'expired' in str(exc)
        else:
            raise AssertionError('expired profile accepted')
    print("PID hardware profile validation test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
