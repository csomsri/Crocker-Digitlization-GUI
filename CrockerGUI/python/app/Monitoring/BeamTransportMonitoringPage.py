from collections.abc import Callable

from python.app.Monitoring.LiveTelemetryPage import LiveTelemetryPage


class BeamTransportMonitoringPage(LiveTelemetryPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__('Beam Transport Monitoring', go_back)
