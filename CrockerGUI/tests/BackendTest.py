"""
ControlService simulator smoke test.

Run from the repository root after building the CycloViz Python extension:
    python CrockerGUI/tests/BackendTest.py
"""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path


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


def main() -> int:
    CycloViz = importlib.import_module("CycloViz")
    if not hasattr(CycloViz, "ControlService"):
        module_path = getattr(CycloViz, "__file__", "<unknown>")
        raise RuntimeError(
            "The imported CycloViz module does not expose ControlService. "
            "Rebuild the CycloViz Python extension after the new bindings were added. "
            f"Imported module: {module_path}"
        )

    backend = CycloViz.ControlService()
    target = 100.0
    samples: list[float] = []

    try:
        backend.StartSimulator()

        backend.SetChannelTarget(0, target)
        backend.SetChannelOn(0, True)
        backend.SetChannelEnabled(0, True)

        if not backend.ApplyCommand():
            raise RuntimeError("ApplyCommand returned false")

        for _ in range(100):
            snapshot = backend.LatestSnapshot()
            actual = float(snapshot["channels"][0]["actual"])
            samples.append(actual)
            print(f"channel 0 actual: {actual:8.3f}")
            time.sleep(0.1)

        if len(samples) < 2:
            raise RuntimeError("not enough simulator samples")

        if samples[-1] <= samples[0]:
            raise RuntimeError(
                f"simulator did not move toward target: first={samples[0]:.3f}, last={samples[-1]:.3f}"
            )

        if abs(target - samples[-1]) >= abs(target - samples[0]):
            raise RuntimeError(
                f"simulator did not get closer to target: first={samples[0]:.3f}, last={samples[-1]:.3f}"
            )

        health = backend.Health()
        print(
            "simulator smoke test passed: "
            f"first={samples[0]:.3f}, last={samples[-1]:.3f}, "
            f"connection={health['connection']}, simulated={health['simulated']}"
        )
        return 0
    finally:
        backend.Stop()


if __name__ == "__main__":
    raise SystemExit(main())
