from collections.abc import Callable

from python.app.PageShell import CategoryPage, PageSpec


MANUAL_CONTROL_PAGES: list[PageSpec] = [
    ("Field Ctrl", "Magnetic/beam control screen"),
    ("Beam Range", "Beam range selection/control"),
    ("Alarm", "Alarm on/off toggle"),
    ("Snapshot", "Captures current channel state to file"),
]


class ManualControlsPage(CategoryPage):
    def __init__(
        self,
        show_home: Callable[[], None],
        open_page: Callable[[str, str], None],
    ) -> None:
        super().__init__("Manual Controls", MANUAL_CONTROL_PAGES, show_home, open_page)
