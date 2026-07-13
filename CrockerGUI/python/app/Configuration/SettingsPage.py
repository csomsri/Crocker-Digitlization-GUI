from collections.abc import Callable

from python.app.PageShell import ConfigDetailPage


class SettingsPage(ConfigDetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__(
            "Settings",
            "App settings",
            ["ZMQ endpoint", "Data directory", "Operator name", "Refresh rate"],
            "Back to Configuration",
            go_back,
        )
