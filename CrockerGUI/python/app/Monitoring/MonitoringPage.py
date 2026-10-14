from collections.abc import Callable

from python.app.PageShell import CategoryPage, PageSpec


MONITORING_PAGES: list[PageSpec] = [
    ("Magnetic Field Monitoring", "Magnetic field live monitoring"),
    ("Beam Transport Monitoring", "Beam transport live monitoring"),
    ("Beam Source & Extraction", "Source/extraction monitoring"),
    ("Vacuum / Beam Monitoring", "Vacuum readings and beam current"),
    ("RF Power Monitoring", "Live RF reading and trend"),
    ("Display Controller", "Choose the monitoring view shown on managed displays"),
]


class MonitoringPage(CategoryPage):
    def __init__(
        self,
        show_home: Callable[[], None],
        open_page: Callable[[str, str], None],
    ) -> None:
        super().__init__('Monitoring', MONITORING_PAGES, show_home, open_page)
