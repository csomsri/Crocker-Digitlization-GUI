from collections.abc import Callable

from python.app.PageShell import MonitoringDetailPage


class BeamTransportMonitoringPage(MonitoringDetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__(
            "Beam Transport Monitoring",
            "Beam transport live monitoring",
            ["Beam X", "Beam Y", "Current", "Loss", "Steerer A", "Steerer B"],
            "Back to Monitoring",
            go_back,
        )
