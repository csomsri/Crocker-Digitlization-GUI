from collections.abc import Callable

from python.app.PageShell import MonitoringDetailPage


class MagneticFieldMonitoringPage(MonitoringDetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__(
            "Magnetic Field Monitoring",
            "Magnetic field live monitoring",
            ["B-Field X", "B-Field Y", "B-Field Z", "Magnet Temp", "Supply Current"],
            "Back to Monitoring",
            go_back,
        )
