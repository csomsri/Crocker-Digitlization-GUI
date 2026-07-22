from __future__ import annotations

import argparse
import time
from pathlib import Path

from source.Python.Data.pipeline_schema import DEFAULT_DB_PATH, connect_database


def process_latest_window(
    *,
    db_path: str | Path,
    window_seconds: float,
    processor_name: str = "python-window-average",
) -> int:
    connection = connect_database(db_path)
    now = time.time()
    window_start = now - window_seconds
    rows = connection.execute(
        """
        SELECT
            run_id,
            channel,
            AVG(engineering_value) AS average_value,
            MIN(timestamp) AS min_timestamp,
            MAX(timestamp) AS max_timestamp,
            MAX(id) AS source_reading_id
        FROM readings
        WHERE timestamp >= ?
          AND channel != 'bitmask'
          AND quality = 'ok'
        GROUP BY run_id, channel
        """,
        (window_start,),
    ).fetchall()

    metric_rows = [
        (
            int(row["run_id"]),
            now,
            f"{row['channel']}.rolling_average",
            float(row["average_value"]),
            "raw",
            float(row["min_timestamp"]),
            float(row["max_timestamp"]),
            processor_name,
            int(row["source_reading_id"]),
        )
        for row in rows
        if row["average_value"] is not None
    ]

    if metric_rows:
        connection.executemany(
            """
            INSERT INTO processed_metrics (
                run_id,
                timestamp,
                metric_name,
                value,
                units,
                window_start,
                window_end,
                processor,
                source_reading_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            metric_rows,
        )
        connection.commit()

    connection.close()
    return len(metric_rows)


def run_processor_loop(
    *,
    db_path: str | Path,
    window_seconds: float,
    interval_seconds: float,
    stop_file: str | Path | None = None,
) -> None:
    stop_path = Path(stop_file) if stop_file is not None else None
    try:
        while not (stop_path is not None and stop_path.exists()):
            process_latest_window(db_path=db_path, window_seconds=window_seconds)
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        return


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process Crocker telemetry in SQLite.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--window-seconds", type=float, default=5.0)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--stop-file", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.once:
        process_latest_window(
            db_path=args.db_path,
            window_seconds=args.window_seconds,
        )
    else:
        run_processor_loop(
            db_path=args.db_path,
            window_seconds=args.window_seconds,
            interval_seconds=args.interval_seconds,
            stop_file=args.stop_file,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
