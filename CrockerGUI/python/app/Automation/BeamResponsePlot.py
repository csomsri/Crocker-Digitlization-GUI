"""Beam feedback and TC command use separate, explicitly labelled axes."""
from PySide6.QtWidgets import QWidget, QBoxLayout
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
        layout.addWidget(self.beam)
        layout.addWidget(self.coil)

    def resizeEvent(self, event):
        stacked = self.width() < 760
        self.layout().setDirection(QBoxLayout.TopToBottom if stacked else QBoxLayout.LeftToRight)
        self.setMinimumHeight(380 if stacked else 200)
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
