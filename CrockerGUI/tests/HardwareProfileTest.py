"""Validation test for fail-closed PID hardware allocation profiles."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

CROCKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CROCKER_ROOT))

from source.Python.PID_Tuner.hardware_profile import HardwareProfile


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
        profile["approval_status"] = "draft"
        path.write_text(json.dumps(profile), encoding="utf-8")
        try:
            HardwareProfile(path, channels)
        except ValueError:
            pass
        else:
            raise RuntimeError("draft hardware profile was accepted")
    print("PID hardware profile validation test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
