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
    control_index = 2

    try:
        if not page.backend_available or page.backend is None:
            raise RuntimeError("PidControlPage did not start the CycloViz simulator backend")

        page.channel_select.setCurrentIndex(1)
        page.setpoint_input.setValue(setpoint)
        page.open_tuner_button.click()
        if page.page_stack.currentWidget() is not page.tuner_page:
            raise RuntimeError("Optimized Tuner did not open from PID Control")
        if page.tuner_channel.currentIndex() != 1 or page.tuner_target.value() != setpoint:
            raise RuntimeError("Optimized Tuner did not inherit PID channel and target")
        if page.tuner_viewport.layout() is not None:
            raise RuntimeError("Optimized Tuner visualization viewport should remain empty")
        if page.apply_tuned_gains_button.isEnabled():
            raise RuntimeError("Unvalidated tuner gains must not be applicable to PID Control")
        for combo in (page.tuner_channel, page.tuner_profile, page.tuner_safety_profile):
            if not combo.property("stablePopup"):
                raise RuntimeError(f"{combo.objectName()} does not preserve its native clickable popup")
        page.tuner_safety_profile.setCurrentIndex(1)
        if page.tuner_safety_profile.currentText() != "Approved hardware profile":
            raise RuntimeError("Safety-profile dropdown did not accept a selection")
        page.tuner_safety_profile.setCurrentIndex(0)

        page.tuner_target.setValue(30.0)
        page.tuner_duration.setValue(0.5)
        page.prepare_tuning_button.click()
        proposal_deadline = time.monotonic() + 20.0
        while page.tuning_candidate is None and time.monotonic() < proposal_deadline:
            app.processEvents()
            page._tick_feedback()
            time.sleep(0.02)
        if page.tuning_candidate is None:
            raise RuntimeError(f"BoTorch UI candidate was not prepared: {page.tuner_status.text()}")

        page.run_tuning_trial_button.click()
        trial_deadline = time.monotonic() + 5.0
        while not page.tuning_results and time.monotonic() < trial_deadline:
            app.processEvents()
            page._tick_feedback()
            time.sleep(0.02)
        if not page.tuning_results:
            raise RuntimeError(f"BoTorch UI trial did not complete: {page.tuner_status.text()}")
        page.stop_tuning_button.click()
        page.approve_gains_button.click()
        if not page.apply_tuned_gains_button.isEnabled():
            raise RuntimeError("Validated best tuner gains were not made available to PID Control")
        expected = page.tuning_optimizer.best_result.candidate
        page.apply_tuned_gains_button.click()
        if page.pid_enabled:
            raise RuntimeError("Applying tuned gains must not enable PID automatically")
        if abs(page.kp_input.value() - expected.kp) > 0.011:
            raise RuntimeError("Best BoTorch gains were not transferred to PID Control")

        page.close_tuner_button.click()
        if page.page_stack.currentIndex() != 0:
            raise RuntimeError("Optimized Tuner did not return to PID Control")

        # Use a fresh channel for the normal PID check so the preceding tuning
        # trial's plant state does not make the convergence assertion timing-dependent.
        page.channel_select.setCurrentIndex(control_index)
        page.setpoint_input.setValue(setpoint)
        page.kp_input.setValue(1.0)
        page.ki_input.setValue(0.05)
        page.kd_input.setValue(0.0)
        page.output_on_check.setChecked(True)
        page.control_enabled_check.setChecked(True)
        page.dry_run_check.setChecked(False)
        page.arm_button.setChecked(True)
        page.enable_button.setChecked(True)

        first = float(page.backend.LatestSnapshot()["channels"][control_index]["actual"])
        deadline = time.monotonic() + 4.0
        samples: list[float] = []
        while time.monotonic() < deadline:
            app.processEvents()
            page._tick_feedback()
            actual = float(page.backend.LatestSnapshot()["channels"][control_index]["actual"])
            samples.append(actual)
            if abs(setpoint - actual) < abs(setpoint - first) * 0.65:
                break
            time.sleep(0.05)

        last = samples[-1] if samples else first
        if abs(setpoint - last) >= abs(setpoint - first):
            raise RuntimeError(
                f"PID control did not move channel {control_index} toward setpoint: "
                f"first={first:.3f}, last={last:.3f}"
            )
        if not page.history:
            raise RuntimeError("PID plot history did not receive samples")

        print(
            "PID Control page simulator test passed: "
            f"first={first:.3f}, last={last:.3f}, setpoint={setpoint:.3f}, "
            f"command={page.command_values[control_index]:.3f}"
        )
        return 0
    finally:
        page.stop_backend()


if __name__ == "__main__":
    raise SystemExit(main())
