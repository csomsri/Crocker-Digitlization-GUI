from collections.abc import Callable

from python.app.Monitoring.LiveTelemetryPage import LiveTelemetryPage


class RfPowerMonitoringPage(LiveTelemetryPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__('RF Power Monitoring', go_back)
