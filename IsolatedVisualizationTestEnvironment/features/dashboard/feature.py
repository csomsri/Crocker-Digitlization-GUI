"""Render all telemetry sections from a single decoded ZMQ packet."""

from pathlib import Path

from PySide6.QtWidgets import QGridLayout, QGroupBox, QVBoxLayout, QWidget

from features.bar_plot.feature import BarPlot
from features.dashboard.sections import SECTIONS, readings


TIMINGS = ("prepare_ms", "render_ms", "upload_ms", "kernel_ms", "download_ms")
PANEL_FIELDS = (*TIMINGS, "bars", "plot_width_px", "plot_height_px", "readings")


class SectionPlots(QWidget):
    name = "All telemetry sections"
    window_size = (1150, 760)
    metrics = (
        *TIMINGS[1:], "panels_with_data", "panels_rendered", "bars", "renderer",
        "beam_range_idx",
        *(f"{key}_{field}" for key, _, _ in SECTIONS for field in PANEL_FIELDS),
    )

    def __init__(self, mode, library, bars, device):
        super().__init__()
        self.mode = mode
        self.bars = bars
        self.results = Path(__file__).with_name("results") / mode
        self.panels = {}
        self.scales = {}
        grid = QGridLayout(self)
        for index, (key, title, count) in enumerate(SECTIONS):
            panel = BarPlot(mode, library, (bars or count) if count > 1 else 1,
                            device, minimum_height=100)
            box = QGroupBox(title)
            layout = QVBoxLayout(box)
            layout.addWidget(panel)
            policy = panel.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            panel.setSizePolicy(policy)
            grid.addWidget(box, index // 4, index % 4)
            grid.setColumnStretch(index % 4, 1)
            grid.setRowStretch(index // 4, 1)
            self.panels[key] = (box, panel)

    @property
    def device_id(self):
        return self.panels["channels"][1].device_id

    def start(self):
        for _, panel in self.panels.values():
            panel.start()

    def stop(self):
        for _, panel in self.panels.values():
            panel.stop()

    def process(self, packet, validate=False):
        row = {"beam_range_idx": packet.get("beam_range_idx")}
        samples = []
        for key, title, capacity in SECTIONS:
            box, panel = self.panels[key]
            values = readings(packet, key, capacity)
            row[f"{key}_readings"] = len(values)
            if not values:
                if box.title() != f"{title} (no data)":
                    box.setTitle(f"{title} (no data)")
                    panel.hide()
                continue

            if panel.isHidden():
                box.setTitle(title)
                panel.show()
            peak = max(map(abs, values))
            if key not in self.scales and peak >= 1e-30:
                self.scales[key] = min(peak * 1.25, 3.4e38)
            scale = self.scales.get(key, 1e-30)
            if self.bars is None:
                values += (0.0,) * (capacity - len(values))
            sample = panel.plot_values(values, validate, scale=scale)
            samples.append(sample)
            row.update({f"{key}_{field}": sample.get(field)
                        for field in PANEL_FIELDS if field != "readings"})

        if not samples:
            return None
        for field in TIMINGS:
            values = [sample[field] for sample in samples if sample.get(field) is not None]
            row[field] = sum(values) if values else None
        row.update(
            panels_with_data=len(samples),
            panels_rendered=sum(sample["render_ms"] is not None for sample in samples),
            bars=sum(sample["bars"] for sample in samples),
            renderer=samples[0]["renderer"],
        )
        return row
