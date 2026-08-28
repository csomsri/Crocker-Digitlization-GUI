from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from source.Python.Services.AlarmService import AlarmService
from source.Python.Services.BeamCalibrationService import BeamCalibrationService
from source.Python.Services.InterlockService import InterlockService
from source.Python.Services.SignalMapService import SignalMapService


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    beam = BeamCalibrationService(root / "config" / "beam_cal.json")
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

    alarm = AlarmService(root / "config" / "alarm_config.json", None)
    assert alarm.update({"timestamp": 1.0, "signals": {"rf_kv": 10.0}}) == []
    active = alarm.update({"timestamp": 2.0, "signals": {"rf_kv": 11.2}})
    assert len(active) == 1
    assert active[0].code == "RF_DELTA"

    alarm.acknowledge()
    acknowledged = alarm.active()
    assert len(acknowledged) == 1
    assert acknowledged[0].acknowledged

    writable_alarm_config = root / "Exports" / "addon_alarm_config.test.json"
    try:
        writable_alarm_config.write_text(
            (root / "config" / "alarm_config.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        editable_alarm = AlarmService(writable_alarm_config, None)
        saved = editable_alarm.save_config({"enabled": False, "vac_channels": "vac3, vac4"})
        assert saved["enabled"] is False
        assert saved["vac_channels"] == ["vac3", "vac4"]
    finally:
        try:
            writable_alarm_config.unlink()
        except OSError:
            pass

    signal_map = SignalMapService(root / "config" / "signal_map.json")
    signal_snapshot = {
        "timestamp": 3.0,
        "channels": [
            {"raw": float(index), "actual": float(index), "on": False, "enabled": False}
            for index in range(14)
        ],
    }
    signal_map.enrich_snapshot(signal_snapshot)
    assert signal_snapshot["signals"]["rf_kv"] == 4.0
    assert signal_snapshot["signal_classes"]["rf_kv"] == "rf"
    assert signal_snapshot["signals"]["main_magnet_current"] == 12.0

    interlock_config = root / "Exports" / "interlock_config.test.json"
    try:
        interlock_config.write_text(
            """
{
  "enabled": true,
  "rules": [
    {
      "id": "rf_high",
      "enabled": true,
      "signal": "rf_kv",
      "operator": ">",
      "limit": 3.0,
      "severity": "Critical",
      "code": "RF_HIGH",
      "message": "RF high",
      "interlock_channels": ["ch5"]
    }
  ]
}
""".strip(),
            encoding="utf-8",
        )
        interlocks = InterlockService(interlock_config)
        events = interlocks.evaluate(signal_snapshot)
        assert len(events) == 1
        assert events[0]["code"] == "RF_HIGH"
        assert signal_snapshot["channels"][4]["interlocked"] is True
        assert signal_snapshot["channels"][4]["status"] == "Interlocked"
        filtered = interlocks.filter_command(
            {
                "channels": [
                    {"target": 1.0, "on": True, "enabled": True}
                    for _ in range(14)
                ]
            }
        )
        assert filtered["channels"][4]["on"] is False
        assert filtered["channels"][4]["enabled"] is False
        assert filtered["interlock_filtered"] is True
    finally:
        try:
            interlock_config.unlink()
        except OSError:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
