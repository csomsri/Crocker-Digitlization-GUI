from collections.abc import Callable

from python.app.PageShell import CategoryPage, PageSpec


CONFIGURATION_PAGES: list[PageSpec] = [
    ("Database Monitoring", "SQLite data viewer"),
    ("Recall", "Load/preview saved snapshots"),
    ("Scaling", "Scaling and calibration setup"),
    ("Settings", "App settings"),
]


class ConfigurationPage(CategoryPage):
    def __init__(
        self,
        show_home: Callable[[], None],
        open_page: Callable[[str, str], None],
    ) -> None:
        super().__init__("Settings", CONFIGURATION_PAGES, show_home, open_page, columns=1)
