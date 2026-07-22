from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class DataPipelineManager:
    def __init__(
        self,
        *,
        crocker_root: Path,
        db_path: Path,
        source: str = "smoke",
        rate_hz: float = 20.0,
    ) -> None:
        self.crocker_root = crocker_root
        self.db_path = db_path
        self.source = source
        self.rate_hz = rate_hz
        self._processes: list[subprocess.Popen] = []
        self._stop_file = db_path.with_suffix(".stop")

    def start(self) -> None:
        if self._processes:
            return
        if self._stop_file.exists():
            self._stop_file.unlink()

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
        self._stop_file.parent.mkdir(parents=True, exist_ok=True)
        self._stop_file.write_text("stop\n", encoding="utf-8")

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
        return bool(self._processes) and all(
            process.poll() is None for process in self._processes
        )
