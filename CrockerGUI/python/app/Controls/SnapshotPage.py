from collections.abc import Callable

from python.app.PageShell import SnapshotDetailPage


class SnapshotPage(SnapshotDetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__("Back to Manual Controls", go_back)
