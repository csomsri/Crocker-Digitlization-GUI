from collections.abc import Callable

from python.app.PageShell import CategoryPage, PageSpec


AI_CONTROL_PAGES: list[PageSpec] = [
    ("AI ON OFF", "AI control toggle"),
]


class AiControlPage(CategoryPage):
    def __init__(
        self,
        show_home: Callable[[], None],
        open_page: Callable[[str, str], None],
    ) -> None:
        super().__init__("AI Control", AI_CONTROL_PAGES, show_home, open_page)
