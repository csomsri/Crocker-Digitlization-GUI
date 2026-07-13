from collections.abc import Callable

from python.app.PageShell import MonitoringDetailPage


class RfPowerMonitoringPage(MonitoringDetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__(
            "RF Power Monitoring",
            "RF power monitoring routed through Field Ctrl for now",
            ["Forward Power", "Reflected Power", "Phase", "Duty", "RF Status"],
            "Back to Monitoring",
            go_back,
        )
