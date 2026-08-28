from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from source.Python.Services.CalibrationWorkbookService import (
    append_calibration_record,
    export_scaling_curves,
    import_scaling_curves,
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    scaling_path = root / "Exports" / "scaling_workbook_test.json"
    curves_path = root / "Exports" / "scaling_curves.test.xlsx"
    records_path = root / "Exports" / "calibration_records.test.xlsx"
    for path in (scaling_path, curves_path, records_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    try:
        scaling_path.write_text(
            json.dumps(
                {
                    "ch1": {
                        "label": "TC1",
                        "enabled": True,
                        "raw_to_eng": {"type": "curve", "points": [[0.0, 0.0], [1.0, 10.0]]},
                        "eng_to_raw": {"type": "curve", "points": [[0.0, 0.0], [10.0, 1.0]]},
                    }
                }
            ),
            encoding="utf-8",
        )

        assert export_scaling_curves(scaling_path, curves_path) == 1
        imported = import_scaling_curves(curves_path)
        assert imported["ch1"]["raw_to_eng"]["points"] == [[0.0, 0.0], [1.0, 10.0]]
        assert imported["ch1"]["eng_to_raw"]["points"] == [[0.0, 0.0], [10.0, 1.0]]

        assert append_calibration_record(records_path, scaling_path, operator_name="test", notes="round trip") == 1
        assert records_path.exists()
    finally:
        for path in (scaling_path, curves_path, records_path):
            try:
                path.unlink()
            except OSError:
                pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
