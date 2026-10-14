"""Local theme helpers for the imported PID/GA workspace."""
from types import SimpleNamespace
from PySide6.QtWidgets import QFrame, QTabBar

T = SimpleNamespace(panel='#1a1c1f', border='#33363b', border_soft='#292c31',
                    text='#f3f3f4', muted='#a5a8ae', dim='#80858e', cyan='#c4c7cc',
                    cyan_bright='#f3f3f4', green='#66d99a', orange='#ffa65b',
                    amber='#f4cc65', red='#ff6b75')


class Card(QFrame):
    def __init__(self, radius=9, parent=None):
        super().__init__(parent)
        self.setObjectName('gaCard')
        self.setStyleSheet(f'QFrame#gaCard {{background:{T.panel}; border:1px solid {T.border}; border-radius:{radius}px;}}')


class TeslaTabBar(QTabBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f'QTabBar::tab {{border-radius:9px; margin-right:8px; margin-bottom:8px; padding:12px; color:{T.muted}; background:{T.panel};}} QTabBar::tab:selected {{color:{T.text}; border-bottom:2px solid #e82138;}}')


def info_label_css(color=T.muted):
    return f'color:{color}; padding:6px; font-size:11px;'


def secondary_button_css(color=T.cyan):
    return f'QPushButton {{color:{color}; border:1px solid {color}; border-radius:5px; padding:7px; background:{T.panel};}} QPushButton:disabled {{color:{T.dim}; border-color:{T.border};}}'
