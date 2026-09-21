"""Two-series Qt trend plot used by the copied workspace."""
import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget
from .Theme import T
from python.app.widgets.PlotSurface import PlotSurface


class AxisTrendPlot(PlotSurface):
    def __init__(self, y_axis_label='', x_axis_label='', target_color=T.cyan, actual_color=T.orange, parent=None):
        super().__init__(parent)
        self.y_axis_label, self.x_axis_label = y_axis_label, x_axis_label
        self.colors = target_color, actual_color
        self.data = ([], [], [])

    def set_data(self, x, target, actual):
        self.data = list(x), list(target), list(actual)
        self.update()

    def clear(self):
        self.set_data([], [], [])

    def paint_chart(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(T.panel))
        rect = QRectF(65, 26, max(1,self.width()-80), max(1,self.height()-63))
        painter.setPen(QColor(T.muted))
        painter.drawText(QRectF(8,0,self.width()-16,23), Qt.AlignLeft, self.y_axis_label)
        painter.drawText(QRectF(60,self.height()-23,self.width()-75,23), Qt.AlignCenter, self.x_axis_label)
        x, a, b = self.data
        values = [v for series in (a,b) for v in series if math.isfinite(v)]
        finite_x = [v for v in x if math.isfinite(v)]
        low, high = (min(values),max(values)) if values else (0,1)
        pad = max((high-low)*.08, abs(high)*.001, 1e-6)
        low, high = low-pad, high+pad
        xmin, xmax = (min(finite_x),max(finite_x)) if finite_x else (0,1)
        xmax = max(xmax,xmin+1e-9)
        for i in range(5):
            y = rect.top()+rect.height()*i/4
            painter.setPen(QColor(T.border_soft))
            painter.drawLine(QPointF(rect.left(),y),QPointF(rect.right(),y))
            painter.setPen(QColor(T.muted))
            painter.drawText(QRectF(0,y-9,60,18),Qt.AlignRight,f'{high-(high-low)*i/4:.3g}')
        painter.drawText(QRectF(rect.left(),rect.bottom()+2,70,18),Qt.AlignLeft,f'{xmin:.2g}')
        painter.drawText(QRectF(rect.right()-70,rect.bottom()+2,70,18),Qt.AlignRight,f'{xmax:.2g}')
        painter.setClipRect(rect)
        for series,color in zip((a,b),self.colors):
            painter.setPen(QPen(QColor(color),1.6))
            points = QPolygonF()
            for t,v in zip(x,series):
                if math.isfinite(t) and math.isfinite(v):
                    points.append(QPointF(rect.left()+(t-xmin)/(xmax-xmin)*rect.width(),rect.bottom()-(v-low)/(high-low)*rect.height()))
                else:
                    painter.drawPolyline(points)
                    points = QPolygonF()
            painter.drawPolyline(points)
            for point in points:
                painter.drawEllipse(point,1.5,1.5)
