from collections.abc import Callable

from python.app.PageShell import ConfigDetailPage


class DatabaseMonitoringPage(ConfigDetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__(
            "Database Monitoring",
            "SQLite data viewer",
            ["Database path", "Table", "Filter"],
            "Back to Configuration",
            go_back,
        )
