from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import parse_args


def main() -> int:
    smoke = parse_args(["-simulation", "-smoke"])
    assert smoke.backend_mode == "simulation"
    assert smoke.simulation_mode == "smoke"

    cyclotron = parse_args(["-simulation", "-cyclotron"])
    assert cyclotron.backend_mode == "simulation"
    assert cyclotron.simulation_mode == "cyclotron"

    zmq = parse_args(["-ZMQ"])
    assert zmq.backend_mode == "zmq"
    assert zmq.simulation_mode is None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
