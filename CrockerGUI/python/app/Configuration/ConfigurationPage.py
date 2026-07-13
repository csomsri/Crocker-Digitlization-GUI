from collections.abc import Callable

from python.app.PageShell import CategoryPage, PageSpec


CONFIGURATION_PAGES: list[PageSpec] = [
    ("Database Monitoring", "SQLite data viewer"),
    ("Recall", "Load/preview saved snapshots"),
    ("Settings", "App settings"),
    ("Scaling", "Scaling and calibration setup"),
]


class ConfigurationPage(CategoryPage):
    def __init__(
        self,
        show_home: Callable[[], None],
        open_page: Callable[[str, str], None],
    ) -> None:
        super().__init__("Configuration", CONFIGURATION_PAGES, show_home, open_page)
