"""BO-style presentation for C++ GA only; reuse the existing connected controls."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFrame,
    QScrollArea,
    QTabWidget,
    QDoubleSpinBox,
)
from python.app.widgets.AppDialogs import AppDialog as QDialog
from python.app.widgets.PidDialog import setup_pid_dialog


STYLE = '''
QWidget { color: #e5edf7; }
QLabel, QPushButton, QCheckBox, QAbstractSpinBox, QComboBox, QTabBar { font-family: "Segoe UI"; font-size: 13px; }
QFrame#cppGaPanel { background: #131f30; border: 1px solid #2b3b51; border-radius: 10px; }
QLabel { background: transparent; border: none; }
QPushButton { background: #1a2a40; border: 1px solid #3a4d66; border-radius: 6px; padding: 7px 12px; min-height: 0px; }
QPushButton:hover { background: #2c496a; }
QPushButton:disabled { color: #738197; border-color: #34465d; }
QDoubleSpinBox, QSpinBox, QComboBox { background: #192a40; color: #e7eef8; border: 1px solid #48668b; border-radius: 5px; padding: 5px; min-height: 0px; }
QTabBar::tab { background: #142235; padding: 8px 16px; }
QTabBar::tab:selected { background: #213954; color: #91d8ff; border-bottom: 2px solid #59b9f3; }
QTabWidget::pane { border: 1px solid #2b3b51; border-radius: 6px; }
QPushButton[role="primary"] { background: #2563eb; border-color: #477fed; color: white; font-weight: 600; }
QPushButton[role="primary"]:hover { background: #3473f2; }
QPushButton[role="danger"] { background: #30222e; color: #ffb2bc; border-color: #65404b; }
QPushButton[role="primary"]:disabled, QPushButton[role="danger"]:disabled { background: #182638; border-color: #2b3b51; color: #718299; }
QLabel[role="section"] { color: #8fa5c2; font-size: 11px; font-weight: 600; padding-top: 2px; }
QLabel[role="metric"] { color: #e4efff; font-size: 18px; font-weight: 600; }
QLabel[role="badge"] { background: #19354a; color: #9edaf8; border: 1px solid #31546d; border-radius: 6px; padding: 6px 12px; }
QLabel[role="status"] { background: #101a29; color: #aebfd4; border: 1px solid #293b52; border-radius: 6px; padding: 6px 10px; }
QCheckBox { spacing: 9px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #647b96; border-radius: 3px; background: #101a29; }
QCheckBox::indicator:checked { background: #2563eb; border-color: #80b4ff; }
QAbstractSpinBox:focus, QComboBox:focus { border-color: #60a5fa; }
QFrame#workspace { border: none; background: transparent; }

'''


def _use(widget):
    """Prepare a control; its destination layout owns parenting and visibility."""
    widget.setStyleSheet('')
    widget.setMinimumSize(0, 0)
    widget.setMaximumSize(16777215, 16777215)
    # New controls may have no parent yet. Showing here creates a transient
    # native window before addWidget/addTab reparents it, causing Windows
    # geometry warnings (and briefly flashing standalone editors).
    return widget


def _section(layout, title):
    label = QLabel(title)
    label.setProperty('role', 'section')
    layout.addWidget(label)


def style_cpp_shell(page, go_back, workspace_layout):
    """Replace the decorative shell with a compact C++-only app header."""
    page.setStyleSheet(STYLE)
    page.header.hide()
    back = page.findChild(QPushButton, 'navBackButton')
    if back is not None:
        back.hide()
        for i in range(page.layout.count()):
            item = page.layout.itemAt(i)
            nav = item.layout()
            if nav is not None and nav.indexOf(back) >= 0:
                page.layout.removeItem(nav)
                break
    header = QWidget()
    row = QHBoxLayout(header)
    row.setContentsMargins(24, 16, 24, 16)
    row.setSpacing(20)
    row.addWidget(_button('‹  Automation', go_back))
    text = QVBoxLayout()
    text.setSpacing(3)
    title = QLabel('PID control & gain tuning')
    title.setStyleSheet('font-family: "Segoe UI"; font-size: 22px; font-weight: 600; color: #edf4ff;')
    subtitle = QLabel('Beam-current control  /  C++ PID')
    subtitle.setStyleSheet('font-family: "Segoe UI"; font-size: 12px; color: #93a8c2;')
    text.addWidget(title)
    text.addWidget(subtitle)
    row.addLayout(text, 1)
    mode = QLabel('Simulation' if page.tuning_enabled else 'Preview only')
    mode.setProperty('role', 'badge')
    row.addWidget(mode)
    page.layout.insertWidget(0, header)
    workspace_layout.setContentsMargins(24, 0, 24, 18)
    workspace_layout.setSpacing(10)


def _panel():
    frame = QFrame()
    frame.setObjectName('cppGaPanel')
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 10, 14, 10)
    layout.setSpacing(7)
    return frame, layout


def _fields(layout, fields, columns=4):
    grid = QGridLayout()
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(6)
    for index, (name, widget) in enumerate(fields):
        row, column = divmod(index, columns)
        label = QLabel(name)
        label.setStyleSheet('color: #93a8c2; font-size: 12px;')
        grid.addWidget(label, row*2, column)
        grid.addWidget(_use(widget), row*2+1, column)
        grid.setColumnStretch(column, 1)
        if not isinstance(widget, QLabel):
            widget.setFixedHeight(34)
    layout.addLayout(grid)


def _actions(layout, *widgets):
    row = QHBoxLayout()
    for widget in widgets:
        row.addWidget(_use(widget))
        widget.setFixedHeight(36)
    row.addStretch()
    layout.addLayout(row)


def _button(text, callback):
    button = QPushButton(text)
    button.setFixedHeight(36)
    button.clicked.connect(callback)
    return button


def _dialog(w, title, groups):
    dialog = QDialog(w)
    layout = setup_pid_dialog(dialog, title, window_controls=False)
    tabs = QTabWidget()
    layout.addWidget(tabs)
    for name, fields in groups:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        contents = QVBoxLayout(body)
        _fields(contents, fields, columns=2)
        contents.addStretch()
        scroll.setWidget(body)
        tabs.addTab(scroll, name)
    layout.addWidget(_button('Close', dialog.close), 0, Qt.AlignRight)
    return dialog


def _open(dialog):
    title_bar = dialog.findChild(QFrame, 'dialogTitleBar')
    if title_bar is not None:
        for label in title_bar.findChildren(QLabel):
            label.setWordWrap(False)
    screen = dialog.screen().availableGeometry()
    dialog.resize(min(760, screen.width()-40), min(620, screen.height()-80))
    dialog.show()
    dialog.raise_()


def install_cpp_layout(w):
    from .CppTrendPlot import upgrade_cpp_plots
    upgrade_cpp_plots(w)
    # Keep unshown reference readouts alive: the shared controller still updates
    # them. Only C++ presentation is rearranged; Python keeps its original tabs.
    w._reference_pages = [w.control_tabs.widget(i) for i in range(w.control_tabs.count())]
    while w.control_tabs.count():
        w.control_tabs.removeTab(0)
    for page in w._reference_pages:
        page.hide()
    w.control_tabs.tabBar().hide()
    w.setStyleSheet(STYLE)

    w.settings_dialog = _dialog(w, 'Controller Settings and Output Limits', [
        ('Output limits', [('Minimum TC current (A)',w.tc_min_spin),('Maximum TC current (A)',w.tc_max_spin),
                           ('Beam freshness limit (s)',w.beam_stale_spin),('Control interval (ms)',w.loop_period_spin)]),
        ('Adaptive PID', [('Deadband (nA)',w.deadband_spin),('Trend tolerance (nA)',w.trend_tolerance_spin),
                          ('Direction window (s)',w.direction_check_spin),('Initial direction',w.initial_direction_combo),
                          ('Derivative filter (s)',w.derivative_tau_spin),('Integral behavior',w.reset_i_deadband_check),
                          ('Direction reversal',w.reset_i_reverse_check)]),
    ])
    w.ga_settings_dialog = _dialog(w, 'GA Evaluation and Recovery Settings', [
        ('Evaluation', [('Warm-up (s)',w.ga_warmup_spin),('Steady-state window (s)',w.ga_steady_window_spin),
                        ('Maximum TC excursion (A)',w.ga_max_excursion_spin),('Beam error abort (nA)',w.ga_max_beam_error_spin),
                        ('Beam loss threshold (nA)',w.ga_min_valid_beam_spin),('Saturation timeout (s)',w.ga_max_saturation_spin),
                        ('Maximum TC rate (A/s)',w.ga_max_tc_rate_spin)]),
        ('Recovery', [('Recovery channels',w.ga_recovery_scope_combo),('Capture reference',w.ga_capture_recovery_button),
                      ('Recovery step (A)',w.ga_restore_step_spin),('Measured TC tolerance (A)',w.ga_restore_tolerance_spin),
                      ('Beam reference tolerance (nA)',w.ga_baseline_beam_tolerance_spin),('Minimum recovered beam',w.ga_recovery_beam_fraction_spin),
                      ('Stable hold (s)',w.ga_restore_hold_spin),('Timeout (s)',w.ga_restore_timeout_spin),
                      ('Reference',w.ga_recovery_reference_display)]),
        ('Fitness weights', [('Tracking',w.ga_w_track_spin),('Steady state',w.ga_w_ss_spin),
                             ('Movement',w.ga_w_move_spin),('Saturation',w.ga_w_sat_spin),('Oscillation',w.ga_w_osc_spin)]),
        ('Manual scoring', [('Manual mode',w.manual_ga_mode_check),('Fitness',w.fitness_spin),('Submit',w.submit_fitness_button)]),
    ])

    pid = QWidget()
    pid_layout = QVBoxLayout(pid)
    pid_layout.setContentsMargins(0,0,0,0)
    pid_layout.setSpacing(12)
    heading = QHBoxLayout()
    title = QLabel('PID Control')
    title.setStyleSheet('font-size: 18px; font-weight: 600;')
    heading.addWidget(title,1)
    heading.addStretch()
    w.open_tuner_button = _button('Open GA Tuner', lambda: w.control_tabs.setCurrentIndex(1))
    heading.addWidget(w.open_tuner_button)
    pid_layout.addLayout(heading)
    panel, form = _panel()
    _section(form, 'CONTROL SETUP')
    _fields(form, [('Trim-coil actuator',w.actuator_selector),('Confirm selection',w.apply_actuator_button),
                   ('Beam setpoint (nA)',w.setpoint_spin),('Measured beam (nA)',w.actual_display)])
    _section(form, 'PID GAINS')
    _fields(form, [('Kp',w.kp_spin),('Ki',w.ki_spin),('Kd',w.kd_spin)],3)
    w.load_actual_button.setText('Use measured beam')
    w.capture_baseline_button.setText('Capture baseline')
    w.reset_button.setText('Reset PID')
    w.start_pid_button.setText('Start PID')
    w.settings_button = _button('Control Settings and Output Limits',lambda:_open(w.settings_dialog))
    _actions(form,w.load_actual_button,w.capture_baseline_button,w.reset_button,w.settings_button,w.start_pid_button)
    form.addWidget(_use(w.pid_status_label))
    pid_layout.addWidget(panel)
    plots = QTabWidget()
    for title,plot in [('Beam response',w.plot),('Absolute error',w.error_plot),('Trim-coil current',w.tc_plot)]:
        plots.addTab(_use(plot),title)
    pid_layout.addWidget(plots,1)

    ga = QWidget()
    ga_layout = QVBoxLayout(ga)
    ga_layout.setContentsMargins(0,0,0,0)
    ga_layout.setSpacing(10)
    heading = QHBoxLayout()
    title = QLabel('PID Gain Tuning — Genetic Algorithm')
    title.setStyleSheet('font-size: 18px; font-weight: 600;')
    heading.addWidget(title,1)
    heading.addStretch()
    w.back_to_pid_button = _button('Back to PID Control',lambda:w.control_tabs.setCurrentIndex(0))
    heading.addWidget(w.back_to_pid_button)
    ga_layout.addLayout(heading)
    panel,form = _panel()
    w.ga_target_input = QDoubleSpinBox()
    w.ga_target_input.setRange(w.setpoint_spin.minimum(),w.setpoint_spin.maximum())
    w.ga_target_input.setDecimals(w.setpoint_spin.decimals())
    w.ga_target_input.setValue(w.setpoint_spin.value())
    w.ga_target_input.valueChanged.connect(w.setpoint_spin.setValue)
    w.setpoint_spin.valueChanged.connect(w.ga_target_input.setValue)
    w._ga_config_widgets.append(w.ga_target_input)
    _section(form, 'SEARCH CONFIGURATION')
    _fields(form,[('Selected actuator',w.ga_channel_display),('Trial target (nA)',w.ga_target_input),
                  ('Population',w.population_spin),('Generations',w.generations_spin),('Trial duration (s)',w.ga_evaluation_spin)],5)
    _section(form, 'GAIN SEARCH BOUNDS')
    _fields(form,[('Kp minimum',w.kp_min_spin),('Kp maximum',w.kp_max_spin),
                  ('Ki minimum',w.ki_min_spin),('Ki maximum',w.ki_max_spin),
                  ('Kd minimum',w.kd_min_spin),('Kd maximum',w.kd_max_spin)],6)
    summary = QHBoxLayout()
    summary.addWidget(QLabel('Seed gains (Kp, Ki, Kd):'))
    summary.addWidget(_use(w.ga_seed_display),1)
    w.ga_settings_button = _button('Evaluation and Recovery Settings',lambda:_open(w.ga_settings_dialog))
    form.addLayout(summary)
    w.start_ga_button.setText('Start GA Search')
    w.apply_best_button.setText('Apply Best Gains')
    w.auto_ga_arm_check.setText('Arm automatic GA')
    _actions(form,w.auto_ga_arm_check,w.start_ga_button,w.apply_best_button,w.ga_settings_button)
    ga_layout.addWidget(panel)
    progress,progress_layout = _panel()
    _fields(progress_layout,[('Generation',w.ga_generation_display),('Candidate',w.ga_candidate_display),
                            ('Phase',w.ga_phase_display),('Best fitness / gains',w.ga_best_display)],4)
    ga_layout.addWidget(progress)
    plots = QTabWidget()
    for title,plot in [('Live beam response',w.ga_live_beam_plot),('Fitness history',w.ga_plot),
                       ('Absolute error',w.ga_live_error_plot),('Trim-coil current',w.ga_live_tc_plot)]:
        plots.addTab(_use(plot),title)
    ga_layout.addWidget(plots,1)
    ga_layout.addWidget(_use(w.ga_status_label))
    w.control_tabs.addTab(pid,'PID Control')
    w.control_tabs.addTab(ga,'GA Tuner')
    w.control_tabs.setCurrentIndex(0)

    w.arm_output_check.setText('Arm output')
    w.stop_pid_button.setText('Stop PID')
    w.abort_ga_button.setText('Abort GA + Restore')
    footer_panel, footer_outer = _panel()
    footer = QHBoxLayout()
    footer.setSpacing(14)
    footer_outer.addLayout(footer)
    w.channel_state_label = QLabel()
    w.enable_channel_button = _button('Enable selected coil',w.page.enable_selected_channel)
    w.enable_channel_button.setToolTip('Turn on and enable the confirmed trim coil at its current target. PID and GA remain stopped.')
    for widget in (w.channel_state_label,w.enable_channel_button,w.arm_output_check,w.stop_pid_button,w.abort_ga_button):
        footer.addWidget(_use(widget))
        widget.setFixedHeight(36)
    w.layout().setSpacing(12)
    w.layout().addWidget(footer_panel)
    for button in (w.start_pid_button, w.start_ga_button):
        button.setProperty('role', 'primary')
    for button in (w.stop_pid_button, w.abort_ga_button):
        button.setProperty('role', 'danger')
    for label in (w.ga_generation_display, w.ga_candidate_display, w.ga_phase_display, w.ga_best_display):
        label.setProperty('role', 'metric')
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    for label in (w.pid_status_label, w.ga_status_label):
        label.setProperty('role', 'status')
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    w.channel_state_label.setProperty('role', 'badge')
