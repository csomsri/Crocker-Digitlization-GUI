from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from source.Python.Services.AlarmService import AlarmService
from source.Python.Services.BeamCalibrationService import BeamCalibrationService


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    beam = BeamCalibrationService(root / "config" / "beam_cal.example.json")
    state = beam.update(
        {
            "timestamp": 1.0,
            "channels": [
                {"raw": 0.0, "actual": 0.0, "on": False, "enabled": False}
                for _ in range(14)
            ],
        }
    )
    assert state.quality == "ok"
    assert state.range_label == "1 nA"
    assert abs(state.current_ua) < 1.0e-12

    alarm = AlarmService(root / "config" / "alarm_config.example.json", None)
    assert alarm.update({"timestamp": 1.0, "signals": {"rf_kv": 10.0}}) == []
    active = alarm.update({"timestamp": 2.0, "signals": {"rf_kv": 11.2}})
    assert len(active) == 1
    assert active[0].code == "RF_DELTA"

    alarm.acknowledge()
    acknowledged = alarm.active()
    assert len(acknowledged) == 1
    assert acknowledged[0].acknowledged

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
