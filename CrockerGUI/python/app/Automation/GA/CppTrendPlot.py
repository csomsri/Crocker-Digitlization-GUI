"""Readable two-series charts for the C++ GA workspace only."""
import math
from html import escape
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPainterPath
from python.app.widgets.InlinePopups import InlineToolTip as QToolTip
from .TrendPlot import AxisTrendPlot


def _ticks(low, high, count=5):
    """Round axis limits to human-readable 1/2/5 intervals."""
    if high <= low:
        padding = max(abs(low)*.05, .01)
        low, high = low-padding, high+padding
    raw = (high-low)/count
    power = 10**math.floor(math.log10(raw))
    step = next((factor*power for factor in (1,2,5,10) if factor*power >= raw),10*power)
    start, stop = math.floor(low/step)*step, math.ceil(high/step)*step
    return [start+i*step for i in range(round((stop-start)/step)+1)]


def _number(value):
    if not math.isfinite(value):
        return '—'
    if value == 0:
        return '0'
    return f'{value:.4g}'


class CppTrendPlot(AxisTrendPlot):
    def __init__(self, source, labels, *, fitness=False, offset_provider=None):
        super().__init__(source.y_axis_label,source.x_axis_label,*source.colors)
        self.series_labels = labels
        self.fitness = fitness
        self.offset_provider = offset_provider
        self.data = tuple(list(series) for series in source.data)
        self._hover = None
        self._x_range = None
        self._drag = None
        self.setMouseTracking(True)
        self.setAccessibleName(' / '.join(labels))
        self.setAccessibleDescription('Dashed reference line and solid response line. Hover to inspect samples.')
        self.setToolTip('Scroll to zoom time. Drag to pan. Double-click to resume live autoscaling.')

    def _geometry(self):
        x,a,b = self.data
        values = [v for series in (a,b) for t,v in zip(x,series) if math.isfinite(t) and math.isfinite(v)
                  and (self._x_range is None or self._x_range[0] <= t <= self._x_range[1])]
        times = [t for t in x if math.isfinite(t)]
        low,high = (min(values),max(values)) if values else (0.,1.)
        pad = max((high-low)*.08,abs(high)*.000001,.000001)
        lower = max(0,low-pad) if self.fitness or 'ERROR' in self.y_axis_label else low-pad
        tick_count = max(2, min(5, (self.height()-108)//32))
        yticks = _ticks(lower,high+pad,tick_count) if values else _ticks(0,1,tick_count)
        xmin,xmax = (min(times),max(times)) if times else (0.,1.)
        if self.fitness:
            # Evaluation numbers are discrete; never label fractional trials.
            step = max(1,math.ceil((xmax-xmin)/6))
            start = math.floor(xmin)
            stop = start + max(1,math.ceil((xmax-start)/step))*step
            xticks = list(range(start,stop+1,step))
        else:
            xticks = _ticks(xmin,xmax,max(2,min(6,(self.width()-100)//90)))
        if self._x_range is not None:
            lo, hi = self._x_range
            xticks = [lo+(hi-lo)*i/4 for i in range(5)]
        font = QFont('Segoe UI')
        font.setPixelSize(12)
        metrics = QFontMetrics(font)
        label_width = max(metrics.horizontalAdvance(_number(v)) for v in yticks)
        left = max(72,label_width+22)
        top = 88 if self.width() < 540 else 64
        rect = QRectF(left,top,max(1,self.width()-left-32),max(1,self.height()-top-44))
        return rect,xticks,yticks,bool(values)

    def paint_chart(self,event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        font = QFont('Segoe UI')
        font.setPixelSize(12)
        p.setFont(font)
        p.fillRect(self.rect(),QColor('#101a29'))
        rect,xticks,yticks,has_data = self._geometry()
        x,a,b = self.data
        offset = self.offset_provider() if self.offset_provider else 0
        ylabel = ('Fitness score' if self.fitness else
                  'Absolute error (nA)' if 'ERROR' in self.y_axis_label else
                  'Trim-coil current (A)' if 'TC CURRENT' in self.y_axis_label else
                  'Beam current (nA)')
        if offset:
            ylabel += f'  (axis values + {_number(offset)})'
        p.setPen(QColor('#dce7f5'))
        p.drawText(QRectF(18,8,self.width()-36,22),Qt.AlignLeft | Qt.AlignVCenter,ylabel)
        # Always-visible legends also show the latest finite value for each line.
        legend_x = 18
        for index,(label,series,color) in enumerate(zip(self.series_labels,(a,b),self.colors)):
            legend_y = 46 + (24*index if self.width() < 540 else 0)
            if self.width() < 540:
                legend_x = 18
            p.setPen(QPen(QColor(color),2.2,Qt.DashLine if index == 0 else Qt.SolidLine))
            p.drawLine(QPointF(legend_x,legend_y),QPointF(legend_x+28,legend_y))
            last = next((v for t,v in reversed(list(zip(x,series))) if math.isfinite(t) and math.isfinite(v)),None)
            text = f'{label}: {_number(last+offset) if last is not None else "—"}'
            p.setPen(QColor('#cbd8e9'))
            width = p.fontMetrics().horizontalAdvance(text)+16
            p.drawText(QRectF(legend_x+36,legend_y-12,width,24),Qt.AlignVCenter,text)
            legend_x += width+60
        xmin,xmax = xticks[0],xticks[-1]
        ymin,ymax = yticks[0],yticks[-1]
        def point(t,v):
            return QPointF(rect.left()+(t-xmin)/(xmax-xmin)*rect.width(),rect.bottom()-(v-ymin)/(ymax-ymin)*rect.height())
        p.fillRect(rect,QColor('#111f30'))
        for v in yticks:
            y=point(xmin,v).y()
            p.setPen(QPen(QColor('#293b50'),1))
            p.drawLine(QPointF(rect.left(),y),QPointF(rect.right(),y))
            p.setPen(QColor('#9db0c7'))
            p.drawText(QRectF(4,y-10,rect.left()-14,20),Qt.AlignRight | Qt.AlignVCenter,_number(v))
        for t in xticks:
            px=point(t,ymin).x()
            p.setPen(QPen(QColor('#203247'),1))
            p.drawLine(QPointF(px,rect.top()),QPointF(px,rect.bottom()))
            p.setPen(QColor('#9db0c7'))
            p.drawText(QRectF(px-40,rect.bottom()+6,80,20),Qt.AlignCenter,_number(t))
        p.drawText(QRectF(rect.left(),self.height()-24,rect.width(),20),Qt.AlignCenter,
                   'Evaluation number' if self.fitness else 'Elapsed time (s)')
        if not has_data:
            p.setPen(QColor('#9db0c7'))
            p.drawText(rect,Qt.AlignCenter,'No evaluations yet' if self.fitness else 'Waiting for response data')
            return
        p.save()
        p.setClipRect(rect.adjusted(-3,-3,3,3))
        for index,(series,color) in enumerate(zip((a,b),self.colors)):
            p.setPen(QPen(QColor(color),2.2,Qt.DashLine if index == 0 else Qt.SolidLine))
            path=QPainterPath()
            connected=False
            dots=[]
            for t,v in zip(x,series):
                if not math.isfinite(t) or not math.isfinite(v):
                    connected=False
                    continue
                pt=point(t,v)
                if connected: path.lineTo(pt)
                else: path.moveTo(pt)
                connected=True
                dots.append(pt)
            p.drawPath(path)
            p.setBrush(QColor(color))
            if self.fitness or len(dots)==1:
                for pt in dots: p.drawEllipse(pt,3,3)
            if dots: p.drawEllipse(dots[-1],3.5,3.5)
            p.setBrush(Qt.NoBrush)
        if self._hover is not None and self._hover < len(x):
            i=self._hover
            if math.isfinite(x[i]):
                px=point(x[i],ymin).x()
                p.setPen(QPen(QColor('#9db0c7'),1,Qt.DotLine))
                p.drawLine(QPointF(px,rect.top()),QPointF(px,rect.bottom()))
                for series,color in zip((a,b),self.colors):
                    if i<len(series) and math.isfinite(series[i]):
                        p.setPen(QPen(QColor(color),2))
                        p.drawEllipse(point(x[i],series[i]),5,5)
        p.restore()

    def mouseMoveEvent(self,event):
        rect,xticks,_,_ = self._geometry()
        if self._drag is not None:
            start, lo, hi = self._drag
            shift = (event.position().x()-start)/rect.width()*(hi-lo)
            self._x_range = (lo-shift, hi-shift)
            self.update()
            return
        if not rect.contains(event.position()):
            self.leaveEvent(event)
            return
        x,a,b=self.data
        t=xticks[0]+(event.position().x()-rect.left())/rect.width()*(xticks[-1]-xticks[0])
        indices=[i for i,v in enumerate(x) if math.isfinite(v)]
        if not indices: return
        self._hover=min(indices,key=lambda i:abs(x[i]-t))
        i=self._hover
        offset=self.offset_provider() if self.offset_provider else 0
        rows=[f'{"Evaluation" if self.fitness else "Time (s)"}: {_number(x[i])}']
        rows += [f'{escape(label)}: {_number(series[i]+offset)}' for label,series in zip(self.series_labels,(a,b)) if i<len(series)]
        QToolTip.showText(event.globalPosition().toPoint(),'<br>'.join(rows),self)
        self.update()

    def wheelEvent(self, event):
        rect, ticks, _, _ = self._geometry()
        if not rect.contains(event.position()):
            event.ignore()
            return
        fraction = (event.position().x()-rect.left())/rect.width()
        lo, hi = ticks[0], ticks[-1]
        center = lo+fraction*(hi-lo)
        span = max(1e-6, min(1e9, (hi-lo)*(.8 if event.angleDelta().y() > 0 else 1.25)))
        self._x_range = (center-fraction*span, center+(1-fraction)*span)
        self.update()
        event.accept()

    def mousePressEvent(self, event):
        rect, ticks, _, _ = self._geometry()
        if event.button() == Qt.LeftButton and rect.contains(event.position()):
            self._drag = (event.position().x(), ticks[0], ticks[-1])
            self.setCursor(Qt.ClosedHandCursor)

    def mouseReleaseEvent(self, event):
        self._drag = None
        self.unsetCursor()

    def mouseDoubleClickEvent(self, event):
        self._x_range = None
        self._drag = None
        self.unsetCursor()
        self.update()

    def clear(self):
        self._x_range = None
        self._hover = None
        super().clear()

    def leaveEvent(self,event):
        self._hover=None
        QToolTip.hideText()
        self.update()


def upgrade_cpp_plots(w):
    specs = {
        'plot': ('Setpoint','Measured beam'),
        'error_plot': ('Deadband','Absolute error'),
        'tc_plot': ('Commanded current','Measured current'),
        'ga_live_beam_plot': ('Setpoint','Measured beam'),
        'ga_live_error_plot': ('Deadband','Absolute error'),
        'ga_live_tc_plot': ('Commanded current','Measured current'),
        'ga_plot': ('Best so far','Candidate fitness'),
    }
    for name,labels in specs.items():
        old=getattr(w,name)
        plot=CppTrendPlot(old,labels,fitness=name=='ga_plot',
                          offset_provider=(lambda:w._ga_plot_offset) if name=='ga_plot' else None)
        old.hide()
        setattr(w,name,plot)
