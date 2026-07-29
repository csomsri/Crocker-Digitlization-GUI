from collections.abc import Callable

from python.app.PageShell import CategoryPage, PageSpec


AUTOMATION_PAGES: list[PageSpec] = [
    ("Exploration", "Explore and characterize daily machine settings"),
    ("PID Control", "Run closed-loop control on a selected channel"),
    ("Assisted Tuning", "Safely suggest and log one approved trial at a time"),
]


class AutomationPage(CategoryPage):
    def __init__(
        self,
        show_home: Callable[[], None],
        open_page: Callable[[str, str], None],
    ) -> None:
        super().__init__("Automation", AUTOMATION_PAGES, show_home, open_page)
