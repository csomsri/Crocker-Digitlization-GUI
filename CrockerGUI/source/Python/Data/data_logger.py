from __future__ import annotations

import argparse
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any, Callable

from source.Python.Data.pipeline_schema import (
    DEFAULT_DB_PATH,
    connect_database,
    finish_run,
    start_run,
)
from source.Python.Simulator.ZMQSimulator import EPOCH_OFFSET, SimulatorFrame, generate_frame

CHANNEL_NAMES = [f"ch{index}" for index in range(1, 13)] + ["main_magnet", "centering_beam"]
DEFAULT_CHANNEL_UNITS = ["engineering" for _ in CHANNEL_NAMES]


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

    reconstructed_bitmask = 0
    for index, channel in enumerate(channels[: len(CHANNEL_NAMES)]):
        if not isinstance(channel, dict):
            continue
        raw_value = float(channel.get("raw", 0.0))
        engineering_value = float(channel.get("actual", raw_value))
        units = str(channel.get("units", DEFAULT_CHANNEL_UNITS[index]))
        readings.append(
            Reading(
                timestamp=timestamp,
                logged_at=logged_at,
                channel=CHANNEL_NAMES[index],
                raw_value=raw_value,
                engineering_value=engineering_value,
                units=units,
                source=source,
                quality=str(channel.get("quality", "ok")),
            )
        )
        if bool(channel.get("on", False)):
            reconstructed_bitmask |= 1 << index
        if bool(channel.get("enabled", False)):
            reconstructed_bitmask |= 1 << (len(CHANNEL_NAMES) + index)

    bitmask = _snapshot_bitmask(snapshot, reconstructed_bitmask)

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
    readings.extend(_signal_readings(snapshot, timestamp, logged_at, source))
    readings.extend(_beam_readings(snapshot, timestamp, logged_at, source))
    readings.extend(_alarm_readings(snapshot, timestamp, logged_at, source))
    return readings


def _snapshot_bitmask(snapshot: dict, fallback: int) -> int:
    for key in ("bitmask", "raw_bitmask"):
        value = snapshot.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return fallback


def _beam_readings(
    snapshot: dict,
    timestamp: float,
    logged_at: float,
    source: str,
) -> list[Reading]:
    beam = snapshot.get("beam")
    if not isinstance(beam, dict):
        return []
    try:
        raw_value = float(beam.get("raw_value", 0.0))
        display_ua = float(beam.get("display_ua", beam.get("current_ua", 0.0)))
        full_scale_ua = float(beam.get("full_scale_ua", 0.0))
        range_index = float(beam.get("range_index", 0.0))
    except (TypeError, ValueError):
        return []
    quality = str(beam.get("quality", "ok"))
    return [
        Reading(
            timestamp=timestamp,
            logged_at=logged_at,
            channel="beam_current",
            raw_value=raw_value,
            engineering_value=display_ua,
            units="uA",
            source=source,
            quality=quality,
        ),
        Reading(
            timestamp=timestamp,
            logged_at=logged_at,
            channel="beam_full_scale",
            raw_value=full_scale_ua,
            engineering_value=full_scale_ua,
            units="uA",
            source=source,
            quality=quality,
        ),
        Reading(
            timestamp=timestamp,
            logged_at=logged_at,
            channel="beam_range_index",
            raw_value=range_index,
            engineering_value=range_index,
            units="index",
            source=source,
            quality=quality,
        ),
    ]


def _signal_readings(
    snapshot: dict,
    timestamp: float,
    logged_at: float,
    source: str,
) -> list[Reading]:
    signals = snapshot.get("signals")
    if not isinstance(signals, dict):
        return []
    units_by_signal = snapshot.get("signal_units")
    if not isinstance(units_by_signal, dict):
        units_by_signal = {}
    readings: list[Reading] = []
    for name, value in signals.items():
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        readings.append(
            Reading(
                timestamp=timestamp,
                logged_at=logged_at,
                channel=f"signal:{name}",
                raw_value=numeric,
                engineering_value=numeric,
                units=str(units_by_signal.get(name, "engineering")),
                source=source,
            )
        )
    return readings


def _alarm_readings(
    snapshot: dict,
    timestamp: float,
    logged_at: float,
    source: str,
) -> list[Reading]:
    alarms = snapshot.get("active_alarms", [])
    if not isinstance(alarms, list):
        alarms = []
    readings = [
        Reading(
            timestamp=timestamp,
            logged_at=logged_at,
            channel="alarm_count",
            raw_value=float(len(alarms)),
            engineering_value=float(len(alarms)),
            units="count",
            source=source,
        )
    ]
    for alarm in alarms:
        if not isinstance(alarm, dict):
            continue
        alarm_id = _alarm_channel_name(alarm)
        acknowledged = 1.0 if bool(alarm.get("acknowledged", False)) else 0.0
        active = 1.0 if bool(alarm.get("active", True)) else 0.0
        readings.append(
            Reading(
                timestamp=timestamp,
                logged_at=logged_at,
                channel=alarm_id,
                raw_value=active,
                engineering_value=acknowledged,
                units="alarm_state",
                source=source,
                quality=str(alarm.get("severity", "ok")).lower(),
            )
        )
    return readings


def _alarm_channel_name(alarm: dict[str, Any]) -> str:
    identifier = str(alarm.get("id") or alarm.get("code") or "alarm")
    return "alarm:" + "".join(char if char.isalnum() or char in {"_", "-", ":"} else "_" for char in identifier)


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
            units="engineering",
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
    last_snapshot_key: tuple[Any, ...] | None = None

    try:
        while not stop_event.is_set():
            snapshot = snapshot_source()
            if snapshot is not None:
                sequence = snapshot.get("sequence_number")
                try:
                    sequence_number = int(sequence)
                except (TypeError, ValueError):
                    sequence_number = None
                snapshot_key = (sequence_number, _snapshot_signature(snapshot))
                if snapshot_key != last_snapshot_key:
                    pending.extend(snapshot_to_readings(snapshot, source=source))
                    last_snapshot_key = snapshot_key

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


def _snapshot_signature(snapshot: dict) -> tuple[Any, ...]:
    channels = snapshot.get("channels", [])
    channel_signature: list[tuple[Any, ...]] = []
    if isinstance(channels, list):
        for channel in channels[: len(CHANNEL_NAMES)]:
            if not isinstance(channel, dict):
                channel_signature.append(("malformed",))
                continue
            channel_signature.append(
                (
                    channel.get("raw"),
                    channel.get("actual"),
                    channel.get("on"),
                    channel.get("enabled"),
                    channel.get("quality"),
                )
            )
    beam = snapshot.get("beam") if isinstance(snapshot.get("beam"), dict) else {}
    alarms = snapshot.get("active_alarms") if isinstance(snapshot.get("active_alarms"), list) else []
    signals = snapshot.get("signals") if isinstance(snapshot.get("signals"), dict) else {}
    alarm_signature = tuple(
        (
            alarm.get("id"),
            alarm.get("code"),
            alarm.get("channel"),
            alarm.get("active"),
            alarm.get("acknowledged"),
        )
        for alarm in alarms
        if isinstance(alarm, dict)
    )
    return (
        snapshot.get("bitmask"),
        snapshot.get("raw_bitmask"),
        tuple(channel_signature),
        (
            beam.get("raw_value"),
            beam.get("display_ua"),
            beam.get("current_ua"),
            beam.get("range_index"),
            beam.get("quality"),
        ),
        tuple(sorted(signals.items())),
        alarm_signature,
    )


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
