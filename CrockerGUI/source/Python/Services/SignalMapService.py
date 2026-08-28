from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Any


CHANNEL_KEYS = [f"ch{index}" for index in range(1, 13)] + ["main_magnet", "centering_beam"]


@dataclass(frozen=True)
class SignalDefinition:
    name: str
    channel: str
    units: str = "engineering"
    device_class: str = "general"
    source_field: str = "actual"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SignalMapService:
    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)
        self._lock = Lock()
        self._signals: list[SignalDefinition] = []
        self.reload()

    def reload(self) -> None:
        if not self.config_path.exists():
            return
        with self.config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("signal map config must contain a JSON object")
        signals = data.get("signals", [])
        if not isinstance(signals, list):
            raise ValueError("signal map config must contain a signals list")
        parsed: list[SignalDefinition] = []
        for entry in signals:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip()
            channel = str(entry.get("channel", "")).strip()
            if not name or self._channel_index(channel) is None:
                continue
            parsed.append(
                SignalDefinition(
                    name=name,
                    channel=channel,
                    units=str(entry.get("units", "engineering")),
                    device_class=str(entry.get("device_class", "general")),
                    source_field=str(entry.get("source_field", "actual")),
                )
            )
        with self._lock:
            self._signals = parsed

    def definitions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [signal.to_dict() for signal in self._signals]

    def enrich_snapshot(self, snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
        if snapshot is None:
            return None
        channels = snapshot.get("channels", [])
        if not isinstance(channels, list):
            return snapshot

        with self._lock:
            definitions = list(self._signals)

        signals = snapshot.get("signals")
        if not isinstance(signals, dict):
            signals = {}
        signal_units = snapshot.get("signal_units")
        if not isinstance(signal_units, dict):
            signal_units = {}
        signal_classes = snapshot.get("signal_classes")
        if not isinstance(signal_classes, dict):
            signal_classes = {}

        for definition in definitions:
            index = self._channel_index(definition.channel)
            if index is None or index >= len(channels) or not isinstance(channels[index], dict):
                continue
            value = channels[index].get(definition.source_field, channels[index].get("actual", channels[index].get("raw", 0.0)))
            try:
                signals[definition.name] = float(value)
            except (TypeError, ValueError):
                continue
            signal_units[definition.name] = definition.units
            signal_classes[definition.name] = definition.device_class

        snapshot["signals"] = signals
        snapshot["signal_units"] = signal_units
        snapshot["signal_classes"] = signal_classes
        return snapshot

    def _channel_index(self, channel: str) -> int | None:
        text = channel.strip().lower()
        if text.startswith("ch") and text[2:].isdigit():
            index = int(text[2:]) - 1
            return index if 0 <= index < len(CHANNEL_KEYS) else None
        if text in CHANNEL_KEYS:
            return CHANNEL_KEYS.index(text)
        return None
