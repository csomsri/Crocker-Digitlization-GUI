import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source.Python.Simulator.FirstOrderBeamPlant import FirstOrderBeamPlant
from source.Python.Simulator.ZMQSimulator import build_bitmask


def main():
    plant = FirstOrderBeamPlant()
    initial = plant.channels[9]
    targets = list(plant.channels)
    targets[9] = 200.0
    enabled = [False] * 14
    enabled[9] = True
    reply = [value * plant.raw_scale for value in targets] + [build_bitmask([True] * 14, enabled)]
    plant.apply_reply(reply, 2.0)
    assert math.isclose(plant.channels[9], 200 + (initial - 200) * math.exp(-1))
    assert math.isclose(plant.beam_na, plant.channels[9] * 0.004)
    before = plant.beam_na
    targets[0] = 999.0
    plant.apply_reply([value * plant.raw_scale for value in targets] + [reply[-1]], 0)
    assert plant.beam_na == before
    for _ in range(200):
        plant.apply_reply(reply, 0.1)
    assert abs(plant.beam_na - 0.8) < 0.00001
    assert abs(plant.frame().beam_current - 0.215) < 0.00001
    plant.disturbance_na = -0.1
    plant.apply_reply(reply, 0)
    assert abs(plant.beam_na - 0.7) < 0.00001
    print("First-order TC10 response, independent channels, calibration and disturbance passed")


if __name__ == '__main__':
    main()
