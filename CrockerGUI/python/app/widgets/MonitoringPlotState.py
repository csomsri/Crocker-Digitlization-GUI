from __future__ import annotations

import time


MONITOR_VARIABLES: dict[str, list[str]] = {
    "Beam Transport Monitoring": [
        "Beam X",
        "Beam Y",
        "Current",
        "Loss",
        "Steerer A",
        "Steerer B",
    ],
    "Beam Source & Extraction": [
        "Source Current",
        "Extractor Voltage",
        "Arc",
        "Plasma",
        "Interlock",
    ],
    "Vacuum / Beam Monitoring": [
        "Vacuum A",
        "Vacuum B",
        "Beam Current",
        "RF Forward",
        "RF Reflected",
    ],
    "RF Power Monitoring": [
        "Forward Power",
        "Reflected Power",
        "Phase",
        "Duty",
        "RF Status",
    ],
}

MONITOR_CONTROL_TABS: list[tuple[str, str]] = [
    ("Magnetic Field Monitoring", "Field"),
    ("Beam Transport Monitoring", "Beam Transport"),
    ("Beam Source & Extraction", "Source / Extraction"),
    ("Vacuum / Beam Monitoring", "Vacuum / Beam"),
    ("RF Power Monitoring", "RF Power"),
]


class MonitoringPlotState:
    def __init__(self) -> None:
        self.plot_enabled = {
            page_title: {channel: True for channel in channels}
            for page_title, channels in MONITOR_VARIABLES.items()
        }
        self.last_updated = 0.0

    def is_enabled(self, page_title: str, channel: str) -> bool:
        return self.plot_enabled.get(page_title, {}).get(channel, True)

    def set_enabled(self, page_title: str, channel: str, enabled: bool) -> None:
        page = self.plot_enabled.setdefault(page_title, {})
        page[channel] = bool(enabled)
        self.last_updated = time.perf_counter()

    def set_all_enabled(self, page_title: str, enabled: bool) -> None:
        for channel in self.plot_enabled.get(page_title, {}):
            self.plot_enabled[page_title][channel] = bool(enabled)
        self.last_updated = time.perf_counter()

    def enabled_channels(self, page_title: str, channels: list[str]) -> list[str]:
        return [channel for channel in channels if self.is_enabled(page_title, channel)]


_MONITORING_PLOT_STATE = MonitoringPlotState()


def monitoring_plot_state() -> MonitoringPlotState:
    return _MONITORING_PLOT_STATE
