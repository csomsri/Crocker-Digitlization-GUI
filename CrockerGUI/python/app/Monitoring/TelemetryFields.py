"""Confirmed packet groups. Numbered labels deliberately avoid guessed device names."""
import math


def group(label, field, count):
    return [(f"{label} {index + 1}", field, index, "raw") for index in range(count)]


MONITOR_FIELDS = {
    "Beam Transport Monitoring": group("Transport", "transport", 10),
    "Beam Source & Extraction": [*group("Source", "source", 6),
                                 *group("Extraction", "extraction", 6),
                                 *group("Extraction angle", "extraction_angles", 6)],
    "Vacuum / Beam Monitoring": [*group("Vacuum", "vacuum", 5),
                                  ("Beam detector", "beam_current", None, "raw"),
                                  ("Beam current", "beam", "display_ua", "µA"),
                                  ("Beam range index", "beam_range_idx", None, "index")],
    "RF Power Monitoring": [("RF reading", "rf_power_kv", None, "raw")],
}


def reading(snapshot, spec):
    _, field, index, _ = spec
    value = snapshot.get(field)
    if field == "beam" and (not isinstance(value, dict) or value.get("quality") != "ok"
                            or snapshot.get("beam_current") is None):
        return None
    if index is not None:
        if isinstance(index, int):
            value = value[index] if isinstance(value, (list, tuple)) and len(value) > index else None
        else:
            value = value.get(index) if isinstance(value, dict) else None
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        return None
    return float(value)
