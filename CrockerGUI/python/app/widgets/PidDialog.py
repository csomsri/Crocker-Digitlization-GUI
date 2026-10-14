"""Shared themed window surface for PID tools."""
from python.app.theme.palette import graphite_stylesheet
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QSizeGrip, QPushButton
from python.app.widgets.DialogTitleBar import DialogTitleBar
from pathlib import Path


def setup_pid_dialog(dialog, title, *, window_controls=True, resize_grip=True):
    dialog.setWindowTitle(title)
    dialog.setWindowFlag(Qt.FramelessWindowHint, True)
    dialog.setAttribute(Qt.WA_TranslucentBackground)
    dialog.setObjectName('pidToolDialog')
    dialog.setStyleSheet('''
        QDialog#pidToolDialog { background: transparent; }
        QFrame#pidToolSurface { background: #1a1c1f; border: 1px solid #41444a; border-radius: 12px; }
        QFrame#dialogTitleBar { background: #23262a; border: none; border-radius: 7px; }
        QFrame#dialogTitleBar QLabel { color: #f0f5fc; font-family: "Segoe UI"; font-size: 14px; font-weight: 600; }
        QPushButton#dialogWindowControl { background: #d4e1f2; border: 1px solid #91aacb; border-radius: 4px; padding: 0; }
        QPushButton#dialogWindowControl:hover { background: #ffffff; }
        QLabel { color: #c4c7cc; font-family: "Segoe UI"; font-size: 13px; }
        QDateEdit, QSpinBox { background: #111214; color: #e7eef8; border: 1px solid #3b526e;
            border-radius: 5px; padding: 0 10px; font-family: "Segoe UI"; font-size: 13px; }
        QDateEdit::drop-down { width: 24px; border-left: 1px solid #3b526e; }
        QTableWidget { background: #23262a; alternate-background-color: #23262a; color: #e7eef8;
            selection-background-color: #36383d; border: 1px solid #33363b; }
        QHeaderView::section { background: #23262a; color: #b9cce1; padding: 8px; border: none; }
    ''')
    icons = Path(__file__).resolve().parents[1] / 'theme'
    dialog.setStyleSheet(dialog.styleSheet() +
        f'QDateEdit::down-arrow, QSpinBox::down-arrow {{ image: url("{(icons / "chevron-down.svg").as_posix()}"); width: 10px; height: 6px; }}'
        f'QSpinBox::up-arrow {{ image: url("{(icons / "chevron-up.svg").as_posix()}"); width: 10px; height: 6px; }}')
    dialog.setStyleSheet(dialog.styleSheet() + (icons / 'dialogs.qss').read_text(encoding='utf-8'))
    dialog.setStyleSheet(graphite_stylesheet(dialog.styleSheet()))
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(4, 4, 4, 4)
    surface = QFrame()
    surface.setObjectName('pidToolSurface')
    outer.addWidget(surface)
    frame = QVBoxLayout(surface)
    frame.setContentsMargins(8, 8, 8, 4)
    frame.addWidget(DialogTitleBar(dialog, title, window_controls=window_controls))
    content = QVBoxLayout()
    content.setContentsMargins(16, 12, 16, 12)
    content.setSpacing(12)
    frame.addLayout(content, 1)
    footer = QHBoxLayout()
    owner = dialog.parentWidget()
    if owner is not None and type(owner).__name__ == 'PidControlPage' and hasattr(owner, 'cruise'):
        # Modal overlays cover the workspace controls. Keep Stop reachable in
        # every PID tool, including history, metrics and hardware-profile editors.
        stop = QPushButton('Stop control')
        stop.setObjectName('pidCruiseDialogStop')
        stop.setAutoDefault(False)
        stop.setToolTip('Stop PID / BO and disable the selected output')
        def stop_control():
            owner._stop_cruise()
            dialog.reject()
        stop.clicked.connect(stop_control)
        footer.addWidget(stop)
    footer.addStretch()
    if resize_grip:
        footer.addWidget(QSizeGrip(dialog))
    frame.addLayout(footer)
    return content
