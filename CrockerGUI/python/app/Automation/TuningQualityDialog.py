"""Editable, persistent performance thresholds, separate from actuator safety."""
import math
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QLabel, QFormLayout, QDoubleSpinBox, QSpinBox, QPushButton
from python.app.widgets.AppDialogs import AppDialog
from python.app.widgets.PidDialog import setup_pid_dialog
from source.Python.Optimization.trial_metrics import TuningQuality


class TuningQualityDialog(AppDialog):
    def __init__(self, parent, unit, *, beam=True):
        super().__init__(parent)
        self.resize(680, 480)
        self.settings = QSettings('Crocker Nuclear Lab', 'Digitalization')
        self.prefix = f'tuning_quality/{type(parent).__name__}/'
        self.defaults = TuningQuality() if beam else TuningQuality(0.1, 0.5, 0.1, 1.0, 2)
        layout = setup_pid_dialog(self, 'Tuning quality settings', window_controls=False, resize_grip=False)
        note = QLabel('Changes apply to the next tuning session. These settings judge response quality; '
                      'they do not change hardware abort limits. Final gain validation remains at least 60 seconds.')
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        form.setSpacing(12)
        self.inputs = {}
        fields = [
            ('settling_tolerance', 'Settling tolerance floor (+/-)', unit, 0.01, 10.0),
            ('hold_seconds', 'Continuous settling hold', 's', 0.5, 30.0),
            ('oscillation_amplitude', 'Oscillation amplitude', unit, 0.01, 10.0),
            ('oscillation_min_seconds', 'Observation time before rejection', 's', 1.0, 120.0),
            ('oscillation_min_cycles', 'Persistent cycles before rejection', 'cycles', 2, 20),
        ]
        for key, label, suffix, low, high in fields:
            control = QSpinBox() if key.endswith('cycles') else QDoubleSpinBox()
            control.setRange(low, high)
            control.setSuffix(' ' + suffix)
            if isinstance(control, QDoubleSpinBox):
                control.setDecimals(2)
                control.setSingleStep(0.01 if suffix == unit else 0.5)
            default = getattr(self.defaults, key)
            try:
                value = float(self.settings.value(self.prefix + key, default))
            except (ValueError, TypeError):
                value = default
            if not math.isfinite(value):
                value = default
            control.setValue(int(value) if key.endswith('cycles') else value)
            control.setKeyboardTracking(False)
            control.setAccessibleName(label)
            control.valueChanged.connect(lambda value, key=key: self.settings.setValue(self.prefix + key, value))
            self.inputs[key] = control
            form.addRow(label, control)
        layout.addLayout(form)
        explanation = QLabel('Effective settling tolerance is the largest of this floor, 1% of the target, '
                             'and controller deadband. Oscillation amplitude is half the peak-to-peak swing and uses its own threshold.')
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        close = QPushButton('Done')
        close.setAutoDefault(False)
        close.clicked.connect(self.accept)
        layout.addWidget(close, 0, Qt.AlignRight)

    def snapshot(self):
        return TuningQuality(**{key: control.value() for key, control in self.inputs.items()})
