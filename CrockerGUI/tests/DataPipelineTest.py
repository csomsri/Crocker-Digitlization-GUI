from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from source.Python.Data.data_logger import run_smoke_logger, snapshot_to_readings
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
                    "on": True,
                    "enabled": True,
                }
            ],
        },
        source="transport",
    )
    assert snapshot_readings[0].channel == "ch1"
    assert snapshot_readings[0].raw_value == 10.0
    assert snapshot_readings[0].engineering_value == 6.0
    assert snapshot_readings[0].units == "engineering"
    assert snapshot_readings[-1].channel == "bitmask"
    assert int(snapshot_readings[-1].raw_value) == (1 | (1 << 14))

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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
