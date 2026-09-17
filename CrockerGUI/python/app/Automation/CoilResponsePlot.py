"""Coil traces rendered by the existing native OpenGL time-series chart."""
import math
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QSizePolicy
from python.app.widgets.MagneticFieldWidgets import TimeDomainPlot


class CoilResponsePlot(TimeDomainPlot):
    def paintGL(self):
        super().paintGL()
        if self._ready and len(self.samples) > 1 and self.trial_markers:
            painter = QPainter(self)
            painter.setPen(QPen(QColor('#cbd5e1'), 1, Qt.DashLine))
            start, end = self.samples[0][0], self.samples[-1][0]
            ratio = self.devicePixelRatioF()
            left, right = 54/ratio, self.width()-20/ratio
            for stamp, label in self.trial_markers:
                if start <= stamp <= end and end > start:
                    x = left+(stamp-start)/(end-start)*(right-left)
                    painter.drawLine(QPointF(x, 38/ratio), QPointF(x, self.height()-54/ratio))
                    painter.drawText(QPointF(x+4, 50/ratio), label.split(':')[0])
            painter.end()
        if self._ready and not self._samples:
            painter = QPainter(self)
            painter.setPen(QColor('#cbd5e1'))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             'Waiting for response samples - start a trial to display coil currents')
            painter.end()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.coil_response = True
        self.samples = []
        self.target = 0.0
        self.trial_markers = []
        self.setMinimumHeight(160)
        self.setMaximumHeight(16777215)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_samples(self, samples, target=None):
        if target is None:
            # PID page: time, actual, target, commanded current.
            rows = [row for row in samples if all(math.isfinite(v) for v in row)]
        else:
            self.target = target
            self.setToolTip('Continuous session response; rolling 120-second window.\n' +
                            '\n'.join(f'{t:.1f}s: {label}' for t, label in self.trial_markers))
            self.samples = [r for r in samples if len(r) >= 6 and all(math.isfinite(r[i]) for i in (0, 1, 4))]
            rows = [(r[0], r[1], target, r[4]) for r in self.samples]
        # Shift before float conversion in the native binding to retain precision.
        start = rows[0][0] if rows else 0
        super().set_samples([(r[0]-start, *r[1:]) for r in rows])
