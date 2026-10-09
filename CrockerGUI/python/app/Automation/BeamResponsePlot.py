"""Beam feedback and TC command use separate, explicitly labelled axes."""
from PySide6.QtWidgets import QWidget, QFrame, QBoxLayout, QVBoxLayout
from python.app.Automation.GA.TrendPlot import AxisTrendPlot
from python.app.Automation.GA.CppTrendPlot import CppTrendPlot


class BeamResponsePlot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.samples = []
        self.target = 0.0
        self.trial_markers = []
        layout = QBoxLayout(QBoxLayout.LeftToRight, self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.beam = CppTrendPlot(AxisTrendPlot('Beam current (nA)', 'Time (s)'),
                                 ('Beam target', 'Measured beam'))
        self.coil = CppTrendPlot(AxisTrendPlot('TC CURRENT (A)', 'Time (s)'),
                                 ('TC command', 'TC actual'))
        beam_panel = QFrame()
        beam_panel.setObjectName('beamTrackingPanel')
        beam_panel.setStyleSheet('QFrame#beamTrackingPanel { background: #101d2d; border: 1px solid #2c4058; border-radius: 8px; }')
        beam_layout = QVBoxLayout(beam_panel)
        beam_layout.setContentsMargins(10, 10, 10, 10)
        self.error = CppTrendPlot(AxisTrendPlot('SIGNED ERROR', 'Time (s)'),
                                 ('Zero error', 'Target − measured'), display_y_label='Signed beam error (nA)', compact=True)
        self.error.setMinimumHeight(130)
        beam_layout.addWidget(self.beam, 2)
        beam_layout.addWidget(self.error, 1)
        layout.addWidget(beam_panel)
        coil_panel = QFrame()
        coil_panel.setObjectName('coilTrackingPanel')
        coil_panel.setStyleSheet('QFrame#coilTrackingPanel { background: #101d2d; border: 1px solid #2c4058; border-radius: 8px; }')
        coil_layout = QVBoxLayout(coil_panel)
        coil_layout.setContentsMargins(10, 10, 10, 10)
        coil_layout.addWidget(self.coil)
        layout.addWidget(coil_panel)

    def resizeEvent(self, event):
        stacked = self.width() < 760
        self.layout().setDirection(QBoxLayout.TopToBottom if stacked else QBoxLayout.LeftToRight)
        self.setMinimumHeight(650 if stacked else 340)
        super().resizeEvent(event)

    def set_samples(self, samples, target=None):
        self.samples = list(samples)
        rows = self.samples
        start = rows[0][0] if rows else 0
        x = [r[0]-start for r in rows]
        if target is None:
            self.beam.set_data(x, [r[2] for r in rows], [r[1] for r in rows])
            self.coil.set_data(x, [r[3] for r in rows],
                               [r[4] if len(r)>4 else float('nan') for r in rows])
        else:
            self.target = target
            self.beam.set_data(x, [target]*len(rows), [r[1] for r in rows])
            self.coil.set_data(x, [r[4] for r in rows],
                               [r[6] if len(r)>6 else float('nan') for r in rows])
        targets = [r[2] for r in rows] if target is None else [target]*len(rows)
        self.error.set_data(x, [0.0]*len(rows), [t-r[1] for t, r in zip(targets, rows)])
