from collections.abc import Callable

from python.app.PageShell import ToggleDetailPage


class AlarmPage(ToggleDetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__(
            "Alarm",
            "Alarm on/off toggle",
            ["Enable audible alarm", "Enable visual alarm", "Trip on interlock", "Log alarm changes"],
            "Back to Manual Controls",
            go_back,
        )
