"""Persistent navigation for the live workspace and its engineering tools."""
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QPushButton, QTabBar, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QScrollArea
from python.app.widgets.AppDialogs import AppDialog
from python.app.widgets.PidDialog import setup_pid_dialog


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
        self.tabs.setFocusPolicy(Qt.StrongFocus)
        self.tabs.setAccessibleName('Automation sections')
        if hasattr(page, 'cruise_workspace'):
            self.add_tab('Overview', page.cruise_workspace, page._show_pid_control)
        self.add_tab('Live control' if not hasattr(page, 'cruise_workspace') else 'PID settings', page._advanced_control_page,
                     lambda: page.page_stack.setCurrentWidget(page._advanced_control_page))
        self.tuning_tab_index = len(self.targets)
        self.tuning_tab_label = ('Auto Tune · GA + BO' if getattr(page, 'engine_kind', None) == 'hybrid_cpp'
                                 else 'Auto Tune · BO')
        self.add_tab(self.tuning_tab_label, page.tuner_page, page._show_tuner)
        self.add_tab('Trial history', page.results_page, page._show_tuning_history)
        self.tabs.currentChanged.connect(self.activate)
        stop = QPushButton('Stop control')
        stop.clicked.connect(self.stop)
        stop.setToolTip('Stop PID and BO from any section')
        self.help_button = QPushButton('How to use')
        self.help_button.setAccessibleName('How to use PID tuning')
        self.help_button.clicked.connect(self.show_help)
        row.addWidget(self.help_button)
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

    def show_help(self):
        hybrid = getattr(self.page, 'engine_kind', None) == 'hybrid_cpp'
        if not hasattr(self, 'help_dialog'):
            self.help_dialog = AppDialog(self)
            layout = setup_pid_dialog(self.help_dialog, 'How to use Hybrid tuning' if hybrid else 'How to use BO tuning', window_controls=False)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            label = QLabel()
            label.setWordWrap(True)
            label.setTextFormat(Qt.RichText)
            label.setMargin(16)
            label.setText(
                '<h3>1. Set up the response</h3><p>Check the connection and fresh feedback. Select the trim coil '
                'and beam target. Check the feedback units and whether Dry Run is selected; Dry Run does not '
                'measure the physical response.</p>'
                '<h3>2. Configure the search</h3><p>' +
                ('Open Auto Tune · GA + BO. Set the trial budget and open Tuning settings for gain ranges and trial duration. '
                 'Exploration settings controls GA and the measured handover to BO.' if hybrid else
                 'Open Auto Tune · BO. Set the trial budget, duration and minimum/maximum Kp, Ki and Kd. '
                 'The budget is the number of trials; duration is the measurement window for each trial.') +
                '</p><h3>3. Run and monitor</h3><p>' +
                ('Press START TUNING. Search progress shows GA exploration and BO refinement. '
                 'Live trial response shows measured feedback and coil output.' if hybrid else
                 'Press Run trial budget for an automatic search. For individual trials, use Prepare session, '
                 'then Run Proposed Trial. Progress and the measured response appear below the setup controls.') +
                ' Stop control remains available above every page. Changing tabs does not stop a run.</p>'
                '<h3>4. Review, validate and apply</h3><p>Open Trial history to compare measured costs '
                '(lower is better), gains, status and timestamps.' +
                (' Results and history also shows Hybrid handover decisions.' if hybrid else '') +
                ' Choose Validate best gains, inspect the response, then Apply Settings to PID when enabled. '
                'A best observed trial is not yet an approved result. Applying gains updates the live PID settings.</p>'
                '<h3>5. Save results</h3><p>Export trial history as CSV. For recorded traces and SQLite trial IDs, '
                'follow HowToReadDataBase.md in the CrockerGUI folder. Compare runs with the same target, '
                'trial window and scoring version.</p>'
                '<p><b>Keyboard:</b> Ctrl+Tab / Ctrl+Shift+Tab switches main sections. '
                'Tab / Shift+Tab moves through controls; arrow keys change the selected tab.</p>')
            scroll.setWidget(label)
            layout.addWidget(scroll, 1)
            close = QPushButton('Done')
            close.clicked.connect(self.help_dialog.close)
            layout.addWidget(close, 0, Qt.AlignRight)
            self.help_dialog.resize(660, 600)
        self.help_dialog.show()
        self.help_dialog.raise_()

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
