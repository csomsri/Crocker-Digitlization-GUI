"""Persistent navigation for the live workspace and its engineering tools."""
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget, QPushButton, QTabBar, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy


class CruiseNavigation(QWidget):
    def __init__(self, page, back):
        super().__init__(page)
        self.page = page
        self.setObjectName('cruiseNavigation')
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.setStyleSheet('''
            QWidget#cruiseNavigation { background: #101d2d; }
            QWidget#cruiseNavigation QPushButton { color: #b8cbe1; background: transparent;
                border: 1px solid transparent; border-radius: 5px; padding: 9px 12px; }
            QWidget#cruiseNavigation QPushButton:hover { background: #1d324b; }
            QWidget#cruiseNavigation QPushButton:checked { background: #1d324b; color: #edf4fc; border-color: #486c96; }
            QWidget#cruiseNavigation QLabel { color: #cbd5e1; font-family: 'Segoe UI'; font-size: 12px; }
            QWidget#cruiseNavigation QTabBar::tab { background: #132236; color: #cbd5e1;
                border: 1px solid #334155; padding: 8px 12px; font-family: 'Segoe UI'; font-size: 12px; }
            QWidget#cruiseNavigation QTabBar::tab:selected { background: #244669; color: white; border-bottom: 2px solid #60a5fa; }
            QWidget#cruiseNavigation QTabBar::tab:hover { background: #1d324b; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        row = QHBoxLayout()
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(6)
        back.setText('Automation')
        back.setFixedSize(154, 36)
        row.addWidget(back)
        self.status = QLabel()
        self.status.setWordWrap(True)
        row.addStretch(1)
        self.targets, self.actions = [], []
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setAccessibleName('Automation sections')
        if hasattr(page, 'cruise_workspace'):
            self.add_tab('Overview', page.cruise_workspace, page._show_pid_control)
        self.add_tab('PID Control', page._advanced_control_page,
                     lambda: page.page_stack.setCurrentWidget(page._advanced_control_page))
        self.tuning_tab_index = len(self.targets)
        self.tuning_tab_label = ('Auto Tune · GA + BO' if getattr(page, 'engine_kind', None) == 'hybrid_cpp'
                                 else 'Auto Tune · BO')
        self.add_tab(self.tuning_tab_label, page.tuner_page, page._show_tuner)
        self.add_tab('Results', page.results_page, page._show_tuning_history)
        self.tabs.currentChanged.connect(self.activate)
        stop = QPushButton('Stop control')
        stop.clicked.connect(self.stop)
        stop.setToolTip('Stop PID and BO from any section')
        row.addWidget(stop)
        layout.addLayout(row)
        layout.addWidget(self.tabs)
        layout.addWidget(self.status)
        self.shortcuts = []
        for sequence, delta in (('Ctrl+Tab', 1), ('Ctrl+Shift+Tab', -1)):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(lambda d=delta: self.tabs.setCurrentIndex(
                (self.tabs.currentIndex() + d) % self.tabs.count()))
            self.shortcuts.append(shortcut)
        page.page_stack.currentChanged.connect(self.refresh)
        self.refresh()

    def add_tab(self, label, target, action):
        self.tabs.addTab(label)
        self.targets.append(target)
        self.actions.append(action)

    def activate(self, index):
        if index >= 0:
            self.actions[index]()

    def stop(self):
        if hasattr(self.page, 'cruise_workspace'):
            self.page._stop_cruise()
        else:
            self.page._stop_tuning_session()
            self.page._stop_pid('Stopped by operator')

    def refresh(self, index=None):
        # Derived workspaces can wrap/replace the tuner after base construction.
        # Track the section by its stable tab index, then resolve its current host.
        self.targets[self.tuning_tab_index] = self.page.tuner_page
        target = self.page.page_stack.currentWidget()
        if target in self.targets:
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(self.targets.index(target))
            self.tabs.blockSignals(False)
        running = self.page.tuning_session_active
        self.tabs.setTabText(self.tuning_tab_index,
                            self.tuning_tab_label + (' • Running' if running else ''))
        state = 'Auto tuning' if running else 'PID running' if self.page.pid_enabled else 'Idle'
        self.status.setText(f'{state} · Setpoint {self.page.setpoint_input.value():g} {self.page.feedback_unit}')
