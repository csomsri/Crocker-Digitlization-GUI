from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from threading import Event, Thread

from source.Python.Data.data_logger import run_snapshot_logger_loop


class DataPipelineManager:
    def __init__(
        self,
        *,
        crocker_root: Path,
        db_path: Path,
        source: str = "smoke",
        rate_hz: float = 20.0,
        snapshot_source: Callable[[], dict | None] | None = None,
    ) -> None:
        self.crocker_root = crocker_root
        self.db_path = db_path
        self.source = source
        self.rate_hz = rate_hz
        self.snapshot_source = snapshot_source
        self._processes: list[subprocess.Popen] = []
        self._logger_thread: Thread | None = None
        self._logger_stop = Event()
        self._stop_file = db_path.with_suffix(".stop")

    def start(self) -> None:
        if self._processes or self._logger_thread is not None:
            return
        if self._stop_file.exists():
            self._stop_file.unlink()

        if self.snapshot_source is None:
            self._processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "source.Python.Data.data_logger",
                        "--db-path",
                        str(self.db_path),
                        "--source",
                        self.source,
                        "--rate-hz",
                        str(self.rate_hz),
                        "--stop-file",
                        str(self._stop_file),
                    ],
                    cwd=self.crocker_root,
                )
            )
        else:
            self._logger_stop.clear()
            self._logger_thread = Thread(
                target=run_snapshot_logger_loop,
                kwargs={
                    "db_path": self.db_path,
                    "snapshot_source": self.snapshot_source,
                    "rate_hz": self.rate_hz,
                    "batch_size": 100,
                    "stop_event": self._logger_stop,
                    "source": self.source,
                },
                name="transport-snapshot-logger",
                daemon=True,
            )
            self._logger_thread.start()

        self._processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "source.Python.Data.data_processor",
                    "--db-path",
                    str(self.db_path),
                    "--stop-file",
                    str(self._stop_file),
                ],
                cwd=self.crocker_root,
            )
        )

    def stop(self) -> None:
        self._logger_stop.set()
        self._stop_file.parent.mkdir(parents=True, exist_ok=True)
        self._stop_file.write_text("stop\n", encoding="utf-8")

        if self._logger_thread is not None:
            self._logger_thread.join(timeout=5)
            self._logger_thread = None

        for process in self._processes:
            if process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()

        for process in self._processes:
            if process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

        self._processes.clear()
        if self._stop_file.exists():
            self._stop_file.unlink()

    def running(self) -> bool:
        processes_running = bool(self._processes) and all(process.poll() is None for process in self._processes)
        logger_running = self._logger_thread is not None and self._logger_thread.is_alive()
        if self.snapshot_source is None:
            return processes_running
        return logger_running and processes_running
