"""
Assisted Tuning page simulator integration test.

Run from the repository root after building CycloViz:
    python CrockerGUI/tests/OptimizationPageTest.py
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

from python.app.Automation.OptimizationPage import OptimizationPage


def main() -> int:
    app = QApplication.instance() or QApplication([])
    page = OptimizationPage(lambda: None, backend_mode="simulation")

    try:
        if not page.backend_available or page.backend is None:
            raise RuntimeError("Assisted tuning page did not start the CycloViz simulator backend")

        page.channel_select.setCurrentIndex(0)
        page.target_actual_input.setValue(40.0)
        page.max_step_input.setValue(10.0)
        page.observe_seconds_input.setValue(0.5)
        page.output_on_check.setChecked(True)
        page.control_enabled_check.setChecked(True)
        page.dry_run_check.setChecked(False)
        page.automated_trials_check.setChecked(True)
        if page.auto_approve_check.isChecked():
            raise RuntimeError("Automatic trial approval must be off by default")
        page.arm_button.setChecked(True)

        if page.pending_candidate is None:
            raise RuntimeError(f"Trial runner did not automatically suggest a candidate: {page.last_message}")

        candidate = page.pending_candidate.command
        allowed_step = page.pending_candidate.allowed_step
        if abs(candidate - page.command_values[0]) > allowed_step + 1.0e-9:
            raise RuntimeError("Generated candidate exceeded its adaptive range")

        wide_range = page.optimizer.adaptive_step(200.0, 10.0, 0.5)
        narrow_range = page.optimizer.adaptive_step(4.0, 10.0, 0.5)
        if wide_range != 10.0 or narrow_range != 4.0:
            raise RuntimeError(
                f"Adaptive trial range was not based directly on error: {wide_range=}, {narrow_range=}"
            )

        page._approve_trial()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not page.trials:
            app.processEvents()
            page._tick_feedback()
            time.sleep(0.05)

        if not page.trials:
            raise RuntimeError("Approved optimization trial did not complete")
        trial = page.trials[-1]
        if trial["channel_index"] != 0:
            raise RuntimeError("Assisted tuning trial logged the wrong channel")
        if page.trial_table.rowCount() < 1:
            raise RuntimeError("Assisted tuning trial table did not receive a row")
        if page.pending_candidate is None:
            raise RuntimeError("Next assisted trial was not prepared automatically")
        page.auto_approve_check.setChecked(True)
        if page.active_trial is None or page.pending_candidate is not None:
            raise RuntimeError("Automatic approval did not start the waiting trial")

        print(
            "Assisted tuning page simulator test passed: "
            f"candidate={float(trial['candidate']):.3f}, "
            f"actual={float(trial['actual']):.3f}, score={float(trial['score']):.3f}, "
            f"safe={trial['safe']}"
        )
        return 0
    finally:
        page.stop_backend()


if __name__ == "__main__":
    raise SystemExit(main())
