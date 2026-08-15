from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from python.app.PageShell import DetailPage
from python.app.widgets.MagneticFieldWidgets import (
    CHANNEL_NAMES,
    FIELD_AUXILIARY_GROUP,
    FIELD_MONITOR_GROUPS,
    FIELD_PLOT_RENDER_SAMPLES,
    FIELD_PLOT_VISIBLE_SECONDS,
    FIELD_PLOT_VISIBLE_SAMPLES,
    MAX_GAUGE_VALUE,
    magnetic_field_plot_state,
)


PLOT_COLORS = (
    QColor("#60a5fa"),
    QColor("#22c55e"),
    QColor("#f59e0b"),
    QColor("#f472b6"),
)
MAGNETIC_PAGE_REFRESH_FPS = 30
MAGNETIC_PAGE_REFRESH_MS = round(1000 / MAGNETIC_PAGE_REFRESH_FPS)

try:
    import CycloViz
except Exception:
    CycloViz = None


class QtMagneticBarPlot(QWidget):
    def __init__(
        self,
        title: str,
        indices: tuple[int, ...],
        parent: QWidget | None = None,
        minimum_height: int = 185,
    ) -> None:
        super().__init__(parent)
        self.title = title
        self.indices = indices
        self.state = magnetic_field_plot_state()
        self.setMinimumWidth(320)
        self.setMinimumHeight(minimum_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setObjectName("magneticChart")

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self._paint_surface(painter)

        plot = QRectF(self.rect()).adjusted(56.0, 38.0, -16.0, -48.0)
        if plot.width() <= 16 or plot.height() <= 16:
            return

        self._draw_axes(painter, plot)
        enabled = self.state.enabled_indices(self.indices)
        if not enabled:
            self._draw_empty(painter, plot)
            return

        slot = plot.width() / max(1, len(self.indices))
        for lane, index in enumerate(self.indices):
            value = self.state.actual_values[index]
            target = self.state.target_values[index]
            checked = index in enabled
            color = QColor(PLOT_COLORS[lane % len(PLOT_COLORS)])
            color.setAlpha(235 if checked else 42)

            left = plot.left() + lane * slot + min(12.0, slot * 0.18)
            right = plot.left() + (lane + 1) * slot - min(12.0, slot * 0.18)
            bottom = plot.bottom()
            top = plot.bottom() - plot.height() * min(1.0, value / MAX_GAUGE_VALUE)
            if checked:
                path = QPainterPath()
                path.addRoundedRect(QRectF(left, top, max(4.0, right - left), bottom - top), 4.0, 4.0)
                painter.fillPath(path, color)

                target_y = plot.bottom() - plot.height() * min(1.0, target / MAX_GAUGE_VALUE)
                target_pen = QPen(QColor("#e5e7eb"), 1.4)
                target_pen.setStyle(Qt.DashLine)
                painter.setPen(target_pen)
                painter.drawLine(QPointF(left, target_y), QPointF(right, target_y))

            painter.setPen(QColor("#cbd5e1") if checked else QColor("#64748b"))
            painter.drawText(
                QRectF(plot.left() + lane * slot, plot.bottom() + 8.0, slot, 18.0),
                Qt.AlignCenter,
                CHANNEL_NAMES[index],
            )
            painter.drawText(
                QRectF(plot.left() + lane * slot, max(plot.top() - 2.0, top - 20.0), slot, 18.0),
                Qt.AlignCenter,
                f"{value:.1f}" if checked else "OFF",
            )

    def _paint_surface(self, painter: QPainter) -> None:
        painter.fillRect(self.rect(), QColor("#0f172a"))
        painter.setPen(QPen(QColor("#334155"), 1.0))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8.0, 8.0)
        painter.setPen(QColor("#e5e7eb"))
        title_font = QFont(self.font())
        title_font.setPointSize(max(9, title_font.pointSize()))
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(QRectF(14.0, 8.0, self.width() - 28.0, 22.0), Qt.AlignLeft | Qt.AlignVCenter, self.title)

    def _draw_axes(self, painter: QPainter, plot: QRectF) -> None:
        painter.setPen(QPen(QColor(51, 65, 85, 150), 1.0))
        for step in range(5):
            y = plot.top() + plot.height() * step / 4
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        painter.setPen(QPen(QColor("#64748b"), 1.0))
        painter.drawRect(plot)

        painter.setPen(QColor("#cbd5e1"))
        for step in range(5):
            value = MAX_GAUGE_VALUE - MAX_GAUGE_VALUE * step / 4
            y = plot.top() + plot.height() * step / 4
            painter.drawText(QRectF(plot.left() - 52.0, y - 9.0, 44.0, 18.0), Qt.AlignRight | Qt.AlignVCenter, f"{value:.0f}")
        painter.drawText(QRectF(plot.left() - 54.0, plot.center().y() - 46.0, 18.0, 92.0), Qt.AlignCenter, "A")
        painter.drawText(QRectF(plot.left(), plot.bottom() + 28.0, plot.width(), 18.0), Qt.AlignCenter, "Channel")

    def _draw_empty(self, painter: QPainter, plot: QRectF) -> None:
        painter.setPen(QColor("#94a3b8"))
        painter.drawText(plot, Qt.AlignCenter, "Plot toggles are off")


class QtMagneticLinePlot(QWidget):
    def __init__(
        self,
        title: str,
        indices: tuple[int, ...],
        parent: QWidget | None = None,
        minimum_height: int = 185,
    ) -> None:
        super().__init__(parent)
        self.title = title
        self.indices = indices
        self.state = magnetic_field_plot_state()
        self.setMinimumHeight(minimum_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setObjectName("magneticChart")

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0f172a"))
        painter.setPen(QPen(QColor("#334155"), 1.0))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8.0, 8.0)

        plot = QRectF(self.rect()).adjusted(62.0, 42.0, -18.0, -50.0)
        if plot.width() <= 16 or plot.height() <= 16:
            return

        enabled = self.state.enabled_indices(self.indices)
        histories = [list(self.state.history[index])[-FIELD_PLOT_VISIBLE_SAMPLES:] for index in enabled]
        latest = max((history[-1][0] for history in histories if history), default=0.0)
        cutoff = latest - FIELD_PLOT_VISIBLE_SECONDS
        series = [
            (index, [sample for sample in history if sample[0] >= cutoff])
            for index, history in zip(enabled, histories)
        ]
        series = [(index, self._bucket_history(row, FIELD_PLOT_RENDER_SAMPLES)) for index, row in series]
        samples = [sample for _, row in series for sample in row]
        if samples:
            start = min(sample[0] for sample in samples)
            end = max(max(sample[0] for sample in samples), start + 1.0)
            values = [sample[1] for sample in samples]
            lower = min(values)
            upper = max(values)
        else:
            start = 0.0
            end = 16.8
            lower = 0.0
            upper = MAX_GAUGE_VALUE
        if math.isclose(lower, upper, abs_tol=0.001):
            lower -= 1.0
            upper += 1.0
        padding = max(1.0, (upper - lower) * 0.12)
        lower = max(0.0, lower - padding)
        upper = min(MAX_GAUGE_VALUE, upper + padding)
        if math.isclose(lower, upper, abs_tol=0.001):
            upper = lower + 1.0

        self._draw_header_and_legend(painter, plot, enabled)
        self._draw_axes(painter, plot, start, end, lower, upper)
        if not enabled:
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(plot, Qt.AlignCenter, "Plot toggles are off")
            return
        if not samples:
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(plot, Qt.AlignCenter, "Waiting for live samples")
            return

        for lane, (index, row) in enumerate(series):
            if len(row) < 2:
                continue
            color = QColor(PLOT_COLORS[self.indices.index(index) % len(PLOT_COLORS)])
            painter.setPen(QPen(color, 1.8))
            previous = self._point(plot, row[0], start, end, lower, upper)
            for sample in row[1:]:
                current = self._point(plot, sample, start, end, lower, upper)
                painter.drawLine(previous, current)
                previous = current

    def _draw_header_and_legend(self, painter: QPainter, plot: QRectF, enabled: list[int]) -> None:
        title_font = QFont(self.font())
        title_font.setPointSize(max(9, title_font.pointSize()))
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#e5e7eb"))
        painter.drawText(QRectF(14.0, 8.0, 210.0, 22.0), Qt.AlignLeft | Qt.AlignVCenter, self.title)

        x = max(plot.left() + 220.0, plot.right() - 340.0)
        y = 11.0
        for index in enabled:
            color = QColor(PLOT_COLORS[self.indices.index(index) % len(PLOT_COLORS)])
            painter.setPen(QPen(color, 1.8))
            painter.drawLine(QPointF(x, y + 8.0), QPointF(x + 18.0, y + 8.0))
            painter.setPen(QColor("#cbd5e1"))
            painter.drawText(QRectF(x + 24.0, y, 58.0, 18.0), Qt.AlignLeft | Qt.AlignVCenter, CHANNEL_NAMES[index])
            x += 82.0

    def _draw_axes(self, painter: QPainter, plot: QRectF, start: float, end: float, lower: float, upper: float) -> None:
        painter.setPen(QPen(QColor(51, 65, 85, 150), 1.0))
        for step in range(5):
            y = plot.top() + plot.height() * step / 4
            x = plot.left() + plot.width() * step / 4
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
        painter.setPen(QPen(QColor("#64748b"), 1.0))
        painter.drawRect(plot)

        painter.setPen(QColor("#cbd5e1"))
        for step in range(5):
            amount = step / 4
            x = plot.left() + plot.width() * amount
            y = plot.top() + plot.height() * step / 4
            value = upper - (upper - lower) * amount
            seconds = (end - start) * amount
            painter.drawText(QRectF(plot.left() - 56.0, y - 9.0, 48.0, 18.0), Qt.AlignRight | Qt.AlignVCenter, f"{value:.0f}")
            painter.drawText(QRectF(x - 32.0, plot.bottom() + 8.0, 64.0, 18.0), Qt.AlignCenter, f"{seconds:.1f}")
        painter.drawText(QRectF(plot.left(), plot.bottom() + 28.0, plot.width(), 18.0), Qt.AlignCenter, "Time (s)")
        painter.drawText(QRectF(plot.left() - 58.0, plot.center().y() - 46.0, 18.0, 92.0), Qt.AlignCenter, "A")

    def _point(self, plot: QRectF, sample: tuple[float, float, float, float], start: float, end: float, lower: float, upper: float) -> QPointF:
        x_ratio = (sample[0] - start) / max(0.001, end - start)
        y_ratio = (sample[1] - lower) / max(0.001, upper - lower)
        return QPointF(
            plot.left() + plot.width() * x_ratio,
            plot.bottom() - plot.height() * y_ratio,
        )

    def _bucket_history(
        self,
        samples: list[tuple[float, float, float, float]],
        maximum_rows: int,
    ) -> list[tuple[float, float, float, float]]:
        if len(samples) <= maximum_rows or maximum_rows <= 0:
            return samples
        bucketed: list[tuple[float, float, float, float]] = []
        for bucket in range(maximum_rows):
            start = bucket * len(samples) // maximum_rows
            end = max(start + 1, (bucket + 1) * len(samples) // maximum_rows)
            count = float(end - start)
            sums = [0.0, 0.0, 0.0, 0.0]
            for sample in samples[start:end]:
                for column, value in enumerate(sample):
                    sums[column] += float(value)
            bucketed.append(tuple(value / count for value in sums))  # type: ignore[arg-type]
        return bucketed


class NativeMagneticBarPlot(QOpenGLWidget):
    def __init__(
        self,
        title: str,
        indices: tuple[int, ...],
        parent: QWidget | None = None,
        minimum_height: int = 185,
    ) -> None:
        super().__init__(parent)
        surface_format = self.format()
        surface_format.setSamples(8)
        self.setFormat(surface_format)
        self.title = title
        self.indices = indices
        self.state = magnetic_field_plot_state()
        self.setMinimumWidth(320)
        self.setMinimumHeight(minimum_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setObjectName("magneticChart")
        self._native = None
        self._ready = False

    def initializeGL(self) -> None:
        try:
            import CycloViz
            from PySide6.QtGui import QOpenGLContext

            context = QOpenGLContext.currentContext()

            def get_proc(name: str) -> int:
                address = context.getProcAddress(name.encode("ascii"))
                return int(address) if address else 0

            CycloViz.load_opengl(get_proc)
            self._native = CycloViz.MagneticFieldBarPlot()
            self._ready = True
        except Exception as exc:
            self._ready = False
            self._native = None
            print(f"[MagneticFieldMonitoring] Native OpenGL bar plot unavailable: {exc}")

    def paintGL(self) -> None:
        if not self._ready or self._native is None:
            return
        enabled = self.state.enabled_indices(self.indices)
        labels = [CHANNEL_NAMES[index] for index in enabled]
        values = [float(self.state.actual_values[index]) for index in enabled]
        self._native.set_data(self.title, labels, values)
        pixel_ratio = self.devicePixelRatio()
        self._native.render(
            max(1, int(round(self.width() * pixel_ratio))),
            max(1, int(round(self.height() * pixel_ratio))),
        )


class NativeMagneticLinePlot(QOpenGLWidget):
    def __init__(
        self,
        title: str,
        indices: tuple[int, ...],
        parent: QWidget | None = None,
        minimum_height: int = 185,
    ) -> None:
        super().__init__(parent)
        surface_format = self.format()
        surface_format.setSamples(8)
        self.setFormat(surface_format)
        self.title = title
        self.indices = indices
        self.state = magnetic_field_plot_state()
        self.setMinimumHeight(minimum_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setObjectName("magneticChart")
        self._native = None
        self._ready = False

    def initializeGL(self) -> None:
        try:
            import CycloViz
            from PySide6.QtGui import QOpenGLContext

            context = QOpenGLContext.currentContext()

            def get_proc(name: str) -> int:
                address = context.getProcAddress(name.encode("ascii"))
                return int(address) if address else 0

            CycloViz.load_opengl(get_proc)
            self._native = CycloViz.MagneticFieldLinePlot()
            self._ready = True
        except Exception as exc:
            self._ready = False
            self._native = None
            print(f"[MagneticFieldMonitoring] Native OpenGL line plot unavailable: {exc}")

    def paintGL(self) -> None:
        if not self._ready or self._native is None:
            return
        enabled = self.state.enabled_indices(self.indices)
        labels = [CHANNEL_NAMES[index] for index in enabled]
        samples = self._line_samples(enabled)
        self._native.set_data(self.title, labels, samples)
        pixel_ratio = self.devicePixelRatio()
        self._native.render(
            max(1, int(round(self.width() * pixel_ratio))),
            max(1, int(round(self.height() * pixel_ratio))),
        )

    def _line_samples(self, enabled: list[int]) -> list[list[float]]:
        if not enabled:
            return []
        histories = [list(self.state.history[index])[-FIELD_PLOT_VISIBLE_SAMPLES:] for index in enabled]
        latest = max((history[-1][0] for history in histories if history), default=0.0)
        cutoff = latest - FIELD_PLOT_VISIBLE_SECONDS
        histories = [[sample for sample in history if sample[0] >= cutoff] for history in histories]
        sample_count = min((len(history) for history in histories), default=0)
        if sample_count <= 0:
            return []
        rows = self._aligned_rows(histories, sample_count)
        return self._bucket_rows(rows, FIELD_PLOT_RENDER_SAMPLES)

    def _aligned_rows(self, histories: list[list[tuple[float, float, float, float]]], sample_count: int) -> list[list[float]]:
        rows: list[list[float]] = []
        for offset in range(sample_count):
            row = [float(histories[0][offset][0])]
            for history in histories:
                row.append(float(history[offset][1]))
            rows.append(row)
        return rows

    def _bucket_rows(self, rows: list[list[float]], maximum_rows: int) -> list[list[float]]:
        if len(rows) <= maximum_rows or maximum_rows <= 0:
            return rows
        bucketed: list[list[float]] = []
        column_count = len(rows[0])
        for bucket in range(maximum_rows):
            start = bucket * len(rows) // maximum_rows
            end = max(start + 1, (bucket + 1) * len(rows) // maximum_rows)
            count = float(end - start)
            output = [0.0 for _ in range(column_count)]
            for row in rows[start:end]:
                for column, value in enumerate(row):
                    output[column] += value
            bucketed.append([value / count for value in output])
        return bucketed


def _native_magnetic_charts_available() -> bool:
    return (
        CycloViz is not None
        and hasattr(CycloViz, "load_opengl")
        and hasattr(CycloViz, "MagneticFieldBarPlot")
        and hasattr(CycloViz, "MagneticFieldLinePlot")
    )


def make_magnetic_bar_plot(title: str, indices: tuple[int, ...], minimum_height: int = 185) -> QWidget:
    if _native_magnetic_charts_available():
        return NativeMagneticBarPlot(title, indices, minimum_height=minimum_height)
    return QtMagneticBarPlot(title, indices, minimum_height=minimum_height)


def make_magnetic_line_plot(title: str, indices: tuple[int, ...], minimum_height: int = 185) -> QWidget:
    if _native_magnetic_charts_available():
        return NativeMagneticLinePlot(title, indices, minimum_height=minimum_height)
    return QtMagneticLinePlot(title, indices, minimum_height=minimum_height)


class MagneticFieldMonitoringPage(DetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__(
            "Magnetic Field Monitoring",
            "Magnetic field live monitoring",
            "Back to Monitoring",
            go_back,
        )
        self.state = magnetic_field_plot_state()
        self.plot_widgets: list[QWidget] = []
        self._compact_page_chrome()

        workspace_frame, workspace = self.add_workspace()
        workspace_frame.setObjectName("magneticFieldWorkspace")
        workspace.setContentsMargins(4, 4, 4, 4)
        workspace.setSpacing(4)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 7)

        for row, (title, indices) in enumerate(FIELD_MONITOR_GROUPS):
            bar = make_magnetic_bar_plot(f"{title} Current", indices)
            line = make_magnetic_line_plot(f"{title} Live Trend", indices)
            self.plot_widgets.extend([bar, line])
            grid.addWidget(self._wrap_plot(bar), row, 0)
            grid.addWidget(self._wrap_plot(line), row, 1)
            grid.setRowStretch(row, 1)

        aux_row = len(FIELD_MONITOR_GROUPS)
        aux_title, aux_indices = FIELD_AUXILIARY_GROUP
        aux_bar = make_magnetic_bar_plot(f"{aux_title} Current", aux_indices)
        aux_line = make_magnetic_line_plot(f"{aux_title} Live Trend", aux_indices)
        self.plot_widgets.extend([aux_bar, aux_line])
        grid.addWidget(self._wrap_plot(aux_bar), aux_row, 0)
        grid.addWidget(self._wrap_plot(aux_line), aux_row, 1)
        grid.setRowStretch(aux_row, 1)

        workspace.addLayout(grid, 1)

        self.status_label = QLabel()
        self.status_label.setObjectName("fieldStatusText")
        workspace.addWidget(self.status_label)

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(MAGNETIC_PAGE_REFRESH_MS)
        self._refresh()

    def _compact_page_chrome(self) -> None:
        if hasattr(self, "header"):
            self.header.hide()
        spacer_item = self.layout.itemAt(0)
        if spacer_item is not None:
            spacer_item.changeSize(0, 0, QSizePolicy.Minimum, QSizePolicy.Fixed)

        nav_item = self.layout.itemAt(3)
        nav_layout = nav_item.layout() if nav_item is not None else None
        if nav_layout is None:
            return
        nav_layout.setContentsMargins(4, 2, 4, 2)
        nav_layout.setSpacing(0)

    def _wrap_plot(self, plot: QWidget) -> QFrame:
        frame = QFrame()
        frame.setObjectName("magneticPlotFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        layout.addWidget(plot, 1)
        return frame

    def _refresh(self) -> None:
        groups = (*FIELD_MONITOR_GROUPS, FIELD_AUXILIARY_GROUP)
        enabled_count = sum(1 for _, indices in groups for index in indices if self.state.plot_enabled[index])
        total_count = sum(len(indices) for _, indices in groups)
        self.status_label.setText(
            f"Plotting {enabled_count}/{total_count} channels | rolling window {FIELD_PLOT_VISIBLE_SECONDS:.0f}s"
        )
        for widget in self.plot_widgets:
            widget.update()
