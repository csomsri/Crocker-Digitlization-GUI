from collections.abc import Callable

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)

from python.app.widgets.MonitoringPlotState import monitoring_plot_state
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSizePolicy,
    QSpacerItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


PageSpec = tuple[str, str]


ACCENT = QColor("#3b82f6")
TEXT = QColor("#e5e7eb")
MUTED_TEXT = QColor("#94a3b8")
SURFACE = QColor("#111827")
BORDER = QColor("#334155")


def _fitted_font(
    family: str,
    text: str,
    rect: QRectF,
    max_size: int,
    min_size: int = 8,
    weight: int = QFont.Bold,
) -> QFont:
    for size in range(max_size, min_size - 1, -1):
        font = QFont(family, size, weight)
        metrics = QFontMetrics(font)
        if (
            metrics.horizontalAdvance(text) <= rect.width() - 28
            and metrics.height() <= rect.height() - 18
        ):
            return font
    return QFont(family, min_size, weight)


class CnlPanelButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(320, 220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: 0; color: transparent;")

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        highlighted = self.underMouse()
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if highlighted:
            gradient.setColorAt(0, QColor(30, 41, 59, 246))
            gradient.setColorAt(1, QColor(15, 23, 42, 246))
        else:
            gradient.setColorAt(0, QColor(17, 24, 39, 238))
            gradient.setColorAt(1, QColor(15, 23, 42, 238))
        painter.fillPath(path, gradient)
        painter.setPen(QPen(QColor("#64748b") if highlighted else BORDER, 1))
        painter.drawPath(path)

        app = QApplication.instance()
        app_family = app.property("appFontFamily") if app is not None else None
        family = app_family or "Segoe UI"
        font = _fitted_font(family, self.text(), rect, max_size=24, min_size=9)
        painter.setFont(font)
        painter.setPen(QPen(TEXT if highlighted else QColor("#cbd5e1"), 1))
        painter.drawText(rect, Qt.AlignCenter, self.text())


class CnlTransitionButton(QPushButton):
    def __init__(self, title: str, description: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.description = description
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFlat(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setObjectName("transitionCardButton")
        self.setStyleSheet("background: transparent; border: 0; color: transparent;")

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        highlighted = self.underMouse()
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, QColor(30, 41, 59, 248 if highlighted else 232))
        gradient.setColorAt(1, QColor(15, 23, 42, 248 if highlighted else 236))
        painter.fillPath(path, gradient)
        painter.setPen(QPen(QColor("#93c5fd") if highlighted else BORDER, 1.2))
        painter.drawPath(path)

        accent_rect = QRectF(rect.left(), rect.top() + 18, 4, rect.height() - 36)
        painter.fillRect(accent_rect, ACCENT if highlighted else QColor("#475569"))

        app = QApplication.instance()
        app_family = app.property("appFontFamily") if app is not None else None
        family = app_family or "Segoe UI"
        title_rect = rect.adjusted(28, 22, -28, -70)
        painter.setFont(_fitted_font(family, self.title.upper(), title_rect, max_size=22, min_size=12))
        painter.setPen(QPen(TEXT if highlighted else QColor("#e2e8f0"), 1))
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, self.title.upper())

        desc_rect = rect.adjusted(28, 78, -28, -22)
        painter.setFont(_fitted_font(family, self.description, desc_rect, max_size=13, min_size=9, weight=QFont.Normal))
        painter.setPen(QPen(QColor("#cbd5e1") if highlighted else MUTED_TEXT, 1))
        painter.drawText(desc_rect, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap, self.description)


class CnlBackButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setObjectName("navBackButton")
        self.setFixedSize(max(154, min(238, len(text) * 8 + 62)), 40)
        self.setStyleSheet("background: transparent; border: 0; color: transparent;")

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        hovered = self.underMouse()
        pressed = self.isDown()
        fill = QColor(30, 41, 59, 232 if hovered else 180)
        if pressed:
            fill = QColor(37, 99, 235, 150)
        border = QColor("#93c5fd") if hovered else QColor(71, 85, 105, 190)
        painter.setBrush(fill)
        painter.setPen(QPen(border, 1.1))
        painter.drawRoundedRect(rect, 7, 7)

        arrow = QColor("#bfdbfe") if hovered else QColor("#94a3b8")
        painter.setPen(QPen(arrow, 2.0))
        center_y = rect.center().y()
        painter.drawLine(QPointF(24, center_y), QPointF(33, center_y - 8))
        painter.drawLine(QPointF(24, center_y), QPointF(33, center_y + 8))
        painter.drawLine(QPointF(25, center_y), QPointF(46, center_y))

        app = QApplication.instance()
        app_family = app.property("appFontFamily") if app is not None else None
        family = app_family or "Segoe UI"
        text_rect = rect.adjusted(56, 0, -14, 0)
        painter.setFont(_fitted_font(family, self.text().upper(), text_rect, max_size=12, min_size=8))
        painter.setPen(QPen(TEXT if hovered else QColor("#cbd5e1"), 1))
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, self.text().upper())


class CnlViewportPlaceholder(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(560, 440)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, QColor(17, 24, 39, 244))
        gradient.setColorAt(1, QColor(15, 23, 42, 244))
        painter.fillPath(path, gradient)
        painter.setPen(QPen(BORDER, 1))
        painter.drawPath(path)

        app = QApplication.instance()
        app_family = app.property("appFontFamily") if app is not None else None
        family = app_family or "Segoe UI"
        painter.setFont(_fitted_font(family, "CYCLOVIZ VIEWPORT", rect, max_size=20, min_size=10))
        painter.setPen(QPen(MUTED_TEXT, 1))
        painter.drawText(rect, Qt.AlignCenter, "CYCLOVIZ VIEWPORT")


class CnlCircleDisplay(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(420, 420)
        self.setMaximumSize(900, 900)
        self.title = "Monitoring"
        self.preview_lines: list[str] = []

    def _circle_ring_rect(self) -> QRect:
        size = max(1, min(self.width(), self.height()) - 8)
        return QRect(
            int((self.width() - size) / 2),
            int((self.height() - size) / 2),
            int(size),
            int(size),
        ).adjusted(-3, -3, 3, 3)

    def set_preview(self, title: str, lines: list[str]) -> None:
        self.title = title
        self.preview_lines = lines
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        size = min(self.width(), self.height(), 640) - 22
        rect = QRectF(
            (self.width() - size) / 2,
            (self.height() - size) / 2,
            size,
            size,
        )
        radial = QLinearGradient(rect.topLeft(), rect.bottomRight())
        radial.setColorAt(0, QColor(17, 24, 39, 244))
        radial.setColorAt(1, QColor(15, 23, 42, 244))
        painter.setBrush(radial)
        painter.setPen(QPen(BORDER, 1))
        painter.drawEllipse(rect)
        painter.setPen(QPen(QColor("#1f2937"), 1))
        painter.drawEllipse(rect.adjusted(24, 24, -24, -24))
        painter.drawEllipse(rect.adjusted(58, 58, -58, -58))

        center = rect.center()
        painter.setPen(QPen(QColor("#334155"), 1))
        painter.drawLine(QPointF(center.x(), rect.top() + 28), QPointF(center.x(), rect.bottom() - 28))
        painter.drawLine(QPointF(rect.left() + 28, center.y()), QPointF(rect.right() - 28, center.y()))
        painter.setPen(QPen(ACCENT, 2))
        painter.drawArc(rect.adjusted(14, 14, -14, -14), 20 * 16, 72 * 16)

        app = QApplication.instance()
        app_family = app.property("appFontFamily") if app is not None else None
        family = app_family or "Segoe UI"
        title_rect = QRectF(rect.left() + 58, rect.top() + 68, rect.width() - 116, 68)
        painter.setFont(_fitted_font(family, self.title.upper(), title_rect, max_size=26, min_size=12))
        painter.setPen(QPen(TEXT, 1))
        painter.drawText(title_rect, Qt.AlignCenter, self.title.upper())

        painter.setFont(_fitted_font(family, "LIVE MONITORING PREVIEW", rect, max_size=13, min_size=9, weight=QFont.Normal))
        painter.setPen(MUTED_TEXT)
        text_y = center.y() + 20
        for line in self.preview_lines[:4]:
            painter.drawText(
                QRectF(rect.left() + 76, text_y, rect.width() - 152, 32),
                Qt.AlignCenter,
                line.upper(),
            )
            text_y += 38


class CnlMonitorSelectionButton(QPushButton):
    def __init__(self, title: str, description: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.description = description
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(112)
        self.setFixedHeight(112)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFlat(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setObjectName("monitorSelectionButton")
        self.setStyleSheet(
            "background: transparent; border: 0; color: transparent; "
            "min-height: 112px; max-height: 112px;"
        )

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        selected = bool(self.property("selected"))
        circle_size = min(78, self.height() - 12)
        circle = QRectF(4, (self.height() - circle_size) / 2, circle_size, circle_size)
        box = QRectF(circle.right() + 24, 8, max(260.0, self.width() - circle.right() - 30), 96)

        fill = QColor(17, 24, 39, 238)
        if selected:
            fill = QColor(37, 99, 235, 190)
        painter.setBrush(fill)
        painter.setPen(QPen(QColor("#93c5fd") if selected else BORDER, 1))
        painter.drawEllipse(circle)

        box_gradient = QLinearGradient(box.topLeft(), box.bottomRight())
        box_gradient.setColorAt(0, QColor(30, 41, 59, 236 if selected else 220))
        box_gradient.setColorAt(1, QColor(15, 23, 42, 238))
        painter.setBrush(box_gradient)
        painter.setPen(QPen(QColor("#64748b") if selected else BORDER, 1))
        painter.drawRoundedRect(box, 8, 8)

        app = QApplication.instance()
        app_family = app.property("appFontFamily") if app is not None else None
        family = app_family or "Segoe UI"
        title_rect = QRectF(box.left() + 20, box.top() + 12, box.width() - 38, 32)
        painter.setFont(_fitted_font(family, self.title.upper(), title_rect, max_size=18, min_size=10))
        painter.setPen(QPen(TEXT if selected else QColor("#cbd5e1"), 1))
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, self.title.upper())

        desc_rect = QRectF(box.left() + 20, box.top() + 52, box.width() - 38, 34)
        painter.setFont(_fitted_font(family, self.description.upper(), desc_rect, max_size=11, min_size=8, weight=QFont.Normal))
        painter.setPen(MUTED_TEXT)
        painter.drawText(desc_rect, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap, self.description.upper())


class CnlRadialMonitorArena(QWidget):
    """Fan monitoring choices around the right edge of the preview dial."""

    def __init__(
        self,
        preview: CnlCircleDisplay,
        buttons: list[CnlMonitorSelectionButton],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.preview = preview
        self.buttons = buttons
        self.preview.setParent(self)
        for button in buttons:
            button.setParent(self)
        self.setMinimumSize(1050, 680)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().resizeEvent(event)
        count = len(self.buttons)
        if not count:
            return

        width = self.width()
        height = self.height()
        button_width = min(760, max(520, int(width * 0.38)))
        separation = 68
        dial_room = width - button_width - separation - 54
        dial_size = min(860, height - 24, max(430, dial_room))
        composition_width = dial_size + separation + button_width
        dial_left = max(18, int((width - composition_width) / 2))
        vertical_lift = min(38, max(18, int(height * 0.035)))
        minimum_top = max(4, int(56 - dial_size * 0.04))
        dial_top = max(minimum_top, int((height - dial_size) / 2 - vertical_lift))
        self.preview.setGeometry(dial_left, dial_top, dial_size, dial_size)

        center_y = dial_top + dial_size / 2
        radius = dial_size / 2 - 12
        span = min(height - 92, dial_size * 0.92)
        step = span / max(1, count - 1)
        first_y = center_y - span / 2

        for index, button in enumerate(self.buttons):
            marker_y = first_y + index * step
            delta_y = marker_y - center_y
            arc_x = (
                dial_left
                + dial_size / 2
                + max(0.0, radius * radius - delta_y * delta_y) ** 0.5
            )
            # Keep the selector orb visibly separate from the dial rim. The
            # varying arc_x preserves the radial fan while the whole dial/menu
            # composition remains centered as a single unit.
            button_x = int(arc_x + separation)
            button_y = int(marker_y - 56)
            button.setGeometry(
                button_x,
                button_y,
                max(350, min(button_width, width - button_x - 18)),
                112,
            )
            button.raise_()


class CnlTitleBar(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title.upper()
        self.setMinimumHeight(58)
        self.setMaximumWidth(1160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(8, 4, -8, -4)

        app = QApplication.instance()
        app_family = app.property("appFontFamily") if app is not None else None
        family = app_family or "Segoe UI"
        title_rect = rect.adjusted(98, -2, -98, -16)
        painter.setFont(_fitted_font(family, self.title, title_rect, max_size=23, min_size=11))

        baseline = rect.bottom() - 12
        center = rect.center().x()
        painter.setPen(QPen(BORDER, 1))
        painter.drawLine(QPointF(rect.left() + 96, baseline), QPointF(center - 180, baseline))
        painter.drawLine(QPointF(center + 180, baseline), QPointF(rect.right() - 96, baseline))
        painter.setPen(QPen(ACCENT, 2))
        painter.drawLine(QPointF(center - 72, baseline), QPointF(center + 72, baseline))
        painter.setPen(QPen(TEXT, 1))
        painter.drawText(title_rect, Qt.AlignCenter, self.title)


class PageShell(QWidget):
    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self.setObjectName("page")

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.header = CnlTitleBar(title)

        subheader = QLabel(subtitle)
        subheader.setObjectName("subheader")
        subheader.hide()

        self.layout.addSpacing(2)
        self.layout.addWidget(self.header, 0, Qt.AlignHCenter)
        self.layout.addWidget(subheader)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        gradient = QLinearGradient(0, self.height(), self.width(), 0)
        gradient.setColorAt(0, QColor("#0b1120"))
        gradient.setColorAt(0.55, QColor("#0f172a"))
        gradient.setColorAt(1, QColor("#111827"))
        painter.fillRect(self.rect(), gradient)


class CategoryPage(PageShell):
    def __init__(
        self,
        title: str,
        pages: list[PageSpec],
        show_home: Callable[[], None],
        open_page: Callable[[str, str], None],
        columns: int = 2,
    ) -> None:
        super().__init__(title, "Select a UI page")

        nav = QHBoxLayout()
        back_button = CnlBackButton("Back Home")
        back_button.clicked.connect(lambda checked=False: show_home())
        nav.addWidget(back_button)
        nav.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        nav.setContentsMargins(52, 10, 52, 10)
        nav.setSpacing(14)
        self.layout.addLayout(nav)

        panel = QFrame()
        panel.setObjectName("workspace")
        grid = QGridLayout(panel)
        grid.setContentsMargins(54, 34, 54, 46)
        grid.setHorizontalSpacing(22)
        grid.setVerticalSpacing(22)
        for column in range(columns):
            grid.setColumnStretch(column, 1)

        for index, (page_title, purpose) in enumerate(pages):
            button = CnlTransitionButton(page_title, purpose)
            button.clicked.connect(
                lambda checked=False, title=page_title, text=purpose: open_page(
                    title, text
                )
            )
            grid.addWidget(button, index // columns, index % columns)
            grid.setRowStretch(index // columns, 1)

        self.layout.addWidget(panel, 1)


class DetailPage(PageShell):
    def __init__(
        self,
        title: str,
        subtitle: str,
        back_label: str,
        go_back: Callable[[], None],
    ) -> None:
        super().__init__(title, subtitle)

        nav = QHBoxLayout()
        back_button = CnlBackButton(back_label)
        back_button.clicked.connect(lambda checked=False: go_back())
        nav.addWidget(back_button)
        nav.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        nav.setContentsMargins(52, 8, 52, 8)
        nav.setSpacing(14)
        self.layout.addLayout(nav)

    def add_workspace(self) -> tuple[QFrame, QVBoxLayout]:
        panel = QFrame()
        panel.setObjectName("workspace")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(24, 14, 24, 24)
        panel_layout.setSpacing(16)
        self.layout.addWidget(panel, 1)
        return panel, panel_layout


class MonitoringDetailPage(DetailPage):
    def __init__(
        self,
        title: str,
        subtitle: str,
        channels: list[str],
        back_label: str,
        go_back: Callable[[], None],
    ) -> None:
        super().__init__(title, subtitle, back_label, go_back)
        self.monitor_title = title
        self.channels = channels
        self.monitor_plot_state = monitoring_plot_state()
        self.metric_cards: list[QLabel] = []
        panel, panel_layout = self.add_workspace()

        controls = QHBoxLayout()
        self.connect_button = QPushButton("Connect")
        self.pause_button = QPushButton("Pause")
        self.export_button = QPushButton("Export CSV")
        for button in (self.connect_button, self.pause_button, self.export_button):
            button.setCursor(Qt.PointingHandCursor)
            controls.addWidget(button)
        controls.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        panel_layout.addLayout(controls)

        metric_grid = QGridLayout()
        metric_grid.setSpacing(12)
        for index, channel in enumerate(channels):
            metric = QLabel(f"{channel}\n--")
            metric.setObjectName("metricCard")
            metric.setAlignment(Qt.AlignCenter)
            metric_grid.addWidget(metric, index // 3, index % 3)
            self.metric_cards.append(metric)
        panel_layout.addLayout(metric_grid)

        self.chart = QLabel("Live chart area")
        self.chart.setObjectName("chartPlaceholder")
        self.chart.setAlignment(Qt.AlignCenter)
        self.chart.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        panel_layout.addWidget(self.chart, 1)

        self.table = QTableWidget(len(channels), 3)
        self.table.setHorizontalHeaderLabels(["Channel", "Value", "Status"])
        for row, channel in enumerate(channels):
            self.table.setItem(row, 0, QTableWidgetItem(channel))
            self.table.setItem(row, 1, QTableWidgetItem("--"))
            self.table.setItem(row, 2, QTableWidgetItem("Idle"))
        panel_layout.addWidget(self.table)
        panel.setLayout(panel_layout)

        self.visibility_timer = QTimer(self)
        self.visibility_timer.timeout.connect(self._refresh_plot_visibility)
        self.visibility_timer.start(250)
        self._refresh_plot_visibility()

    def _refresh_plot_visibility(self) -> None:
        enabled = self.monitor_plot_state.enabled_channels(self.monitor_title, self.channels)
        enabled_set = set(enabled)
        for index, card in enumerate(self.metric_cards):
            if index < len(self.channels):
                card.setVisible(self.channels[index] in enabled_set)
        for row, channel in enumerate(self.channels):
            self.table.setRowHidden(row, channel not in enabled_set)
        if enabled:
            self.chart.setText(
                f"Live chart area\nPlotting {len(enabled)}/{len(self.channels)} variables"
            )
        else:
            self.chart.setText("Live chart area\nPlot toggles are off")


MONITOR_PREVIEWS: dict[str, list[str]] = {
    "Magnetic Field Monitoring": [
        "Live B-field vector trace",
        "Supply current convergence",
        "Magnet temperature bands",
    ],
    "Beam Transport Monitoring": [
        "Transport channel profile",
        "Quadrupole response map",
        "Beamline stability view",
    ],
    "Beam Source & Extraction": [
        "Source current telemetry",
        "Extraction aperture trend",
        "Ion source health scan",
    ],
    "Vacuum / Beam Monitoring": [
        "Vacuum pressure timeline",
        "Beam intensity overlay",
        "Interlock status preview",
    ],
    "Database History": [
        "Logged channel timelines",
        "Run history and CSV export",
        "SQLite readings review",
    ],
    "RF Power Monitoring": [
        "Forward/reflected RF power",
        "Cavity phase response",
        "Amplifier status preview",
    ],
}


class MonitorMockupPage(PageShell):
    def __init__(
        self,
        pages: list[PageSpec],
        show_home: Callable[[], None],
        open_page: Callable[[str, str], None],
    ) -> None:
        super().__init__("Monitor Page", "")
        self.pages = pages
        self.open_page = open_page
        self.selected_index = 0
        self.selection_buttons: list[CnlMonitorSelectionButton] = []
        self.setFocusPolicy(Qt.StrongFocus)

        nav = QHBoxLayout()
        nav.setContentsMargins(52, 10, 52, 10)
        nav.setSpacing(14)
        back_button = CnlBackButton("Back Home")
        back_button.clicked.connect(lambda checked=False: show_home())
        nav.addWidget(back_button)
        nav.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        self.layout.addLayout(nav)

        self.preview = CnlCircleDisplay()
        for index, (title, purpose) in enumerate(self.pages):
            button = CnlMonitorSelectionButton(title, purpose)
            button.clicked.connect(lambda checked=False, idx=index: self._activate_selection(idx))
            self.selection_buttons.append(button)
        self.arena = CnlRadialMonitorArena(self.preview, self.selection_buttons)
        self.layout.addWidget(self.arena, 1)
        self._set_selected(0)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().showEvent(event)
        self.setFocus(Qt.OtherFocusReason)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API name
        key = event.key()
        if key in (Qt.Key_Up, Qt.Key_W):
            self._set_selected(self.selected_index - 1)
            event.accept()
            return
        if key in (Qt.Key_Down, Qt.Key_S):
            self._set_selected(self.selected_index + 1)
            event.accept()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self._activate_selection(self.selected_index)
            event.accept()
            return
        super().keyPressEvent(event)

    def _set_selected(self, index: int) -> None:
        if not self.selection_buttons:
            return
        self.selected_index = index % len(self.selection_buttons)
        for button_index, button in enumerate(self.selection_buttons):
            button.setProperty("selected", button_index == self.selected_index)
            button.update()
        title, _ = self.pages[self.selected_index]
        self.preview.set_preview(title, MONITOR_PREVIEWS.get(title, ["Telemetry overview"]))

    def _activate_selection(self, index: int) -> None:
        self._set_selected(index)
        title, purpose = self.pages[self.selected_index]
        self.open_page(title, purpose)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API name
        self.setFocus(Qt.MouseFocusReason)
        super().mousePressEvent(event)


class ControlDetailPage(DetailPage):
    def __init__(
        self,
        title: str,
        subtitle: str,
        controls: list[str],
        back_label: str,
        go_back: Callable[[], None],
    ) -> None:
        super().__init__(title, subtitle, back_label, go_back)
        _, panel_layout = self.add_workspace()

        form = QFormLayout()
        form.setSpacing(12)
        self.inputs: dict[str, QDoubleSpinBox] = {}
        for label in controls:
            row = QHBoxLayout()
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            spin = QDoubleSpinBox()
            spin.setRange(0, 100)
            spin.setSuffix(" %")
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(lambda value, target=slider: target.setValue(int(value)))
            row.addWidget(slider, 1)
            row.addWidget(spin)
            form.addRow(label, row)
            self.inputs[label] = spin
        panel_layout.addLayout(form)

        actions = QHBoxLayout()
        for label in ("Apply", "Reset", "Save Preset"):
            button = QPushButton(label)
            button.setCursor(Qt.PointingHandCursor)
            actions.addWidget(button)
        actions.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        panel_layout.addLayout(actions)

        status = QLabel("Ready for hardware/backend hookup")
        status.setObjectName("workspaceBody")
        panel_layout.addWidget(status)


class ToggleDetailPage(DetailPage):
    def __init__(
        self,
        title: str,
        subtitle: str,
        toggles: list[str],
        back_label: str,
        go_back: Callable[[], None],
    ) -> None:
        super().__init__(title, subtitle, back_label, go_back)
        _, panel_layout = self.add_workspace()

        for label in toggles:
            checkbox = QCheckBox(label)
            checkbox.setObjectName("toggleRow")
            panel_layout.addWidget(checkbox)

        panel_layout.addSpacerItem(
            QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding)
        )

        actions = QHBoxLayout()
        for label in ("Apply", "Clear", "Log Event"):
            button = QPushButton(label)
            button.setCursor(Qt.PointingHandCursor)
            actions.addWidget(button)
        actions.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        panel_layout.addLayout(actions)


class ConfigDetailPage(DetailPage):
    def __init__(
        self,
        title: str,
        subtitle: str,
        fields: list[str],
        back_label: str,
        go_back: Callable[[], None],
    ) -> None:
        super().__init__(title, subtitle, back_label, go_back)
        _, panel_layout = self.add_workspace()

        form = QFormLayout()
        form.setSpacing(12)
        for field in fields:
            form.addRow(field, QLineEdit())
        panel_layout.addLayout(form)

        self.table = QTableWidget(4, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Value", "Notes"])
        for row in range(4):
            self.table.setItem(row, 0, QTableWidgetItem(f"Item {row + 1}"))
            self.table.setItem(row, 1, QTableWidgetItem(""))
            self.table.setItem(row, 2, QTableWidgetItem(""))
        panel_layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        for label in ("Load", "Save", "Validate"):
            button = QPushButton(label)
            button.setCursor(Qt.PointingHandCursor)
            actions.addWidget(button)
        actions.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        panel_layout.addLayout(actions)


class SnapshotDetailPage(DetailPage):
    def __init__(self, back_label: str, go_back: Callable[[], None]) -> None:
        super().__init__(
            "Snapshot",
            "Captures current channel state to file",
            back_label,
            go_back,
        )
        _, panel_layout = self.add_workspace()

        form = QFormLayout()
        self.file_name = QLineEdit("snapshot_001.json")
        self.notes = QLineEdit()
        form.addRow("File name", self.file_name)
        form.addRow("Notes", self.notes)
        panel_layout.addLayout(form)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        panel_layout.addWidget(self.progress)

        actions = QHBoxLayout()
        for label in ("Capture", "Preview", "Open Folder"):
            button = QPushButton(label)
            button.setCursor(Qt.PointingHandCursor)
            actions.addWidget(button)
        actions.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        panel_layout.addLayout(actions)


class PlaceholderDialog(QDialog):
    def __init__(self, title: str, purpose: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        heading = QLabel(title)
        heading.setObjectName("dialogHeader")

        description = QLabel(purpose)
        description.setObjectName("dialogBody")
        description.setWordWrap(True)

        placeholder = QLabel("Placeholder window")
        placeholder.setObjectName("dialogPlaceholder")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        close_button = QPushButton("Close")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(self.accept)

        layout.addWidget(heading)
        layout.addWidget(description)
        layout.addWidget(placeholder, 1)
        layout.addWidget(close_button, 0, Qt.AlignRight)
