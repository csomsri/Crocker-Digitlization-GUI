from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from source.Python.Data.data_logger import (
    run_smoke_logger,
    run_snapshot_logger_loop,
    snapshot_to_readings,
)
from source.Python.Data.data_processor import process_latest_window


def main() -> int:
    snapshot_readings = snapshot_to_readings(
        {
            "timestamp": 123.0,
            "sequence_number": 1,
            "channels": [
                {
                    "raw": 10.0,
                    "actual": 6.0,
                    "units": "A",
                    "on": True,
                    "enabled": True,
                }
            ],
            "bitmask": 7,
            "beam": {
                "raw_value": 0.25,
                "display_ua": 0.0005,
                "full_scale_ua": 0.001,
                "range_index": 2,
                "quality": "ok",
            },
            "active_alarms": [
                {
                    "id": "rf_delta",
                    "code": "RF_DELTA",
                    "active": True,
                    "acknowledged": False,
                    "severity": "Warning",
                }
            ],
        },
        source="transport",
    )
    assert snapshot_readings[0].channel == "ch1"
    assert snapshot_readings[0].raw_value == 10.0
    assert snapshot_readings[0].engineering_value == 6.0
    assert snapshot_readings[0].units == "A"
    bitmask_reading = next(reading for reading in snapshot_readings if reading.channel == "bitmask")
    assert int(bitmask_reading.raw_value) == 7
    beam_reading = next(reading for reading in snapshot_readings if reading.channel == "beam_current")
    assert beam_reading.raw_value == 0.25
    assert beam_reading.engineering_value == 0.0005
    assert beam_reading.units == "uA"
    alarm_count = next(reading for reading in snapshot_readings if reading.channel == "alarm_count")
    assert alarm_count.engineering_value == 1.0
    alarm_state = next(reading for reading in snapshot_readings if reading.channel == "alarm:rf_delta")
    assert alarm_state.raw_value == 1.0
    assert alarm_state.engineering_value == 0.0

    db_path = Path(__file__).resolve().parents[1] / "data" / "pipeline_test.sqlite3"
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(str(db_path) + suffix).unlink()
        except FileNotFoundError:
            pass

    try:
        run_id = run_smoke_logger(
            db_path=db_path,
            rate_hz=0.0,
            frames=4,
            batch_size=10,
        )

        processed_count = process_latest_window(
            db_path=db_path,
            window_seconds=60.0,
        )

        connection = sqlite3.connect(db_path)
        try:
            run_count = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            reading_count = connection.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
            metric_count = connection.execute(
                "SELECT COUNT(*) FROM processed_metrics"
            ).fetchone()[0]
        finally:
            connection.close()

        assert run_id == 1
        assert run_count == 1
        assert reading_count == 60
        assert processed_count == 14
        assert metric_count == 14
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(db_path) + suffix).unlink()
            except FileNotFoundError:
                pass

    dedupe_db_path = Path(__file__).resolve().parents[1] / "data" / "pipeline_dedupe_test.sqlite3"
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(str(dedupe_db_path) + suffix).unlink()
        except FileNotFoundError:
            pass

    try:
        stop_event = Event()
        calls = 0
        snapshot = {
            "timestamp": 124.0,
            "channels": [{"raw": 1.0, "actual": 2.0, "on": False, "enabled": False}],
        }

        def snapshot_source() -> dict:
            nonlocal calls
            calls += 1
            if calls >= 3:
                stop_event.set()
            return snapshot

        run_snapshot_logger_loop(
            db_path=dedupe_db_path,
            snapshot_source=snapshot_source,
            rate_hz=0.0,
            batch_size=1,
            stop_event=stop_event,
            source="transport",
        )
        connection = sqlite3.connect(dedupe_db_path)
        try:
            dedupe_reading_count = connection.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        finally:
            connection.close()
        assert dedupe_reading_count == 3
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(dedupe_db_path) + suffix).unlink()
            except FileNotFoundError:
                pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
