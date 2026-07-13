from collections.abc import Callable

from python.app.PageShell import ToggleDetailPage


class AiOnOffPage(ToggleDetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__(
            "AI ON OFF",
            "AI control toggle",
            ["Enable AI assistant", "Allow AI recommendations", "Require operator approval"],
            "Back to AI Control",
            go_back,
        )
