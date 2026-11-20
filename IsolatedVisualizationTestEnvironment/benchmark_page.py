"""Reusable PySide benchmark page. Feature registration lives in main.py."""

import csv
from collections import deque
from datetime import datetime
import math
from time import perf_counter

import psutil
from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


GPU_FIELDS = ("gpu_pct", "gpu_memory_mib", "gpu_memory_total_mib", "gpu_power_w",
              "gpu_temperature_c")
CSV_FIELDS = (
    "mode", "simulator_hz", "warmup_frames", "elapsed_s", "packet_sequence",
    "packet_timestamp", "packet_latency_ms",
    "queue_depth", "coalesced_packets", "invalid_frames", "receive_hz", "frame_hz",
    "frame_interval_ms", "frame_work_ms", "prepare_ms", "process_cpu_pct",
    "system_cpu_pct", "process_rss_mib", "gpu_device", "gpu_sample_age_ms", *GPU_FIELDS,
)


class BenchmarkPage(QWidget):
    def __init__(self, server, endpoint, feature, device, warmup_frames, simulator_hz):
        super().__init__()
        self.server = server
        self.feature = feature
        self.device = str(device)
        self.warmup_frames = warmup_frames
        self.simulator_hz = simulator_hz
        self.file = None
        self.recording_failed = False
        self.sequence = 0
        self.gpu = {}
        self.gpu_time = None
        self.gpu_target = feature.device_id or self.device
        self.polled_target = None
        self.process = psutil.Process()
        self.samples = deque(maxlen=240)
        self.setWindowTitle(f"Visualization benchmark | {feature.name} | {feature.mode}")
        self.resize(*getattr(feature, "window_size", (850, 540)))

        self.endpoint = endpoint
        self.record_button = QPushButton("Start recording")
        self.record_button.clicked.connect(self.toggle_recording)
        controls = QHBoxLayout()
        controls.addWidget(QLabel(feature.mode))
        controls.addWidget(self.record_button)
        controls.addStretch()

        self.status = QLabel(f"Listening on {endpoint}")
        self.resources = QLabel()
        self.summary = QLabel()
        self.timing = QLabel()
        self.result = QLabel()
        self.result.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.status)
        layout.addWidget(feature, 1)
        layout.addWidget(self.summary)
        layout.addWidget(self.timing)
        layout.addWidget(self.resources)
        layout.addWidget(self.result)

        self.reader = QTimer(self, interval=5)
        self.reader.timeout.connect(self.receive)
        self.reader.start()

        self.gpu_query = QProcess(self)
        self.gpu_query.finished.connect(self.read_gpu)
        self.gpu_query.errorOccurred.connect(self.gpu_error)
        self.telemetry = QTimer(self, interval=1000)
        self.telemetry.timeout.connect(self.sample_resources)
        self.telemetry.start()
        self.sample_resources()

    def toggle_recording(self):
        if self.file is not None:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        try:
            self.feature.results.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            self.path = self.feature.results / f"{stamp}.csv"
            self.file = self.path.open("x", newline="", encoding="utf-8")
            self.writer = csv.DictWriter(self.file, fieldnames=(*CSV_FIELDS, *self.feature.metrics))
            self.writer.writeheader()
        except (OSError, RuntimeError) as error:
            self.stop_recording(str(error))
            return False
        self.gpu = {}
        self.gpu_time = None
        self.cpu = {}
        self.process.cpu_percent(None)
        psutil.cpu_percent(None)
        self.samples.clear()
        self.latest_sample = {}
        self.started = perf_counter()
        self.first_sequence = self.sequence
        self.previous_frame = None
        self.frames = self.coalesced = self.invalid = 0
        self.warmup = self.warmup_frames
        self.record_button.setText("Stop recording")
        self.summary.setText(f"Warming up for {self.warmup_frames} valid frames")
        self.timing.clear()
        self.result.setText(f"Recording {self.path}")
        self.recording_failed = False
        self.poll_gpu()
        return True

    def stop_recording(self, error=None):
        if self.file is not None:
            try:
                self.file.close()
            except OSError as close_error:
                error = error or str(close_error)
            self.file = None
            self.result.setText(f"Saved {getattr(self, 'frames', 0)} samples to {self.path}")
        self.record_button.setText("Start recording")
        if error:
            self.recording_failed = True
            self.result.setText(f"Recording error: {error}")

    def receive(self):
        packet = None
        received = 0
        for _ in range(256):
            current = self.server.TryPopPacket()
            if current is None:
                break
            packet = current
            received += 1
        if packet is None:
            return
        self.sequence += received

        if self.recording_failed:
            return
        started = perf_counter()
        try:
            validate = self.file is not None and self.warmup == self.warmup_frames
            sample = self.feature.process(packet, validate)
            if self.file is not None:
                self.coalesced += received - 1
                if sample is None:
                    self.invalid += 1
                elif self.warmup:
                    if (sample["render_ms"] is not None
                            and sample.get("panels_rendered") == sample.get("panels_with_data")):
                        self.warmup -= 1
                        if self.warmup == 0:
                            self.started = perf_counter()
                            self.first_sequence = self.sequence
                            self.coalesced = self.invalid = 0
                            self.process.cpu_percent(None)
                            psutil.cpu_percent(None)
                            self.cpu = {}
                else:
                    self.write_sample(packet, sample, started)
        except (OSError, RuntimeError) as error:
            self.stop_recording(str(error))

    def write_sample(self, packet, sample, started):
        finished = perf_counter()
        elapsed = finished - self.started
        work_ms = (finished - started) * 1000
        interval_ms = None if self.previous_frame is None else (started - self.previous_frame) * 1000
        queue_depth = self.server.PacketQueueSize()
        receive_hz = (self.sequence - self.first_sequence) / elapsed
        self.previous_frame = started
        self.samples.append(work_ms)
        self.writer.writerow({
            "mode": self.feature.mode, "simulator_hz": self.simulator_hz,
            "warmup_frames": self.warmup_frames, "elapsed_s": elapsed,
            "packet_sequence": self.sequence,
            "packet_timestamp": packet.get("timestamp"), "packet_latency_ms": packet.get("latency"),
            "queue_depth": queue_depth, "coalesced_packets": self.coalesced,
            "invalid_frames": self.invalid, "receive_hz": receive_hz,
            "frame_hz": (self.frames + 1) / elapsed,
            "frame_interval_ms": interval_ms, "frame_work_ms": work_ms,
            "gpu_device": self.gpu_target,
            "gpu_sample_age_ms": None if self.gpu_time is None else (finished - self.gpu_time) * 1000,
            **sample, **self.cpu, **self.gpu,
        })
        self.latest_sample = sample
        self.frames += 1

    def sample_resources(self):
        self.cpu = {
            "process_cpu_pct": self.process.cpu_percent(None),
            "system_cpu_pct": psutil.cpu_percent(None),
            "process_rss_mib": self.process.memory_info().rss / (1024 * 1024),
        }
        self.poll_gpu()
        cpu = self.cpu
        gpu = self.gpu
        gpu_pct = gpu.get("gpu_pct")
        memory = gpu.get("gpu_memory_mib")
        gpu_text = "GPU unavailable" if gpu_pct is None else f"GPU {gpu_pct:g}%"
        if memory is not None:
            gpu_text += f" | VRAM {memory:g} MiB"
        self.resources.setText(
            f"Process CPU {cpu['process_cpu_pct']:.1f}% | System CPU {cpu['system_cpu_pct']:.1f}%"
            f" | RSS {cpu['process_rss_mib']:.0f} MiB | {gpu_text}"
        )
        self.status.setText(f"{self.endpoint} | Packets {self.sequence:,} | Queue {self.server.PacketQueueSize():,}")
        if self.file is not None and self.samples:
            ordered = sorted(self.samples)
            mean = sum(ordered) / len(ordered)
            p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
            rate = self.frames / (perf_counter() - self.started)
            summary = (
                f"{self.frames:,} samples | {rate:.1f} frames/s | Frame work mean {mean:.3f} ms"
                f" | p95 {p95:.3f} ms | Coalesced {self.coalesced:,} | Invalid {self.invalid:,}"
            )
            if "panels_with_data" in self.latest_sample:
                summary += (f" | Panels rendered {self.latest_sample['panels_rendered']}"
                            f"/{self.latest_sample['panels_with_data']}")
            self.summary.setText(summary)
            labels = (("prepare_ms", "Prepare"), ("upload_ms", "Upload"),
                      ("kernel_ms", "Kernel"), ("download_ms", "Download"), ("render_ms", "Render"))
            self.timing.setText(" | ".join(
                f"{label} {self.latest_sample[field]:.3f} ms"
                for field, label in labels if self.latest_sample.get(field) is not None
            ))

    def poll_gpu(self):
        if self.gpu_query.state() == QProcess.ProcessState.NotRunning:
            self.polled_target = self.gpu_target
            self.gpu_query.start("nvidia-smi", [
                "-i", self.polled_target, "--format=csv,noheader,nounits",
                "--query-gpu=utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu",
            ])

    def read_gpu(self, exit_code, exit_status):
        raw = bytes(self.gpu_query.readAllStandardOutput()).decode(errors="replace").strip()
        self.gpu_query.readAllStandardError()
        if self.polled_target != self.gpu_target:
            return
        self.gpu = {}
        self.gpu_time = None
        if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
            for field, value in zip(GPU_FIELDS, raw.split(",")):
                try:
                    self.gpu[field] = float(value)
                except ValueError:
                    continue
            if self.gpu:
                self.gpu_time = perf_counter()

    def gpu_error(self, _error):
        self.gpu = {}
        self.gpu_time = None

    def closeEvent(self, event):
        self.reader.stop()
        self.telemetry.stop()
        self.stop_recording()
        if self.gpu_query.state() != QProcess.ProcessState.NotRunning:
            self.gpu_query.kill()
            self.gpu_query.waitForFinished(1000)
        super().closeEvent(event)
