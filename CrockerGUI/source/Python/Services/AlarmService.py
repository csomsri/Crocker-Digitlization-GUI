from __future__ import annotations

import json
import sqlite3
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from source.Python.Data.pipeline_schema import connect_database


@dataclass(frozen=True)
class AlarmState:
    id: str
    timestamp: float
    severity: str
    channel: str
    code: str
    message: str
    active: bool
    acknowledged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AlarmService:
    def __init__(self, config_path: str | Path, db_path: str | Path | None = None) -> None:
        self.config_path = Path(config_path)
        self.db_path = Path(db_path) if db_path is not None else None
        self._lock = Lock()
        self._enabled = True
        self._log_events = True
        self._rf_dkv = 1.0
        self._rf_window_s = 3.0
        self._vac_factor = 2.0
        self._vac_window_s = 3.0
        self._rf_channel = "rf_kv"
        self._vac_channels = ["vac1", "vac2"]
        self._windows: dict[str, deque[tuple[float, float]]] = {}
        self._active: dict[str, AlarmState] = {}
        self._acknowledged: set[str] = set()
        self.reload()

    def reload(self) -> None:
        if not self.config_path.exists():
            return
        with self.config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("alarm config must contain a JSON object")
        with self._lock:
            self._enabled = bool(data.get("enabled", self._enabled))
            self._log_events = bool(data.get("log_events", self._log_events))
            self._rf_dkv = float(data.get("rf_dkv", self._rf_dkv))
            self._rf_window_s = max(0.1, float(data.get("rf_window_s", self._rf_window_s)))
            self._vac_factor = max(1.0, float(data.get("vac_factor", self._vac_factor)))
            self._vac_window_s = max(0.1, float(data.get("vac_window_s", self._vac_window_s)))
            self._rf_channel = str(data.get("rf_channel", self._rf_channel))
            vac_channels = data.get("vac_channels", self._vac_channels)
            if isinstance(vac_channels, list):
                self._vac_channels = [str(channel) for channel in vac_channels]

    def update(self, snapshot: dict[str, Any] | None, beam_state: dict[str, Any] | None = None) -> list[AlarmState]:
        timestamp = float((snapshot or {}).get("timestamp") or time.time())
        if not self._enabled:
            with self._lock:
                self._clear_missing(set(), timestamp)
                return []

        values = self._values_from_snapshot(snapshot, beam_state)
        next_active: dict[str, AlarmState] = {}

        with self._lock:
            rf_value = values.get(self._rf_channel)
            if rf_value is not None and self._delta_exceeded(self._rf_channel, timestamp, rf_value, self._rf_window_s, self._rf_dkv):
                alarm = AlarmState(
                    id="rf_delta",
                    timestamp=timestamp,
                    severity="Warning",
                    channel=self._rf_channel,
                    code="RF_DELTA",
                    message=f"RF changed by more than {self._rf_dkv:g} kV",
                    active=True,
                    acknowledged="rf_delta" in self._acknowledged,
                )
                next_active[alarm.id] = alarm

            for channel in self._vac_channels:
                value = values.get(channel)
                if value is None:
                    continue
                alarm_id = f"vac_factor:{channel}"
                if self._factor_exceeded(channel, timestamp, value, self._vac_window_s, self._vac_factor):
                    alarm = AlarmState(
                        id=alarm_id,
                        timestamp=timestamp,
                        severity="Warning",
                        channel=channel,
                        code="VAC_FACTOR",
                        message=f"{channel} changed by more than factor {self._vac_factor:g}",
                        active=True,
                        acknowledged=alarm_id in self._acknowledged,
                    )
                    next_active[alarm.id] = alarm

            self._record_transitions(self._active, next_active, timestamp)
            self._active = next_active
            return list(self._active.values())

    def acknowledge(self, alarm_id: str | None = None) -> None:
        with self._lock:
            if alarm_id:
                self._acknowledged.add(alarm_id)
            else:
                self._acknowledged.update(self._active)
            self._active = {
                key: AlarmState(**{**alarm.to_dict(), "acknowledged": key in self._acknowledged})
                for key, alarm in self._active.items()
            }

    def active(self) -> list[AlarmState]:
        with self._lock:
            return list(self._active.values())

    def active_dicts(self) -> list[dict[str, Any]]:
        return [alarm.to_dict() for alarm in self.active()]

    def config_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "log_events": self._log_events,
                "rf_dkv": self._rf_dkv,
                "rf_window_s": self._rf_window_s,
                "vac_factor": self._vac_factor,
                "vac_window_s": self._vac_window_s,
                "rf_channel": self._rf_channel,
                "vac_channels": list(self._vac_channels),
            }

    def _values_from_snapshot(self, snapshot: dict[str, Any] | None, beam_state: dict[str, Any] | None) -> dict[str, float]:
        values: dict[str, float] = {}
        if beam_state:
            values["beam_current"] = float(beam_state.get("display_ua", beam_state.get("current_ua", 0.0)))
        if not snapshot:
            return values
        channels = snapshot.get("channels", [])
        if isinstance(channels, list):
            for index, channel in enumerate(channels):
                if not isinstance(channel, dict):
                    continue
                value = float(channel.get("actual", channel.get("raw", 0.0)))
                values[f"ch{index + 1}"] = value
                if index == 12:
                    values["main_magnet"] = value
                elif index == 13:
                    values["centering_beam"] = value
                    values.setdefault("beam_current", value)
        extra = snapshot.get("signals")
        if isinstance(extra, dict):
            for key, value in extra.items():
                try:
                    values[str(key)] = float(value)
                except (TypeError, ValueError):
                    pass
        return values

    def _delta_exceeded(self, key: str, timestamp: float, value: float, window_s: float, limit: float) -> bool:
        window = self._push_window(key, timestamp, value, window_s)
        if len(window) < 2:
            return False
        return abs(value - window[0][1]) >= limit

    def _factor_exceeded(self, key: str, timestamp: float, value: float, window_s: float, factor: float) -> bool:
        window = self._push_window(key, timestamp, value, window_s)
        if len(window) < 2:
            return False
        baseline = abs(window[0][1])
        current = abs(value)
        if baseline <= 0.0:
            return False
        ratio = max(current / baseline, baseline / max(current, 1.0e-30))
        return ratio >= factor

    def _push_window(self, key: str, timestamp: float, value: float, window_s: float) -> deque[tuple[float, float]]:
        window = self._windows.setdefault(key, deque())
        window.append((timestamp, value))
        cutoff = timestamp - window_s
        while len(window) > 1 and window[0][0] < cutoff:
            window.popleft()
        return window

    def _clear_missing(self, next_ids: set[str], timestamp: float) -> None:
        next_active = {key: alarm for key, alarm in self._active.items() if key in next_ids}
        self._record_transitions(self._active, next_active, timestamp)
        self._active = next_active

    def _record_transitions(
        self,
        previous: dict[str, AlarmState],
        current: dict[str, AlarmState],
        timestamp: float,
    ) -> None:
        if not self._log_events or self.db_path is None:
            return
        opened = [alarm for key, alarm in current.items() if key not in previous]
        cleared = [alarm for key, alarm in previous.items() if key not in current]
        if not opened and not cleared:
            return
        try:
            connection = connect_database(self.db_path)
            run_id = self._latest_run_id(connection, timestamp)
            rows = [
                (run_id, alarm.timestamp, alarm.code, alarm.channel, "active", None, None, alarm.message)
                for alarm in opened
            ]
            rows.extend(
                (run_id, timestamp, alarm.code, alarm.channel, "cleared", None, None, alarm.message)
                for alarm in cleared
            )
            connection.executemany(
                """
                INSERT INTO alarm_events (
                    run_id,
                    timestamp,
                    alarm_name,
                    channel,
                    state,
                    measured_value,
                    threshold_value,
                    message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            connection.commit()
            connection.close()
        except sqlite3.Error:
            return

    def _latest_run_id(self, connection: sqlite3.Connection, timestamp: float) -> int:
        row = connection.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        if row is not None:
            return int(row["id"])
        cursor = connection.execute(
            "INSERT INTO runs (started_at, mode, source, notes) VALUES (?, ?, ?, ?)",
            (timestamp, "alarm", "alarm-service", "Created for alarm events"),
        )
        connection.commit()
        return int(cursor.lastrowid)
