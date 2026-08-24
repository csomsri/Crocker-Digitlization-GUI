from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CROCKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CROCKER_ROOT))

from PySide6.QtWidgets import QApplication

from python.app.Configuration.ScalingPage import ScalingPage


def main() -> int:
    app = QApplication.instance() or QApplication([])
    page = ScalingPage(lambda: None)

    legacy_array = {
        "raw_to_eng_gain": [2.0] * 14,
        "raw_to_eng_offset": [1.0] * 14,
        "eng_to_raw_gain": [0.5] * 14,
        "eng_to_raw_offset": [-0.5] * 14,
        "enabled": [True] * 14,
    }
    normalized = page._normalize_scaling(legacy_array)
    assert normalized["ch1"]["enabled"] is True
    assert normalized["ch1"]["raw_to_eng"]["type"] == "linear"
    assert normalized["ch1"]["raw_to_eng"]["gain"] == 2.0
    assert normalized["main_magnet"]["eng_to_raw"]["offset"] == -0.5

    old_style_curve = {
        "ch1": {
            "enabled": True,
            "raw_to_eng": {
                "type": "curve",
                "points": [[0.0, 0.0], [1.0, 10.0], [2.0, 20.0]],
            },
            "eng_to_raw": {
                "type": "curve",
                "points": [[0.0, 0.0], [10.0, 1.0], [20.0, 2.0]],
            },
        }
    }
    normalized = page._normalize_scaling(old_style_curve)
    assert normalized["ch1"]["raw_to_eng"]["type"] == "curve"
    assert normalized["ch1"]["raw_to_eng"]["points"][1] == [1.0, 10.0]
    assert page._validation_errors(normalized) == []

    page._apply_scaling_to_table(normalized)
    round_trip = page._read_scaling_from_table()
    assert round_trip["ch1"]["raw_to_eng"]["type"] == "curve"
    assert round_trip["ch1"]["raw_to_eng"]["points"][2] == [2.0, 20.0]

    page._edit_transform(0, "eng_to_raw")
    assert page.editor_title.text() == "TC1 CALIBRATION"
    eng_widgets = page.direction_widgets["eng_to_raw"]
    for button in eng_widgets["type_group"].buttons():
        if button.property("transformType") == "curve":
            button.click()
            break
    eng_widgets["points_table"].item(1, 0).setText("11.0")
    eng_widgets["points_table"].item(1, 1).setText("1.1")
    round_trip = page._read_scaling_from_table()
    assert round_trip["ch1"]["eng_to_raw"]["type"] == "curve"
    assert round_trip["ch1"]["eng_to_raw"]["points"][1] == [11.0, 1.1]
    eng_widgets["sample_spin"].setValue(11.0)
    assert eng_widgets["result_label"].text() == "-> 1.1"

    print("Scaling page curve test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
