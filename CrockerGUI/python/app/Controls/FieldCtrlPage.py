from collections.abc import Callable

from python.app.PageShell import ControlDetailPage


class FieldCtrlPage(ControlDetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__(
            "Field Ctrl",
            "Magnetic/beam control screen",
            ["Magnet Current", "Beam Steering", "RF Trim", "Ramp Rate"],
            "Back to Manual Controls",
            go_back,
        )
