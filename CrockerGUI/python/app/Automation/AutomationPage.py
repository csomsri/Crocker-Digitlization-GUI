from collections.abc import Callable

from python.app.PageShell import CategoryPage, PageSpec


AUTOMATION_PAGES: list[PageSpec] = [
    ("PID Control", "Run closed-loop control on a selected channel"),
    ("PythonPID", "Run nonlinear adaptive-direction PID in Python"),
]


class AutomationPage(CategoryPage):
    def __init__(
        self,
        show_home: Callable[[], None],
        open_page: Callable[[str, str], None],
    ) -> None:
        super().__init__("Automation", AUTOMATION_PAGES, show_home, open_page, columns=1)
