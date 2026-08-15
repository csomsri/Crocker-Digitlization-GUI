from collections.abc import Callable

from python.app.PageShell import MonitoringDetailPage


class BeamSourceExtractionPage(MonitoringDetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__(
            "Beam Source & Extraction",
            "Source/extraction monitoring",
            ["Source Current", "Extractor Voltage", "Arc", "Plasma", "Interlock"],
            "Back to Monitoring",
            go_back,
        )
