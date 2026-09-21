"""Shared themed window surface for PID tools."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QSizeGrip
from python.app.widgets.DialogTitleBar import DialogTitleBar
from pathlib import Path


def setup_pid_dialog(dialog, title, *, window_controls=True, resize_grip=True):
    dialog.setWindowTitle(title)
    dialog.setWindowFlag(Qt.FramelessWindowHint, True)
    dialog.setAttribute(Qt.WA_TranslucentBackground)
    dialog.setObjectName('pidToolDialog')
    dialog.setStyleSheet('''
        QDialog#pidToolDialog { background: transparent; }
        QFrame#pidToolSurface { background: #101a29; border: 1px solid #48668b; border-radius: 12px; }
        QFrame#dialogTitleBar { background: #243e60; border: none; border-radius: 7px; }
        QFrame#dialogTitleBar QLabel { color: #f0f5fc; font-family: "Segoe UI"; font-size: 14px; font-weight: 600; }
        QPushButton#dialogWindowControl { background: #d4e1f2; border: 1px solid #91aacb; border-radius: 4px; padding: 0; }
        QPushButton#dialogWindowControl:hover { background: #ffffff; }
        QLabel { color: #cbd5e1; font-family: "Segoe UI"; font-size: 13px; }
        QDateEdit, QSpinBox { background: #192a40; color: #e7eef8; border: 1px solid #3b526e;
            border-radius: 5px; padding: 0 10px; font-family: "Segoe UI"; font-size: 13px; }
        QDateEdit::drop-down { width: 24px; border-left: 1px solid #3b526e; }
        QTableWidget { background: #142235; alternate-background-color: #1b2c42; color: #e7eef8;
            selection-background-color: #315477; border: 1px solid #34465d; }
        QHeaderView::section { background: #24364c; color: #b9cce1; padding: 8px; border: none; }
    ''')
    icons = Path(__file__).resolve().parents[1] / 'theme'
    dialog.setStyleSheet(dialog.styleSheet() +
        f'QDateEdit::down-arrow, QSpinBox::down-arrow {{ image: url("{(icons / "chevron-down.svg").as_posix()}"); width: 10px; height: 6px; }}'
        f'QSpinBox::up-arrow {{ image: url("{(icons / "chevron-up.svg").as_posix()}"); width: 10px; height: 6px; }}')
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(4, 4, 4, 4)
    surface = QFrame()
    surface.setObjectName('pidToolSurface')
    outer.addWidget(surface)
    frame = QVBoxLayout(surface)
    frame.setContentsMargins(8, 8, 8, 4)
    frame.addWidget(DialogTitleBar(dialog, title, window_controls=window_controls))
    content = QVBoxLayout()
    content.setContentsMargins(8, 8, 8, 0)
    content.setSpacing(12)
    frame.addLayout(content, 1)
    footer = QHBoxLayout()
    footer.addStretch()
    if resize_grip:
        footer.addWidget(QSizeGrip(dialog))
    frame.addLayout(footer)
    return content
