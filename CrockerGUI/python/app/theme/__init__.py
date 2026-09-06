"""Shared UI theme resources for main and assigned monitor windows."""

from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QFontDatabase


@lru_cache(maxsize=1)
def load_app_font() -> str:
    """Register the bundled font once, after QApplication has been created."""
    font_path = Path(__file__).resolve().parents[3] / "assets" / "fonts" / "FuturisticArmour-1p84.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    families = QFontDatabase.applicationFontFamilies(font_id) if font_id != -1 else []
    return families[0] if families else "Segoe UI"


def load_stylesheet(font_family: str) -> str:
    """Resolve the shared stylesheet independently of the working directory."""
    source = Path(__file__).with_name("application.qss").read_text(encoding="utf-8")
    directory = Path(__file__).parent
    numbers = (directory / "number-input.qss").read_text(encoding="utf-8")
    numbers = numbers.replace("__UP_PATH__", (directory / "chevron-up.svg").as_posix())
    numbers = numbers.replace("__DOWN_PATH__", (directory / "chevron-down.svg").as_posix())
    return source.replace("__APP_FONT__", font_family) + "\n" + numbers


@lru_cache(maxsize=1)
def load_dropdown_stylesheet() -> str:
    return Path(__file__).with_name("dropdown.qss").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def load_dropdown_control_stylesheet() -> str:
    directory = Path(__file__).parent
    source = (directory / "dropdown-control.qss").read_text(encoding="utf-8")
    return source.replace("__CHEVRON_PATH__", (directory / "chevron-down.svg").as_posix())
