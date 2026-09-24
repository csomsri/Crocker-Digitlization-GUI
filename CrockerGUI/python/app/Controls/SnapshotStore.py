"""Named, immutable JSON records in a transactional SQLite snapshot library."""
from contextlib import closing
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3


CATEGORY_FIELDS = {
    "Source": ("source",),
    "Extraction": ("extraction", "extraction_angles"),
    "Beam Transport": ("transport",),
    "Vacuum": ("vacuum",),
    "RF": ("rf_power_kv",),
    "Beam": ("beam_current", "beam_range_idx", "beam"),
    "Mapped Signals": ("signals", "signal_units"),
}


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def make_snapshot(telemetry, channel_names, mode):
    """Keep every telemetry field; category views never substitute absent readings."""
    telemetry = json_safe(telemetry)
    categories = {"Trim Coils": {}, "Auxiliary Magnets": {}}
    for index, channel in enumerate(telemetry.get("channels", [])[:len(channel_names)]):
        category = "Trim Coils" if index < 12 else "Auxiliary Magnets"
        categories[category][channel_names[index]] = channel.get("actual")
    for category, fields in CATEGORY_FIELDS.items():
        categories[category] = {key: telemetry.get(key) for key in fields}
    return dict(schema_version=1, captured_at=datetime.now(timezone.utc).isoformat(),
                mode=mode, telemetry=telemetry, categories=categories)


def target_updates(record, selected, channel_names, maximum):
    """Validate all recalled targets before changing any UI state."""
    updates = {}
    for category in ("Trim Coils", "Auxiliary Magnets"):
        if category not in selected:
            continue
        expected = channel_names[:12] if category == "Trim Coils" else channel_names[12:]
        values = record["categories"].get(category, {})
        for name in expected:
            value = values.get(name)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError(f"{name} has no valid captured value.")
            if not 0 <= value <= maximum:
                raise ValueError(f"{name}: {value:g} is outside the target range 0–{maximum:g} A.")
            updates[channel_names.index(name)] = float(value)
    return updates


class SnapshotStore:
    def __init__(self, path):
        self.path = Path(path)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute('''CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
            captured_at TEXT NOT NULL, payload TEXT NOT NULL)''')
        connection.commit()
        return connection

    def next_name(self):
        names = {row[1] for row in self.list()}
        index = 1
        while f"Snapshot{index}" in names:
            index += 1
        return f"Snapshot{index}"

    def save(self, record, name=""):
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            name = name.strip()
            if not name:
                names = {row[0] for row in connection.execute("SELECT name FROM snapshots")}
                index = 1
                while f"Snapshot{index}" in names:
                    index += 1
                name = f"Snapshot{index}"
            saved = dict(record, name=name)
            try:
                cursor = connection.execute(
                    "INSERT INTO snapshots(name,captured_at,payload) VALUES (?,?,?)",
                    (name, saved["captured_at"], json.dumps(saved, allow_nan=False)))
            except sqlite3.IntegrityError as exc:
                raise ValueError("That name already exists. Choose another name.") from exc
            return cursor.lastrowid

    def list(self):
        with closing(self._connect()) as connection:
            return connection.execute(
                "SELECT id,name,captured_at FROM snapshots ORDER BY captured_at DESC,id DESC").fetchall()

    def load(self, identity):
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT payload FROM snapshots WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise ValueError("Snapshot no longer exists.")
        return json.loads(row[0])
