from __future__ import annotations

import argparse
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable

from source.Python.Data.pipeline_schema import (
    DEFAULT_DB_PATH,
    connect_database,
    finish_run,
    start_run,
)
from source.Python.Simulator.ZMQSimulator import EPOCH_OFFSET, SimulatorFrame, generate_frame

CHANNEL_NAMES = [f"ch{index}" for index in range(1, 13)] + ["main_magnet", "centering_beam"]


@dataclass(frozen=True)
class Reading:
    timestamp: float
    logged_at: float
    channel: str
    raw_value: float
    engineering_value: float
    units: str
    source: str
    quality: str = "ok"


def snapshot_to_readings(snapshot: dict, *, source: str) -> list[Reading]:
    channels = snapshot.get("channels", [])
    timestamp = float(snapshot.get("timestamp") or time.time())
    logged_at = time.time()
    readings: list[Reading] = []

    bitmask = 0
    for index, channel in enumerate(channels[: len(CHANNEL_NAMES)]):
        if not isinstance(channel, dict):
            continue
        raw_value = float(channel.get("raw", 0.0))
        engineering_value = float(channel.get("actual", raw_value))
        readings.append(
            Reading(
                timestamp=timestamp,
                logged_at=logged_at,
                channel=CHANNEL_NAMES[index],
                raw_value=raw_value,
                engineering_value=engineering_value,
                units="engineering",
                source=source,
            )
        )
        if bool(channel.get("on", False)):
            bitmask |= 1 << index
        if bool(channel.get("enabled", False)):
            bitmask |= 1 << (len(CHANNEL_NAMES) + index)

    readings.append(
        Reading(
            timestamp=timestamp,
            logged_at=logged_at,
            channel="bitmask",
            raw_value=float(bitmask),
            engineering_value=float(bitmask),
            units="mask",
            source=source,
        )
    )
    return readings


def frame_to_readings(frame: SimulatorFrame, *, source: str) -> list[Reading]:
    timestamp = frame.timestamp - EPOCH_OFFSET
    logged_at = time.time()
    readings = [
        Reading(
            timestamp=timestamp,
            logged_at=logged_at,
            channel=f"ch{index + 1}",
            raw_value=float(value),
            engineering_value=float(value),
            units="raw",
            source=source,
        )
        for index, value in enumerate(frame.channels)
    ]
    readings.append(
        Reading(
            timestamp=timestamp,
            logged_at=logged_at,
            channel="bitmask",
            raw_value=float(frame.bitmask),
            engineering_value=float(frame.bitmask),
            units="mask",
            source=source,
        )
    )
    return readings


def run_snapshot_logger_loop(
    *,
    db_path: str | Path,
    snapshot_source: Callable[[], dict | None],
    rate_hz: float,
    batch_size: int,
    stop_event: Event,
    source: str = "transport",
) -> int:
    connection = connect_database(db_path)
    run_id = start_run(
        connection,
        started_at=time.time(),
        mode="transport",
        source=source,
        notes="Started by GUI ControlService snapshot logger",
    )
    interval_seconds = 1.0 / rate_hz if rate_hz > 0 else 0.0
    pending: list[Reading] = []
    next_frame_time = time.perf_counter()
    last_sequence: int | None = None

    try:
        while not stop_event.is_set():
            snapshot = snapshot_source()
            if snapshot is not None:
                sequence = snapshot.get("sequence_number")
                try:
                    sequence_number = int(sequence)
                except (TypeError, ValueError):
                    sequence_number = None
                if sequence_number is None or sequence_number != last_sequence:
                    pending.extend(snapshot_to_readings(snapshot, source=source))
                    last_sequence = sequence_number

            if len(pending) >= batch_size:
                insert_readings(connection, run_id, pending)
                connection.commit()
                pending.clear()

            if interval_seconds > 0:
                next_frame_time += interval_seconds
                stop_event.wait(max(0.0, next_frame_time - time.perf_counter()))
            else:
                stop_event.wait(0.001)
    finally:
        if pending:
            insert_readings(connection, run_id, pending)
            connection.commit()
        finish_run(connection, run_id, time.time())
        connection.close()

    return run_id


def insert_readings(connection, run_id: int, readings: Iterable[Reading]) -> int:
    rows = [
        (
            run_id,
            reading.timestamp,
            reading.logged_at,
            reading.channel,
            reading.raw_value,
            reading.engineering_value,
            reading.units,
            reading.source,
            reading.quality,
        )
        for reading in readings
    ]
    if not rows:
        return 0
    connection.executemany(
        """
        INSERT INTO readings (
            run_id,
            timestamp,
            logged_at,
            channel,
            raw_value,
            engineering_value,
            units,
            source,
            quality
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def run_smoke_logger(
    *,
    db_path: str | Path,
    rate_hz: float,
    frames: int | None,
    batch_size: int,
    stop_file: str | Path | None = None,
) -> int:
    connection = connect_database(db_path)
    run_id = start_run(
        connection,
        started_at=time.time(),
        mode="simulation",
        source="smoke",
        notes="Started by source.Python.Data.data_logger",
    )
    interval_seconds = 1.0 / rate_hz if rate_hz > 0 else 0.0
    pending: list[Reading] = []
    count = 0
    next_frame_time = time.perf_counter()
    stop_path = Path(stop_file) if stop_file is not None else None

    try:
        while (frames is None or count < frames) and not (
            stop_path is not None and stop_path.exists()
        ):
            pending.extend(frame_to_readings(generate_frame(count), source="smoke"))
            count += 1

            if len(pending) >= batch_size:
                insert_readings(connection, run_id, pending)
                connection.commit()
                pending.clear()

            if interval_seconds > 0:
                next_frame_time += interval_seconds
                time.sleep(max(0.0, next_frame_time - time.perf_counter()))
    except KeyboardInterrupt:
        pass
    finally:
        if pending:
            insert_readings(connection, run_id, pending)
            connection.commit()
        finish_run(connection, run_id, time.time())
        connection.close()

    return run_id


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Log Crocker telemetry into SQLite.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument(
        "--source",
        choices=("smoke",),
        default="smoke",
        help="Telemetry source. The first implementation supports smoke simulation.",
    )
    parser.add_argument("--rate-hz", type=float, default=20.0)
    parser.add_argument("--frames", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--stop-file", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_smoke_logger(
        db_path=args.db_path,
        rate_hz=args.rate_hz,
        frames=args.frames,
        batch_size=args.batch_size,
        stop_file=args.stop_file,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
