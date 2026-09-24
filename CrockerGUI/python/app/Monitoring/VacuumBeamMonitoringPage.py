from collections.abc import Callable

from python.app.Monitoring.LiveTelemetryPage import LiveTelemetryPage


class VacuumBeamMonitoringPage(LiveTelemetryPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__('Vacuum / Beam Monitoring', go_back)
