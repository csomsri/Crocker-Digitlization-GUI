"""Local theme helpers for the imported PID/GA workspace."""
from types import SimpleNamespace
from PySide6.QtWidgets import QFrame, QTabBar

T = SimpleNamespace(panel='#15191e', border='#39414b', border_soft='#292f38',
                    text='#e8edf2', muted='#a5afbb', dim='#778391', cyan='#52cce8',
                    cyan_bright='#7ce5ff', green='#66d99a', orange='#ffa65b',
                    amber='#f4cc65', red='#ff6b75')


class Card(QFrame):
    def __init__(self, radius=9, parent=None):
        super().__init__(parent)
        self.setObjectName('gaCard')
        self.setStyleSheet(f'QFrame#gaCard {{background:{T.panel}; border:1px solid {T.border}; border-radius:{radius}px;}}')


class TeslaTabBar(QTabBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f'QTabBar::tab {{padding:12px; color:{T.muted}; background:{T.panel};}} QTabBar::tab:selected {{color:{T.cyan}; border-bottom:2px solid {T.cyan};}}')


def info_label_css(color=T.muted):
    return f'color:{color}; padding:6px; font-size:11px;'


def secondary_button_css(color=T.cyan):
    return f'QPushButton {{color:{color}; border:1px solid {color}; border-radius:5px; padding:7px; background:{T.panel};}} QPushButton:disabled {{color:{T.dim}; border-color:{T.border};}}'
