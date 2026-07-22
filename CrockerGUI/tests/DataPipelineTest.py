from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from source.Python.Data.data_logger import run_smoke_logger
from source.Python.Data.data_processor import process_latest_window


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "pipeline.sqlite3"
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
