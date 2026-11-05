"""Measured-data layers for the direct-coil optimizer; no invented response surface."""
from __future__ import annotations

import statistics

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip

from python.app.widgets.PlotSurface import PlotSurface


COLORS = {'candidate': '#75baff', 'baseline': '#a1a6b0', 'drift': '#a1a6b0',
          'confirm_candidate': '#b99aff', 'confirm_incumbent': '#e6bd70',
          'final_incumbent': '#66d9af'}


class TrimCoilPlotData:
    def __init__(self):
        self.reset()

    def reset(self):
        self.windows, self.confirmations, self.best, self.telemetry = [], [], [], []
        self.reference = None
        self.incumbent = {'TC1': 0., 'TC2': 0.}
        self.bounds = {'TC1': (-.5, .5), 'TC2': (-.5, .5)}
        self.minimum_gain = .1
        self.pairs = 3

    def consume(self, event):
        kind = event.get('event')
        if kind == 'start':
            self.incumbent = dict(event.get('reference_targets_a', self.incumbent))
            config = event.get('config', {})
            self.minimum_gain = config.get('minimum_gain_nA', .1)
            self.pairs = config.get('confirmation_pairs', 3)
            self.bounds.update({p['name']: tuple(p['bounds']) for p in event.get('parameters', [])})
        elif kind == 'telemetry':
            if event.get('valid', False) and (not self.telemetry or event['time_s'] > self.telemetry[-1]['time_s']):
                self.telemetry.append(event)
        elif kind == 'measurement':
            self.windows.append(event)
            baselines = [w['mean_nA'] for w in self.windows if w['kind'] == 'baseline']
            if baselines:
                self.reference = statistics.mean(baselines)
            if event['kind'] == 'baseline':
                self.best = [(1, self.reference)]
        elif kind == 'confirmation':
            self.confirmations.append({**event, 'window': len(self.windows)})
            if event['promoted']:
                self.incumbent = dict(event['incumbent'])
                repeats = [w['mean_nA'] for w in self.windows
                           if w['kind'] == 'confirm_candidate' and w['point'] == self.incumbent][-self.pairs:]
                if repeats:
                    self.best.append((len(self.windows), statistics.mean(repeats)))


class TrimCoilBOPlot(PlotSurface):
    def __init__(self, data, view, parent=None):
        super().__init__(parent)
        self.data, self.view = data, view
        self.layers = {'Reference': True, 'Confirmed best': True,
                       'Window variability': True, 'Search path': True}
        self.hits = []
        self.setMinimumSize(300, 210)
        self.setMouseTracking(True)
        self.setAccessibleName({'beam': 'Measured beam progress', 'search': 'Joint coil search',
                                'confirmation': 'Improvement confirmation'}[view])

    def mouseMoveEvent(self, event):
        point = event.position()
        nearest = min(reversed(self.hits), key=lambda item: (item[0] - point).manhattanLength(), default=None)
        if nearest and (nearest[0] - point).manhattanLength() < 16:
            QToolTip.showText(event.globalPosition().toPoint(), nearest[1], self)
        else:
            QToolTip.hideText()
        super().mouseMoveEvent(event)

    def paint_chart(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor('#17191c'))
        painter.setPen(QColor('#e6e8ed'))
        titles = {'beam': 'Measured beam and confirmed progress',
                  'search': 'Joint coil search · measured points only',
                  'confirmation': 'Paired gain and one-sided lower bound'}
        painter.drawText(QPointF(14, 23), titles[self.view])
        self.hits = []
        area = QRectF(72, 45, max(1, self.width() - 100), max(1, self.height() - 150))
        if not self.data.windows:
            painter.setPen(QColor('#adb4bf'))
            painter.drawText(area, Qt.AlignCenter, 'Start a simulation to see measurements')
        elif self.view == 'search':
            self._search(painter, area)
        elif self.view == 'confirmation':
            self._confirmation(painter, area)
        else:
            self._beam(painter, area)
        painter.end()

    def _axes(self, painter, area, xlim, ylim, xlabel, ylabel, integer_x=False, show_x_labels=True, ticks=5):
        def position(x, y):
            return QPointF(area.left() + (x - xlim[0]) / (xlim[1] - xlim[0]) * area.width(),
                           area.bottom() - (y - ylim[0]) / (ylim[1] - ylim[0]) * area.height())
        seen_x = set()
        for i in range(ticks):
            fraction = i / (ticks - 1)
            x, y = xlim[0] + fraction * (xlim[1] - xlim[0]), ylim[0] + fraction * (ylim[1] - ylim[0])
            if integer_x:
                x = round(x)
            px, py = position(x, ylim[0]).x(), position(xlim[0], y).y()
            painter.setPen(QPen(QColor('#30353d'), 1))
            if x not in seen_x:
                painter.drawLine(QPointF(px, area.top()), QPointF(px, area.bottom()))
            painter.drawLine(QPointF(area.left(), py), QPointF(area.right(), py))
            painter.setPen(QColor('#b6bdc8'))
            if x not in seen_x and show_x_labels:
                painter.drawText(QRectF(px - 32, area.bottom() + 5, 64, 18), Qt.AlignCenter, f'{x:.3g}')
            seen_x.add(x)
            painter.drawText(QRectF(2, py - 9, 62, 18), Qt.AlignRight | Qt.AlignVCenter, f'{y:.4g}')
        painter.drawText(QRectF(area.left(), area.bottom() + 26, area.width(), 20), Qt.AlignCenter, xlabel)
        painter.save()
        painter.translate(15, area.center().y())
        painter.rotate(-90)
        painter.drawText(QRectF(-area.height()/2, -10, area.height(), 20), Qt.AlignCenter, ylabel)
        painter.restore()
        return position

    @staticmethod
    def _range(values):
        low, high = min(values), max(values)
        pad = max((high - low) * .15, .025)
        return low - pad, high + pad

    def _line(self, painter, position, points, color, dashed=False):
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(color), 1.7, Qt.DashLine if dashed else Qt.SolidLine))
        path = QPainterPath()
        for index, point in enumerate(points):
            if index == 0:
                path.moveTo(position(*point))
            else:
                path.lineTo(position(*point))
        painter.drawPath(path)

    def _beam(self, painter, area):
        rows = self.data.windows
        values = [w['mean_nA'] + sign * (w['stddev_nA'] if self.layers['Window variability'] else 0)
                  for w in rows for sign in (-1, 1)]
        values.extend(value for _, value in self.data.best)
        if self.data.reference is not None:
            values.append(self.data.reference)
        end = max(2, len(rows))
        position = self._axes(painter, area, (1, end), self._range(values), 'Measurement window', 'Beam (nA)', integer_x=True)
        if self.layers['Reference'] and self.data.reference is not None:
            self._line(painter, position, [(1, self.data.reference), (end, self.data.reference)], '#a1a6b0', True)
        if self.layers['Confirmed best'] and self.data.best:
            steps = [self.data.best[0]]
            for index, value in self.data.best[1:]:
                steps.extend([(index, steps[-1][1]), (index, value)])
            steps.append((end, steps[-1][1]))
            self._line(painter, position, steps, '#66d9af')
        for index, window in enumerate(rows, 1):
            mean, sd = window['mean_nA'], window['stddev_nA']
            point = position(index, mean)
            color = QColor(COLORS.get(window['kind'], '#75baff'))
            painter.setPen(QPen(color, 1.3))
            if self.layers['Window variability']:
                painter.drawLine(position(index, mean - sd), position(index, mean + sd))
            painter.setBrush(color)
            painter.drawEllipse(point, 3.5, 3.5)
            self.hits.append((point, f"Window {index} · {window['kind']}\nBeam {mean:.4f} nA\n"
                              f"Window standard deviation {sd:.4f} nA\n{window['point']}"))
        self._footer(painter, 'Blue: candidate · purple: confirmation · gold: incumbent · green line: confirmed best\n'
                     'Gray dashed: initial reference mean · bars: ±1 window standard deviation, not confidence intervals')

    def _search(self, painter, area):
        rows = self.data.windows
        position = self._axes(painter, area, self.data.bounds['TC1'], self.data.bounds['TC2'], 'TC1 (A)', 'TC2 (A)')
        # Only candidate proposals define the search path; baseline returns are omitted.
        candidates = [w for w in rows if w['kind'] == 'candidate']
        if self.layers['Search path']:
            self._line(painter, position, [(w['point']['TC1'], w['point']['TC2']) for w in candidates], '#586b83')
        low, high = min(w['mean_nA'] for w in rows), max(w['mean_nA'] for w in rows)
        for index, window in enumerate(rows, 1):
            point = position(window['point']['TC1'], window['point']['TC2'])
            fraction = (window['mean_nA'] - low) / max(high - low, 1e-12)
            color = QColor.fromHsvF((1 - fraction) * .62, .65, .95)
            painter.setPen(QPen(color, 1))
            painter.setBrush(color)
            painter.drawEllipse(point, 4, 4)
            self.hits.append((point, f"Window {index} · {window['kind']}\n{window['point']}\nBeam {window['mean_nA']:.4f} nA"))
        if self.layers['Reference']:
            point = position(0, 0)  # fixed synthetic reference shown by this workspace
            painter.setPen(QPen(QColor('#ffffff'), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(point.x() - 7, point.y() - 7, 14, 14))
        if self.layers['Confirmed best']:
            point = position(self.data.incumbent['TC1'], self.data.incumbent['TC2'])
            painter.setPen(QPen(QColor('#66d9af'), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(point, 10, 10)
        self._footer(painter, f'Beam color: blue {low:.3f} nA → red {high:.3f} nA · white square: reference · green ring: confirmed best\n'
                     'Path connects candidate proposals only; repeated measurements share a location. Hover for measured values.')

    def _confirmation(self, painter, area):
        rows = self.data.confirmations
        if not rows:
            painter.setPen(QColor('#adb4bf'))
            painter.drawText(area, Qt.AlignCenter, 'No confirmation comparisons yet\nPromising candidates are remeasured before promotion.')
            return
        threshold = self.data.minimum_gain
        limits = self._range([0, threshold] + [r[k] for r in rows for k in ('gain_nA', 'lower_bound_nA')])
        end = max(2, len(rows))
        position = self._axes(painter, area, (1, end), limits, 'Confirmation comparison', 'Paired gain (nA)', integer_x=True)
        self._line(painter, position, [(1, threshold), (end, threshold)], '#e6bd70', True)
        self._line(painter, position, [(1, 0), (end, 0)], '#68707c')
        for index, result in enumerate(rows, 1):
            point, lower = position(index, result['gain_nA']), position(index, result['lower_bound_nA'])
            color = QColor('#66d9af' if result['promoted'] else '#b99aff')
            painter.setPen(QPen(color, 2))
            painter.drawLine(point, lower)
            painter.drawLine(lower + QPointF(-5, 0), lower + QPointF(5, 0))
            painter.setBrush(color)
            painter.drawEllipse(point, 4, 4)
            self.hits.append((point, f"{'Promoted' if result['promoted'] else 'Not promoted'}\n"
                f"Mean paired gain {result['gain_nA']:.4f} nA\nLower bound {result['lower_bound_nA']:.4f} nA\n"
                f"Standard error {result['standard_error_nA']:.4f} nA"))
        self._footer(painter, 'Dot: measured paired gain · lower cap: configured one-sided lower bound · gold dashed: minimum useful gain\n'
                     'Green: promoted · purple: previous best retained. Bound uses the configured multiplier, not a calibrated confidence level.')

    def _footer(self, painter, text):
        painter.setPen(QColor('#adb4bf'))
        painter.drawText(QRectF(14, self.height() - 53, self.width() - 28, 51), Qt.AlignLeft | Qt.TextWordWrap, text)


class TrimCoilBeamTimeline(TrimCoilBOPlot):
    """Time-aligned beam and current readbacks, including ramps between trials."""
    def __init__(self, data, parent=None):
        super().__init__(data, 'beam', parent)
        self.setAccessibleName('Trim-coil currents and beam versus time')
        self.setMinimumHeight(310)

    def paint_chart(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor('#17191c'))
        painter.setPen(QColor('#e6e8ed'))
        painter.drawText(QPointF(14, 23), 'Trim-coil currents and beam · shared simulation time')
        painter.setPen(QColor('#adb4bf'))
        painter.drawText(QPointF(14, 42), 'Beam: green · coil readbacks: solid blue / purple · commanded targets: dashed')
        self.hits = []
        rows = self.data.telemetry
        if not rows:
            painter.drawText(self.rect(), Qt.AlignCenter, 'Start a simulation to see trim-coil currents and beam')
            painter.end()
            return
        times = (rows[0]['time_s'], max(rows[-1]['time_s'], rows[0]['time_s'] + .1))
        step = max(65, (self.height() - 105) / 3)
        for index, channel in enumerate(('beam', 'TC1', 'TC2')):
            area = QRectF(72, 58 + index * step, max(1, self.width() - 100), step - 26)
            if channel == 'beam':
                values = [r['beam_nA'] for r in rows]
                if self.data.reference is not None:
                    values.append(self.data.reference)
                color, ylabel = '#66d9af', 'Beam (nA)'
            else:
                values = [r[key][channel] for r in rows for key in ('targets_a', 'readbacks_a')]
                color, ylabel = ('#75baff' if channel == 'TC1' else '#b99aff'), f'{channel} (A)'
            position = self._axes(painter, area, times, self._range(values), '', ylabel,
                                  show_x_labels=index == 2, ticks=3)
            if channel == 'beam':
                self._line(painter, position, [(r['time_s'], r['beam_nA']) for r in rows], color)
                if self.layers['Reference'] and self.data.reference is not None:
                    self._line(painter, position, [(t, self.data.reference) for t in times], '#a1a6b0', True)
            else:
                self._line(painter, position, [(r['time_s'], r['readbacks_a'][channel]) for r in rows], color)
                targets = []
                for row in rows:
                    if targets:
                        targets.append((row['time_s'], targets[-1][1]))
                    targets.append((row['time_s'], row['targets_a'][channel]))
                self._line(painter, position, targets, color, True)
            for row in rows:
                value = row['beam_nA'] if channel == 'beam' else row['readbacks_a'][channel]
                self.hits.append((position(row['time_s'], value), f"Time {row['time_s']:.2f} s\n"
                    f"Beam {row['beam_nA']:.4f} nA\nTC1 target/readback: {row['targets_a']['TC1']:.4f} / {row['readbacks_a']['TC1']:.4f} A\n"
                    f"TC2 target/readback: {row['targets_a']['TC2']:.4f} / {row['readbacks_a']['TC2']:.4f} A"))
        painter.setPen(QColor('#adb4bf'))
        painter.drawText(QRectF(14, self.height() - 24, self.width() - 28, 20), Qt.AlignCenter,
                         'Simulation time (s) · includes settling, acquisition and reference returns')
        painter.end()


class TrimCoilOverview(TrimCoilBOPlot):
    """Measured cost history and full-dimensional coil settings."""
    def __init__(self, data, view):
        super().__init__(data, 'beam')
        self.overview = view
        self.setAccessibleName('Measured cost history' if view == 'cost' else 'Parallel coil coordinates')

    def paint_chart(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor('#17191c'))
        painter.setPen(QColor('#e6e8ed'))
        self.hits = []
        area = QRectF(72, 55, max(1, self.width()-130), max(1, self.height()-155))
        windows = self.data.windows
        if self.overview == 'cost':
            painter.drawText(QPointF(14, 23), 'Measured cost = −beam · lower is better · all acquisition windows')
            if windows:
                values = [-w['mean_nA'] for w in windows]
                pos = self._axes(painter, area, (1, max(2, len(values))), self._range(values),
                                 'Measurement window (includes baseline and confirmation)', 'Cost (−nA)', integer_x=True)
                self._line(painter, pos, list(enumerate(values, 1)), '#75baff')
                if self.data.reference is not None and self.layers['Reference']:
                    self._line(painter, pos, [(1, -self.data.reference), (max(2,len(values)), -self.data.reference)], '#a1a6b0', True)
                if self.layers['Confirmed best']:
                    best = [(x, -v) for x,v in self.data.best]
                    steps = []
                    for x,y in best:
                        if steps:
                            steps.append((x,steps[-1][1]))
                        steps.append((x,y))
                    if steps:
                        steps.append((max(2,len(values)),steps[-1][1]))
                        self._line(painter,pos,steps,'#66d9af')
                for i,w in enumerate(windows,1):
                    pt = pos(i, -w['mean_nA'])
                    painter.setBrush(QColor(COLORS.get(w['kind'], '#75baff')))
                    painter.drawEllipse(pt, 3, 3)
                    self.hits.append((pt, f"{w['kind']} · beam {w['mean_nA']:.4f} nA · cost {-w['mean_nA']:.4f}"))
        else:
            painter.drawText(QPointF(14, 23), 'Parallel coordinates · each line is one measured coil vector')
            names = list(self.data.bounds)
            def point(i,value):
                low,high = self.data.bounds[names[i]]
                return QPointF(area.left()+i*area.width()/max(1,len(names)-1),
                               area.bottom()-(value-low)/(high-low)*area.height())
            for i,name in enumerate(names):
                low,high = self.data.bounds[name]
                x = point(i,low).x()
                painter.setPen(QColor('#455164'))
                painter.drawLine(point(i,low),point(i,high))
                painter.setPen(QColor('#c8d2df'))
                for y,label in [(area.top()-22,f'{high:+.3f} A'),(area.bottom()+5,f'{low:+.3f} A'),(area.bottom()+27,name)]:
                    painter.drawText(QRectF(x-45,y,90,20),Qt.AlignCenter,label)
            means = [w['mean_nA'] for w in windows]
            lo,hi = (min(means),max(means)) if means else (0,1)
            for w in windows:
                fraction = (w['mean_nA']-lo)/max(hi-lo,1e-9)
                color = QColor.fromHsvF(.65-.3*fraction,.65,.95)
                painter.setPen(QPen(color,1.5))
                points = [point(i,w['point'][name]) for i,name in enumerate(names) if name in w['point']]
                for a,b in zip(points,points[1:]):
                    painter.drawLine(a,b)
                for pt in points:
                    self.hits.append((pt,f"{w['kind']} · {w['mean_nA']:.4f} nA\n{w['point']}"))
            painter.setPen(QColor('#aeb9ca'))
            painter.drawText(QPointF(14, self.height()-16),f'Beam color: blue (low) → green (high) · {lo:.3f} to {hi:.3f} nA · axes scaled to search bounds')
        if not windows:
            painter.setPen(QColor('#aeb9ca'))
            painter.drawText(area,Qt.AlignCenter,'Waiting for baseline and trial measurements')
        painter.end()
