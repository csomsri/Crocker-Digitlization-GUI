"""Interactive gain-space projection on an OpenGL-backed chart surface."""
import math
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from python.app.widgets.PlotSurface import PlotSurface


class GainCloud(PlotSurface):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid = {}
        self.yaw, self.pitch, self.zoom = -.65, .5, 1.
        self.drag = None
        self.setMinimumHeight(260)
        self.setToolTip('Drag to rotate. Scroll to zoom. Double-click to reset the view.')

    def reset_view(self):
        self.yaw, self.pitch, self.zoom = -.65, .5, 1.
        self.update()

    def paint_chart(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(QFont('Segoe UI', 9))
        p.fillRect(self.rect(), QColor('#0f172a'))
        grid = self.grid
        points = np.asarray(grid.get('points', []), dtype=float).reshape(-1, 3)
        if len(points):
            names = grid.get('parameter_names', ['kp', 'ki', 'kd'])
            points = points[:, [names.index(n) for n in ('kp', 'ki', 'kd')]]
        means = np.asarray(grid.get('mean', []), dtype=float)
        trials = np.asarray(grid.get('trials', []), dtype=float).reshape(-1, 3)
        best = grid.get('best')
        combined = [a for a in (points, trials) if len(a)]
        if best is not None:
            combined.append(np.asarray(best, dtype=float).reshape(1, 3))
        if not combined:
            p.setPen(QColor('#9db0c7'))
            p.drawText(self.rect(), Qt.AlignCenter, 'Waiting for gain-space observations')
            return
        all_points = np.concatenate(combined)
        all_points = all_points[np.isfinite(all_points).all(axis=1)]
        if not len(all_points):
            return
        low, high = all_points.min(axis=0), all_points.max(axis=0)
        span = np.maximum(high-low, 1e-12)
        cy, sy, cp, sp = math.cos(self.yaw), math.sin(self.yaw), math.cos(self.pitch), math.sin(self.pitch)
        scale = min(self.width()-100, self.height()-100)*.32*self.zoom
        def project(v):
            a, b, c = (np.asarray(v)-low)/span*2-1
            x, depth = cy*a-sy*b, sy*a+cy*b
            y, z = cp*c-sp*depth, sp*c+cp*depth
            return QPointF(self.width()*.5+x*scale, self.height()*.5-y*scale), z
        origin, _ = project(low)
        for axis, label in enumerate(('Kp', 'Ki', 'Kd')):
            end = low.copy(); end[axis] = high[axis]
            pt, _ = project(end)
            p.setPen(QPen(QColor('#647b96'), 1.2))
            p.drawLine(origin, pt)
            p.setPen(QColor('#dbe7f5'))
            p.drawText(QRectF(pt.x()-55, pt.y()-23, 130, 22), Qt.AlignCenter,
                       f'{label}: {low[axis]:.3g}–{high[axis]:.3g}')
        n = min(len(points), len(means))
        valid = [i for i in range(n) if np.isfinite(points[i]).all() and math.isfinite(means[i])]
        if valid:
            cmin, cmax = float(means[valid].min()), float(means[valid].max())
            for i in sorted(valid, key=lambda i: project(points[i])[1]):
                pt, _ = project(points[i])
                fraction = (means[i]-cmin)/max(1e-12, cmax-cmin)
                color = QColor.fromHsvF(.65*(1-fraction), .7, .95, .65)
                p.setPen(Qt.NoPen); p.setBrush(color)
                p.drawEllipse(pt, 2.8, 2.8)
            p.setPen(QColor('#b9cbe1'))
            p.drawText(QRectF(16, 10, self.width()-32, 24), Qt.AlignLeft,
                       f'Predicted cost: {cmin:.4g} (blue) → {cmax:.4g} (red)')
        p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor('#ffffff'), 2))
        for v in trials:
            if np.isfinite(v).all():
                pt, _ = project(v); p.drawEllipse(pt, 5, 5)
        if best is not None and np.isfinite(best).all():
            pt, _ = project(best)
            p.setPen(QPen(QColor('#ffbe32'), 3))
            p.drawLine(pt-QPointF(7, 0), pt+QPointF(7, 0))
            p.drawLine(pt-QPointF(0, 7), pt+QPointF(0, 7))
        p.setPen(QColor('#9db0c7'))
        p.drawText(QRectF(16, self.height()-28, self.width()-32, 22), Qt.AlignCenter,
                   '○ Tested gains    + Best observed result    • Predicted cost')

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag = event.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            delta = event.position()-self.drag
            self.yaw += delta.x()*.01
            self.pitch = max(-1.4, min(1.4, self.pitch+delta.y()*.01))
            self.drag = event.position()
            self.update()

    def mouseReleaseEvent(self, event):
        self.drag = None
        self.unsetCursor()

    def wheelEvent(self, event):
        self.zoom = max(.25, min(4., self.zoom*(1.1 if event.angleDelta().y()>0 else 1/1.1)))
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.reset_view()


class GainSurfaceWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet('color: #cbd5e1;')
        layout.addWidget(self.status)
        self.canvas = GainCloud(self)
        layout.addWidget(self.canvas, 1)
        reset = QPushButton('Reset view')
        reset.clicked.connect(self.canvas.reset_view)
        layout.addWidget(reset, 0, Qt.AlignRight)
        self.set_grid(None)

    def set_grid(self, grid):
        self.canvas.grid = grid or {}
        self.status.setText('All three gains vary. Drag to rotate; scroll to zoom. Color shows predicted cost.'
                            if grid and grid.get('ready') else
                            (grid or {}).get('message', 'Waiting for enough trials to fit the gain-space model.'))
        self.canvas.update()
