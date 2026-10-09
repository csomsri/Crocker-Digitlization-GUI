from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import parse_args


def main() -> int:
    first_order = parse_args(["-simulation", "-first-order"])
    assert first_order.simulation_mode == "first-order"
    assert first_order.backend_mode == "simulation"

    smoke = parse_args(["-simulation", "-smoke"])
    assert smoke.backend_mode == "simulation"
    assert smoke.simulation_mode == "smoke"

    cyclotron = parse_args(["-simulation", "-cyclotron"])
    assert cyclotron.backend_mode == "simulation"
    assert cyclotron.simulation_mode == "cyclotron"

    smoke2 = parse_args(["-simulation", "-smoke2"])
    assert smoke2.backend_mode == "simulation"
    assert smoke2.simulation_mode == "smoke2"

    zmq = parse_args(["-ZMQ"])
    assert zmq.backend_mode == "zmq"
    assert zmq.simulation_mode is None
    assert not zmq.show_fps
    for flags in (["-simulation", "-smoke2"], ["-ZMQ"]):
        assert parse_args([*flags, "-FPS"]).show_fps

    pipeline = parse_args(["-simulation", "-smoke", "--data-pipeline"])
    assert pipeline.data_pipeline is True
    assert pipeline.db_path
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
