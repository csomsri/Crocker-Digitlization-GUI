from collections.abc import Callable

from python.app.PageShell import ControlDetailPage


class BeamRangePage(ControlDetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__(
            "Beam Range",
            "Beam range selection/control",
            ["Range Start", "Range Stop", "Step Size", "Dwell Time"],
            "Back to Manual Controls",
            go_back,
        )
