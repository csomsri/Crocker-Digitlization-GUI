"""Exercise -ZMQ against an isolated LabVIEW-style client, never facility hardware."""
import os
import sys
import socket
import time
import json
from pathlib import Path
from threading import Event, Thread

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import zmq  # Before Qt import hooks.
import numpy as np
import CycloViz
from PySide6.QtWidgets import QApplication
from main import parse_args
from python.app.Automation.PidControlPage import PidControlPage
from source.Python.Services.BeamCalibrationService import BeamCalibrationService
from source.Python.Simulator.ZMQSimulator import Smoke2Plant, SimulatorFrame, ZMQSimulator


def main():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        endpoint = f'tcp://127.0.0.1:{probe.getsockname()[1]}'
    args = parse_args(['-ZMQ', '--zmq-endpoint', endpoint])
    assert args.backend_mode == 'zmq' and args.simulation_mode is None
    app = QApplication.instance() or QApplication([])
    service = CycloViz.ControlService()
    service.StartServer(endpoint)
    service.SetScaling(dict(enabled=[True]*14, raw_to_eng_gain=[1.]*14,
        raw_to_eng_offset=[0.]*14, eng_to_raw_gain=[1.]*14, eng_to_raw_offset=[0.]*14))
    service.SetChannelCommand(0, 200., True, True)
    service.ApplyCommand()
    calibration = BeamCalibrationService(ROOT / 'config' / 'beam_cal.json')
    calibration.set_manual_range(0)
    points = np.asarray(json.loads((ROOT / 'config' / 'beam_cal.json').read_text())['ranges'][0]['points'])

    class CoupledPlant(Smoke2Plant):
        def frame(self):
            frame = super().frame()
            beam_na = .1 + .02*(self.channels[0]-200)
            frame.channels[13] = float(np.interp(beam_na/1000, points[:, 1], points[:, 0]))
            return frame

    stop = Event()
    plant = CoupledPlant(raw_scale=1.)
    worker = Thread(target=lambda: ZMQSimulator(endpoint).stream(plant=plant, stop_event=stop), daemon=True)
    worker.start()
    def beam_state():
        return calibration.update(service.LatestSnapshot()).to_dict()
    page = PidControlPage(lambda: None, args.backend_mode, shared_backend=service,
                          manage_backend=False, get_beam_state=beam_state)
    def wait(predicate, timeout=10):
        end = time.monotonic()+timeout
        while time.monotonic()<end:
            app.processEvents()
            # Drive the same publisher used by an active PID/BO page.
            page._refresh_beam(publish=True)
            if predicate():
                return
            time.sleep(.01)
        raise AssertionError(str(service.PidTrialStatus()))
    config = dict(controller_kind='nla', measurement_channel=0, setpoint=.3,
                  kp=20., ki=0., kd=0., duration_seconds=6., update_rate_hz=20.,
                  telemetry_timeout_seconds=1., allocation=[1.]+[0.]*13,
                  command_bias=[0.]*14, minimum_command=[0.]*14, maximum_command=[800.]*14,
                  maximum_slew_per_second=[80.]*14, allocation_calibrated=False,
                  hardware_armed=True, dry_run=False, nla_deadband=.01, nla_output_max=10.)
    try:
        wait(lambda: service.LatestSnapshot()['connection']=='Connected' and page.beam_valid)
        page._start_trial(config)
        wait(lambda: service.PidTrialStatus()['state']!='Running')
        status = service.PidTrialStatus()
        assert status['state']=='Completed', status
        assert calibration.state_dict()['current_ua']*1000 > .2, calibration.state_dict()
        assert plant.channels[0]>205 and plant.enabled[0] and plant.on_off[0]
        assert service.PendingCommand()[0]['target'] <= 800
        print('PASS: -ZMQ, calibrated beam feedback, bounded TC commands and client replies')
        before = service.PendingCommand()[0]['target']
        page._start_trial(dict(config, dry_run=True, setpoint=.5, duration_seconds=.5))
        wait(lambda: service.PidTrialStatus()['state']!='Running')
        assert service.PidTrialStatus()['state']=='Completed'
        assert service.PendingCommand()[0]['target']==before
        print('PASS: dry run transmits no PID command changes')
        page._start_trial(dict(config, duration_seconds=10.))
        stop.set()
        worker.join(3)
        wait(lambda: service.PidTrialStatus()['state']=='Faulted', 4)
        assert not service.PendingCommand()[0]['enabled']
        print('PASS: lost feedback faults and disables output:', service.PidTrialStatus()['message'])
    finally:
        stop.set()
        page.stop_backend()
        service.Stop()
        worker.join(3)
        page.deleteLater()


if __name__ == '__main__':
    main()
