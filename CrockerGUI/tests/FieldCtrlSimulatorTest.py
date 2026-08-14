"""
Field Ctrl page simulator integration test.

Run from the repository root after building CycloViz:
    python CrockerGUI/tests/FieldCtrlSimulatorTest.py
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

from python.app.Controls.FieldCtrlPage import FieldCtrlPage


def main() -> int:
    app = QApplication.instance() or QApplication([])
    page = FieldCtrlPage(lambda: None, backend_mode="simulation")
    target = 125.0

    try:
        if not page.backend_available or page.backend is None:
            raise RuntimeError("FieldCtrlPage did not start the CycloViz simulator backend")

        if not page.toggles_locked or page.on_buttons[0].isEnabled():
            raise RuntimeError("FieldCtrlPage toggle controls should start locked")
        page.toggle_lock_button.click()
        if page.toggles_locked or not page.on_buttons[0].isEnabled():
            raise RuntimeError("FieldCtrlPage toggle controls did not unlock")
        page.toggle_lock_button.click()
        if not page.toggles_locked or page.enable_buttons[0].isEnabled():
            raise RuntimeError("FieldCtrlPage toggle controls did not lock")

        page._select_channel(0)
        page.target_input.setValue(target)
        page.on_buttons[0].setChecked(True)
        page.enable_buttons[0].setChecked(False)
        disabled_first = float(page.backend.LatestSnapshot()["channels"][0]["actual"])
        if not page._apply_selected_command():
            raise RuntimeError("FieldCtrlPage disabled Apply command returned false")
        disabled_deadline = time.monotonic() + 0.35
        while time.monotonic() < disabled_deadline:
            app.processEvents()
            page._tick_feedback()
            time.sleep(0.05)
        disabled_channel = page.backend.LatestSnapshot()["channels"][0]
        disabled_last = float(disabled_channel["actual"])
        if bool(disabled_channel["enabled"]):
            raise RuntimeError("Apply drove a channel while Enable was off")
        if abs(disabled_last - disabled_first) > 0.01:
            raise RuntimeError(
                "Apply moved a selected channel while Enable was off: "
                f"first={disabled_first:.3f}, last={disabled_last:.3f}"
            )

        page.on_buttons[0].setChecked(True)
        page.enable_buttons[0].setChecked(True)
        page.target_values[1] = 900.0
        page.on_buttons[1].setChecked(True)
        page.enable_buttons[1].setChecked(True)

        first = float(page.backend.LatestSnapshot()["channels"][0]["actual"])
        second_first = float(page.backend.LatestSnapshot()["channels"][1]["actual"])
        if not page._apply_selected_command():
            raise RuntimeError("FieldCtrlPage Apply command returned false")

        samples: list[float] = []
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            app.processEvents()
            snapshot = page.backend.LatestSnapshot()
            actual = float(snapshot["channels"][0]["actual"])
            samples.append(actual)
            page._tick_feedback()
            if abs(target - actual) < abs(target - first) * 0.55:
                break
            time.sleep(0.05)

        last = samples[-1] if samples else first
        if last <= first:
            raise RuntimeError(f"UI simulator command did not increase actual: first={first:.3f}, last={last:.3f}")
        if abs(target - last) >= abs(target - first):
            raise RuntimeError(f"UI simulator did not move toward target: first={first:.3f}, last={last:.3f}")

        second_channel = page.backend.LatestSnapshot()["channels"][1]
        second_last = float(second_channel["actual"])
        if bool(second_channel["enabled"]):
            raise RuntimeError("Selected Apply enabled an unapplied second channel")
        if abs(second_last - second_first) > 0.01:
            raise RuntimeError(
                "Selected Apply moved an unapplied second channel: "
                f"first={second_first:.3f}, last={second_last:.3f}"
            )

        if not page.history[0]:
            raise RuntimeError("Time-domain plot history did not receive samples")
        _, plotted_actual, plotted_target, plotted_error = page.history[0][-1]
        if abs(plotted_actual - page.actual_values[0]) > 0.01:
            raise RuntimeError("Time-domain plot actual sample is out of sync with page state")

        print(
            "Field Ctrl UI simulator test passed: "
            f"first={first:.3f}, last={last:.3f}, target={target:.3f}, "
            f"plot_actual={plotted_actual:.3f}, plot_target={plotted_target:.3f}, "
            f"plot_error={plotted_error:.3f}, converged={page.converged[0]}"
        )
        return 0
    finally:
        page.stop_backend()


if __name__ == "__main__":
    raise SystemExit(main())
