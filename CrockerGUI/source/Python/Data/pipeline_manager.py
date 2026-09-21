from __future__ import annotations

import time
from pathlib import Path
from PySide6.QtCore import QObject, QTimer
from source.Python.Data.telemetry_database import TelemetryDatabase


class DataPipelineManager(QObject):
    """GUI-thread snapshot publication; SQL runs in the independent A worker."""
    def __init__(self, *, crocker_root: Path, db_path: Path, source='smoke',
                 rate_hz=20.0, snapshot_source=None, database=None):
        super().__init__()
        self.crocker_root, self.db_path = crocker_root, db_path
        self.source, self.rate_hz = source, rate_hz
        self.snapshot_source = snapshot_source
        self.database = database or TelemetryDatabase(db_path, source)
        self.timer = QTimer(self)
        self.timer.setInterval(max(1, round(1000/max(rate_hz, 1))))
        self.timer.timeout.connect(self._publish)
        self.error = ''

    def start(self):
        self.database.start()
        self.database.start_processor()
        self.timer.start()

    def _publish(self):
        try:
            if self.snapshot_source is not None:
                snapshot = self.snapshot_source()
            else:
                from source.Python.Simulator.ZMQSimulator import generate_frame, EPOCH_OFFSET
                frame = generate_frame(time.time())
                snapshot = dict(timestamp=frame.timestamp-EPOCH_OFFSET,
                    bitmask=frame.bitmask, channels=[dict(raw=v, actual=v) for v in frame.channels])
            self.database.snapshot(snapshot)
            self.error = ''
        except Exception as exc:
            self.error = str(exc)

    def stop(self):
        self.timer.stop()
        self.database.stop()

    def running(self):
        return self.timer.isActive() and not self.database.writer.done.is_set()
