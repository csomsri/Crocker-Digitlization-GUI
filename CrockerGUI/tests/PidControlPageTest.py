"""
PID Control page simulator integration test.

Run from the repository root after building CycloViz:
    python CrockerGUI/tests/PidControlPageTest.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
CROCKER_ROOT = REPO_ROOT / "CrockerGUI"

for candidate in (
    CROCKER_ROOT,
    CROCKER_ROOT / "Debug",
    CROCKER_ROOT / "Release",
    CROCKER_ROOT / "build" / "Debug",
    CROCKER_ROOT / "build" / "Release",
):
    sys.path.insert(0, str(candidate))

from PySide6.QtWidgets import QApplication

from python.app.Automation.PidControlPage import PidControlPage


def main() -> int:
    app = QApplication.instance() or QApplication([])
    page = PidControlPage(lambda: None, backend_mode="simulation")
    setpoint = 75.0

    try:
        if not page.backend_available or page.backend is None:
            raise RuntimeError("PidControlPage did not start the CycloViz simulator backend")

        page.channel_select.setCurrentIndex(1)
        page.setpoint_input.setValue(setpoint)
        page.kp_input.setValue(1.0)
        page.ki_input.setValue(0.05)
        page.kd_input.setValue(0.0)
        page.output_on_check.setChecked(True)
        page.control_enabled_check.setChecked(True)
        page.dry_run_check.setChecked(False)
        page.arm_button.setChecked(True)
        page.enable_button.setChecked(True)

        first = float(page.backend.LatestSnapshot()["channels"][1]["actual"])
        deadline = time.monotonic() + 4.0
        samples: list[float] = []
        while time.monotonic() < deadline:
            app.processEvents()
            page._tick_feedback()
            actual = float(page.backend.LatestSnapshot()["channels"][1]["actual"])
            samples.append(actual)
            if abs(setpoint - actual) < abs(setpoint - first) * 0.65:
                break
            time.sleep(0.05)

        last = samples[-1] if samples else first
        if abs(setpoint - last) >= abs(setpoint - first):
            raise RuntimeError(
                f"PID control did not move channel 1 toward setpoint: first={first:.3f}, last={last:.3f}"
            )
        if not page.history:
            raise RuntimeError("PID plot history did not receive samples")

        print(
            "PID Control page simulator test passed: "
            f"first={first:.3f}, last={last:.3f}, setpoint={setpoint:.3f}, "
            f"command={page.command_values[1]:.3f}"
        )
        return 0
    finally:
        page.stop_backend()


if __name__ == "__main__":
    raise SystemExit(main())
