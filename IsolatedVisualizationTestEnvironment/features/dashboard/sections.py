"""Telemetry groups exposed by Crocker's decoded machine-state packet."""

import math

SECTIONS = (
    ("channels", "Trim channels", 14),
    ("extraction", "Extraction", 6),
    ("extraction_angles", "Extraction angles", 6),
    ("source", "Source", 6),
    ("transport", "Transport", 10),
    ("vacuum", "Vacuum", 5),
    ("rf_power_kv", "RF power", 1),
    ("beam_current", "Beam current", 1),
)


def readings(packet, key, count):
    raw = packet.get(key)
    if raw is None:
        return ()
    values = (raw,) if count == 1 else tuple(raw[:count])
    if any(not math.isfinite(value) or abs(value) > 3.4e38 for value in values):
        return ()
    return values
