"""Shared UI theme resources for main and assigned monitor windows."""

from functools import lru_cache
from pathlib import Path
import os
from PySide6.QtGui import QFontDatabase
from .palette import graphite_stylesheet

@lru_cache(maxsize=1)
def load_app_font() -> str:
    """Use a readable system face throughout controls and painted page headings."""
    # Offscreen Qt on Windows does not enumerate system fonts. Register the
    # system files explicitly so screenshots and unattended tests stay legible.
    if os.name == 'nt':
        font_directory = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        for name in ('segoeui.ttf', 'segoeuib.ttf', 'seguisb.ttf'):
            path = font_directory / name
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
    return "Segoe UI"


def load_stylesheet(font_family: str) -> str:
    """Resolve the shared stylesheet independently of the working directory."""
    source = Path(__file__).with_name("application.qss").read_text(encoding="utf-8")
    directory = Path(__file__).parent
    numbers = (directory / "number-input.qss").read_text(encoding="utf-8")
    numbers = numbers.replace("__UP_PATH__", (directory / "chevron-up.svg").as_posix())
    numbers = numbers.replace("__DOWN_PATH__", (directory / "chevron-down.svg").as_posix())
    professional = (directory / "workspace.qss").read_text(encoding="utf-8")
    return graphite_stylesheet(source.replace("__APP_FONT__", font_family) + "\n" + numbers + "\n" + professional)


@lru_cache(maxsize=1)
def load_dropdown_stylesheet() -> str:
    return Path(__file__).with_name("dropdown.qss").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def load_dropdown_control_stylesheet() -> str:
    directory = Path(__file__).parent
    source = (directory / "dropdown-control.qss").read_text(encoding="utf-8")
    return source.replace("__CHEVRON_PATH__", (directory / "chevron-down.svg").as_posix())
