from collections.abc import Callable

from python.app.PageShell import ConfigDetailPage


class RecallPage(ConfigDetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__(
            "Recall",
            "Load/preview saved snapshots",
            ["Snapshot folder", "Snapshot ID", "Preview filter"],
            "Back to Configuration",
            go_back,
        )
