from __future__ import annotations

import json
import operator
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Callable


CHANNEL_KEYS = [f"ch{index}" for index in range(1, 13)] + ["main_magnet", "centering_beam"]
OPERATORS: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


@dataclass(frozen=True)
class InterlockRule:
    id: str
    signal: str
    operator: str
    limit: float
    severity: str
    code: str
    message: str
    interlock_channels: tuple[str, ...]
    enabled: bool = True


@dataclass(frozen=True)
class InterlockEvent:
    id: str
    timestamp: float
    severity: str
    channel: str
    code: str
    message: str
    active: bool = True
    acknowledged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InterlockService:
    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)
        self._lock = Lock()
        self._enabled = False
        self._rules: list[InterlockRule] = []
        self._active_channels: set[str] = set()
        self.reload()

    def reload(self) -> None:
        if not self.config_path.exists():
            return
        with self.config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("interlock config must contain a JSON object")
        rules = data.get("rules", [])
        if not isinstance(rules, list):
            raise ValueError("interlock config must contain a rules list")
        parsed: list[InterlockRule] = []
        for entry in rules:
            if not isinstance(entry, dict):
                continue
            rule_id = str(entry.get("id", "")).strip()
            signal = str(entry.get("signal", "")).strip()
            op = str(entry.get("operator", ">")).strip()
            channels = entry.get("interlock_channels", [])
            if isinstance(channels, str):
                channels = [channels]
            if not rule_id or not signal or op not in OPERATORS or not isinstance(channels, list):
                continue
            parsed.append(
                InterlockRule(
                    id=rule_id,
                    signal=signal,
                    operator=op,
                    limit=float(entry.get("limit", 0.0)),
                    severity=str(entry.get("severity", "Critical")),
                    code=str(entry.get("code", rule_id.upper())),
                    message=str(entry.get("message", rule_id)),
                    interlock_channels=tuple(str(channel).strip() for channel in channels if self._channel_index(str(channel)) is not None),
                    enabled=bool(entry.get("enabled", True)),
                )
            )
        with self._lock:
            self._enabled = bool(data.get("enabled", self._enabled))
            self._rules = parsed

    def evaluate(self, snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
        if snapshot is None:
            with self._lock:
                self._active_channels = set()
            return []
        with self._lock:
            enabled = self._enabled
            rules = list(self._rules)
        if not enabled:
            with self._lock:
                self._active_channels = set()
            return []

        values = self._values(snapshot)
        channels = snapshot.get("channels", [])
        events: list[dict[str, Any]] = []
        active_channels: set[str] = set()
        timestamp = float(snapshot.get("timestamp") or time.time())
        for rule in rules:
            value = values.get(rule.signal)
            if not rule.enabled or value is None:
                continue
            if not OPERATORS[rule.operator](value, rule.limit):
                continue
            for channel_key in rule.interlock_channels:
                index = self._channel_index(channel_key)
                if index is None or not isinstance(channels, list) or index >= len(channels) or not isinstance(channels[index], dict):
                    continue
                channels[index]["interlocked"] = True
                channels[index]["quality"] = "interlocked"
                channels[index]["status"] = "Interlocked"
                active_channels.add(channel_key)
                events.append(
                    InterlockEvent(
                        id=f"interlock:{rule.id}:{channel_key}",
                        timestamp=timestamp,
                        severity=rule.severity,
                        channel=channel_key,
                        code=rule.code,
                        message=f"{rule.message}: {rule.signal}={value:g} {rule.operator} {rule.limit:g}",
                    ).to_dict()
                )
        with self._lock:
            self._active_channels = active_channels
        return events

    def filter_command(self, command: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            active_channels = set(self._active_channels)
        channels = command.get("channels")
        if not active_channels or not isinstance(channels, list):
            return command
        filtered = dict(command)
        filtered_channels = [dict(channel) if isinstance(channel, dict) else channel for channel in channels]
        for channel_key in active_channels:
            index = self._channel_index(channel_key)
            if index is None or index >= len(filtered_channels) or not isinstance(filtered_channels[index], dict):
                continue
            filtered_channels[index]["on"] = False
            filtered_channels[index]["enabled"] = False
            filtered_channels[index]["interlocked"] = True
        filtered["channels"] = filtered_channels
        filtered["interlock_filtered"] = True
        return filtered

    def _values(self, snapshot: dict[str, Any]) -> dict[str, float]:
        values: dict[str, float] = {}
        signals = snapshot.get("signals")
        if isinstance(signals, dict):
            for key, value in signals.items():
                try:
                    values[str(key)] = float(value)
                except (TypeError, ValueError):
                    pass
        channels = snapshot.get("channels", [])
        if isinstance(channels, list):
            for index, channel in enumerate(channels[: len(CHANNEL_KEYS)]):
                if not isinstance(channel, dict):
                    continue
                try:
                    value = float(channel.get("actual", channel.get("raw", 0.0)))
                except (TypeError, ValueError):
                    continue
                values[CHANNEL_KEYS[index]] = value
        return values

    def _channel_index(self, channel: str) -> int | None:
        text = channel.strip().lower()
        if text.startswith("ch") and text[2:].isdigit():
            index = int(text[2:]) - 1
            return index if 0 <= index < len(CHANNEL_KEYS) else None
        if text in CHANNEL_KEYS:
            return CHANNEL_KEYS.index(text)
        return None
