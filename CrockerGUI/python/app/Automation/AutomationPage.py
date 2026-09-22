from collections.abc import Callable

from python.app.PageShell import CategoryPage, PageSpec


AUTOMATION_PAGES: list[PageSpec] = [
    ("PID Control", "Control measured beam current through a selected trim coil; includes BO tuning"),
    ("PythonPID", "Control coil current directly in amps using Python PID"),
    ("GA + C++ PID", "Tune beam-feedback C++ PID gains with GA in simulation"),
    ("GA + Python PID", "Tune beam-feedback Python PID gains with GA in simulation"),
    ("Hybrid GA + BO PID", "GA exploration and measured Bayesian handover with C++ beam PID"),
]


class AutomationPage(CategoryPage):
    def __init__(
        self,
        show_home: Callable[[], None],
        open_page: Callable[[str, str], None],
    ) -> None:
        super().__init__("Automation", AUTOMATION_PAGES, show_home, open_page, columns=1)
