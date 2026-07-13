from collections.abc import Callable

from python.app.PageShell import MonitoringDetailPage


class VacuumBeamMonitoringPage(MonitoringDetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__(
            "Vacuum / Beam Monitoring",
            "Vacuum, beam, and RF-style HUD monitoring",
            ["Vacuum A", "Vacuum B", "Beam Current", "RF Forward", "RF Reflected"],
            "Back to Monitoring",
            go_back,
        )
