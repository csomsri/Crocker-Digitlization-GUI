"""Exercise the smoke2 preset and a real ZMQ PID trial, without hardware."""
import socket
import time
from pathlib import Path
from threading import Event, Thread

import zmq  # Load before Qt's import hook.
from PidControlPageTest import QApplication, PidControlPage
from python.app.Automation.PythonPIDPage import PythonPIDPage
from source.Python.Simulator.ZMQSimulator import Smoke2Plant, ZMQSimulator
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QDialog, QTableWidget, QAbstractItemView
from PySide6.QtGui import QFontDatabase


def main():
    app = QApplication.instance() or QApplication([])
    beam_page = PidControlPage(lambda: None, 'zmq', manage_backend=False,
                               tuning_enabled=True, simulation_mode='smoke2')
    try:
        beam_page._load_smoke2_preset()
        assert beam_page.tuner_target.suffix() == ' nA'
        assert 'no TC-to-beam response' in beam_page.tuner_status.text()
        assert beam_page.smoke2_preset_button.isHidden()
    finally:
        beam_page.stop_backend()
        beam_page.deleteLater()
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        endpoint = f"tcp://127.0.0.1:{probe.getsockname()[1]}"
    page = PythonPIDPage(lambda: None, "zmq", zmq_endpoint=endpoint,
                          tuning_enabled=True, simulation_mode="smoke2")
    page.backend.SetScaling({
        "enabled": [True] * 14,
        "raw_to_eng_gain": [1.0e8] * 14, "raw_to_eng_offset": [0.0] * 14,
        "eng_to_raw_gain": [1.0e-8] * 14, "eng_to_raw_offset": [0.0] * 14,
    })
    stop = Event()
    plant = Smoke2Plant()

    def stream():
        ZMQSimulator(endpoint).stream(plant=plant, stop_event=stop)

    worker = Thread(target=stream, daemon=True)
    worker.start()

    def wait_for(predicate, seconds=40):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.02)
        assert predicate(), page.tuner_status.text()

    try:
        wait_for(lambda: page.actual_values[0] > 190)
        page._show_tuner()
        page._load_smoke2_preset()
        assert page.tuner_target.value() == 250
        assert page.tuner_trials.value() == 20
        assert not page.dry_run_check.isChecked()
        page.arm_button.setChecked(True)
        page._prepare_tuning_session()
        wait_for(lambda: page.tuning_candidate is not None)
        page._run_tuning_trial()
        wait_for(lambda: len(page.tuning_results) == 1)
        assert page.tuning_results[0].safe
        assert max(sample[1] for sample in page.tuning_samples) > 210
        inspected = []

        def inspect_history():
            dialog = next(d for d in page.findChildren(QDialog)
                          if d.isVisible() and d.findChild(QTableWidget) is not None)
            table = dialog.findChild(QTableWidget)
            inspected.append(table.rowCount() == 1 and
                             table.editTriggers() == QAbstractItemView.NoEditTriggers and
                             table.item(0, 9).text() in {"Best observed", "Oscillating"} and
                             isinstance(table.item(0, 4).data(Qt.DisplayRole), float))
            dialog.grab().save(str(Path(__file__).parents[1] / "Exports" / "smoke2-history.png"))
            dialog.accept()

        QTimer.singleShot(100, inspect_history)
        page._show_tuning_history()
        assert inspected == [True]
        print("Smoke2 preset and live ZMQ BO trial passed", page.tuning_results[0])
    finally:
        page.stop_backend()
        stop.set()
        worker.join(timeout=3)


if __name__ == "__main__":
    main()
