"""Measured GA/BO comparison with selectable trial markers."""
import math
from statistics import mean
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget, QToolTip

GA_COLOR = '#75baff'
BO_COLOR = '#bc96ff'

def trial_method(source):
    if source in ('GA', 'GA parent'):
        return 'GA'
    if source in ('BO', 'BO challenger', 'BO refinement'):
        return 'BO'
    return None

class HybridCostPlot(QWidget):
    trialSelected = Signal(int)

    def __init__(self, records, parent=None, *, compact=False):
        super().__init__(parent)
        self.records = records
        self.compact = compact
        self.hits = []
        self.series = {'GA': [], 'BO': []}
        self.selected_trial = None
        self.setMinimumSize(260, 230)
        self.setMouseTracking(True)
        self.setAccessibleName('GA and BO measured cost comparison')

    def _nearest(self, position):
        hit = min(self.hits, key=lambda h: (h[0]-position).manhattanLength(), default=None)
        return hit if hit and (hit[0]-position).manhattanLength() < 18 else None

    def mouseMoveEvent(self, event):
        hit = self._nearest(event.position())
        if hit:
            r = hit[1]
            gains = ' · '.join(f'{n}: {r.get(n, "—")}' for n in ('kp','ki','kd'))
            QToolTip.showText(event.globalPosition().toPoint(),
                f'Trial {r["trial"]} · {r["source"]}\nCost: {r.get("cost")} · Beam MAE: {r.get("beam_mae_nA", "—")} nA\n{gains}', self)
        else:
            QToolTip.hideText()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        hit = self._nearest(event.position())
        if hit and event.button() == Qt.LeftButton:
            self.selected_trial = hit[1]['trial']
            self.trialSelected.emit(self.selected_trial)
            self.update()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor('#1a1c1f'))
        p.setPen(QColor('#e8eaed'))
        p.drawText(16, 23, 'Measured cost · lower is better')
        for x, color, label in [(16, GA_COLOR, 'GA cost'), (125, BO_COLOR, 'BO cost'), (235, '#aeb5bf', 'Baseline / checks')]:
            p.setPen(QPen(QColor(color), 2))
            p.drawLine(x, 42, x+20, 42)
            p.drawText(x+25, 47, label)
        valid = [r for r in self.records if isinstance(r.get('cost'), (int,float)) and math.isfinite(r['cost'])]
        values = [r['cost'] for r in valid]
        low, high = min(values, default=0), max(values, default=1)
        pad = max((high-low)*.15, abs(high)*.05, .01)
        low, high = low-pad, high+pad
        area = QRectF(78, 67, max(1,self.width()-103), max(1,self.height()-108))
        n = max((r['trial'] for r in self.records), default=1)
        def pos(t,c):
            return QPointF(area.left()+(t-1)*area.width()/max(1,n-1), area.bottom()-(c-low)/(high-low)*area.height())
        for i in range(5):
            y = low+(high-low)*i/4
            point = pos(1,y)
            p.setPen(QColor('#343942'))
            p.drawLine(point,QPointF(area.right(),point.y()))
            p.setPen(QColor('#bdc6d2'))
            p.drawText(QRectF(0,point.y()-9,70,18),Qt.AlignRight,f'{y:.4g}')
            t = 1+(n-1)*i/4
            p.drawText(QRectF(pos(t,low).x()-22,area.bottom()+4,44,18),Qt.AlignCenter,str(round(t)))
        p.drawText(QRectF(area.left(), self.height()-21, area.width(),20),Qt.AlignCenter,'Completed trial · click a marker to inspect PID response')
        self.hits = []
        baseline = [r['cost'] for r in valid if r['source']=='Baseline']
        if baseline:
            p.setPen(QPen(QColor('#aeb5bf'),1,Qt.DashLine))
            p.drawLine(pos(1,mean(baseline)),pos(n,mean(baseline)))
        self.series = {name: [r for r in valid if trial_method(r['source'])==name] for name in ('GA','BO')}
        for name,color in [('GA',GA_COLOR),('BO',BO_COLOR)]:
            previous = None
            for r in self.records:
                if trial_method(r['source']) != name:
                    continue
                if r not in valid:
                    previous = None
                    continue
                pt = pos(r['trial'],r['cost'])
                if previous is not None:
                    p.setPen(QPen(QColor(color),2))
                    p.drawLine(previous,pt)
                previous = pt
        for r in self.records:
            if r in valid:
                pt = pos(r['trial'],r['cost'])
                method = trial_method(r['source'])
                color = GA_COLOR if method=='GA' else BO_COLOR if method=='BO' else '#e4be79'
                p.setPen(QPen(QColor(color),2))
                p.setBrush(QColor(color) if method else Qt.NoBrush)
                p.drawEllipse(pt,4,4)
            else:
                pt = pos(r['trial'],low)
                p.setPen(QPen(QColor('#ff7b85'),2))
                p.drawLine(pt+QPointF(-4,-4),pt+QPointF(4,4))
                p.drawLine(pt+QPointF(-4,4),pt+QPointF(4,-4))
            self.hits.append((pt,r))
            if self.selected_trial == r['trial']:
                p.setPen(QPen(QColor('#ffffff'),1))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(pt,8,8)
        if not self.records:
            p.setPen(QColor('#aeb5bf'))
            p.drawText(area,Qt.AlignCenter,'Start tuning to compare measured GA and BO cost')
        p.end()
