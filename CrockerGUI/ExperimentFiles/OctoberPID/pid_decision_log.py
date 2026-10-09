# -*- coding: utf-8 -*-
"""One small CSV per PID session. Does not change existing SQLite recording."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

FIELDS = (
    "event", "utc", "decision_mono_s", "sample_first_source_s", "sample_last_source_s",
    "sample_first_receive_mono_s", "sample_last_receive_mono_s", "sample_count",
    "window_ms", "latest_sample_age_s", "range_index", "raw_latest_V", "raw_mean_V",
    "averaged_beam_nA", "setpoint_nA", "signed_error_nA", "abs_error_nA", "direction",
    "direction_changed", "trend", "in_deadband", "tc_channel", "target_before_A",
    "target_after_A", "tc_readback_A", "requested_delta_A", "command_delta_A",
    "output_accepted", "armed", "kp", "ki", "kd", "loop_ms", "beam_average_ms",
    "derivative_tau_s", "deadband_nA", "trend_tolerance_nA", "beam_stale_s",
    "math_dt_s", "status", "response_wait_ms", "next_average_after_receive_mono_s",
)


class PIDDecisionLog:
    def __init__(self):
        self.path: Path | None = None
        self.error = ""
        self._file = None
        self._writer = None

    def start(self, folder: Path, channel: str, fields: dict) -> bool:
        self.close()
        self.error = ""
        try:
            folder = Path(folder)
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.path = folder / f"PID_{stamp}_{channel}_{uuid4().hex[:6]}.csv"
            self._file = self.path.open("w", encoding="utf-8", newline="")
            self._writer = csv.DictWriter(self._file, fieldnames=FIELDS, extrasaction="ignore")
            self._writer.writeheader()
            return self.write("START", fields)
        except OSError as exc:
            self.error = str(exc)
            self.close()
            return False

    def write(self, event: str, fields: dict) -> bool:
        if self._writer is None:
            return False
        try:
            row = dict(fields, event=event, utc=datetime.now(timezone.utc).isoformat())
            self._writer.writerow(row)
            self._file.flush()
            return True
        except (OSError, ValueError, csv.Error) as exc:
            self.error = str(exc)
            self.close()
            return False

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
        self._file = None
        self._writer = None
