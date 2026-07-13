from collections.abc import Callable

from python.app.PageShell import ConfigDetailPage


class ScalingPage(ConfigDetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__(
            "Scaling",
            "Scaling and calibration setup",
            ["Channel", "Scale factor", "Offset", "Units"],
            "Back to Configuration",
            go_back,
        )
