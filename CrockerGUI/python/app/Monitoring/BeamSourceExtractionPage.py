from collections.abc import Callable

from python.app.Monitoring.LiveTelemetryPage import LiveTelemetryPage


class BeamSourceExtractionPage(LiveTelemetryPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__('Beam Source & Extraction', go_back)
