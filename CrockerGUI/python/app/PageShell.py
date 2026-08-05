from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
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


CYAN = QColor("#35f4ff")
TEXT_CYAN = QColor("#6df8ff")
PANEL_BLACK = QColor("#050a0a")
HUD_RED = QColor("#bd3044")


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

        rect = self.rect().adjusted(2, 2, -2, -2)
        notch = 28
        corner = self.property("corner")
        points = [
            QPointF(rect.left(), rect.top()),
            QPointF(rect.right(), rect.top()),
            QPointF(rect.right(), rect.bottom()),
            QPointF(rect.left(), rect.bottom()),
        ]
        if corner == "top-left":
            points = [
                QPointF(rect.left() + notch, rect.top()),
                QPointF(rect.right(), rect.top()),
                QPointF(rect.right(), rect.bottom()),
                QPointF(rect.left(), rect.bottom()),
                QPointF(rect.left(), rect.top() + notch),
            ]
        elif corner == "top-right":
            points = [
                QPointF(rect.left(), rect.top()),
                QPointF(rect.right() - notch, rect.top()),
                QPointF(rect.right(), rect.top() + notch),
                QPointF(rect.right(), rect.bottom()),
                QPointF(rect.left(), rect.bottom()),
            ]
        elif corner == "bottom-left":
            points = [
                QPointF(rect.left(), rect.top()),
                QPointF(rect.right(), rect.top()),
                QPointF(rect.right(), rect.bottom()),
                QPointF(rect.left() + notch, rect.bottom()),
                QPointF(rect.left(), rect.bottom() - notch),
            ]
        elif corner == "bottom-right":
            points = [
                QPointF(rect.left(), rect.top()),
                QPointF(rect.right(), rect.top()),
                QPointF(rect.right(), rect.bottom() - notch),
                QPointF(rect.right() - notch, rect.bottom()),
                QPointF(rect.left(), rect.bottom()),
            ]

        path = QPainterPath()
        path.addPolygon(QPolygonF(points))
        path.closeSubpath()
        painter.fillPath(path, PANEL_BLACK)
        painter.fillPath(path, QColor(16, 38, 38, 82))
        pen_width = 3 if self.underMouse() else 2
        painter.setPen(QPen(CYAN, pen_width))
        painter.drawPath(path)
        painter.setPen(QPen(HUD_RED, 1))
        painter.drawLine(QPointF(rect.left() + 18, rect.top() + 8), QPointF(rect.left() + 72, rect.top() + 8))
        painter.drawLine(QPointF(rect.right() - 88, rect.bottom() - 8), QPointF(rect.right() - 18, rect.bottom() - 8))

        app = QApplication.instance()
        app_family = app.property("appFontFamily") if app is not None else None
        family = app_family or "Segoe UI"
        font = _fitted_font(family, self.text(), rect, max_size=24, min_size=9)
        painter.setFont(font)
        painter.setPen(QPen(QColor("#003744"), 5))
        painter.drawText(rect, Qt.AlignCenter, self.text())
        painter.setPen(QPen(TEXT_CYAN, 1))
        painter.drawText(rect, Qt.AlignCenter, self.text())


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
        painter.fillRect(rect, PANEL_BLACK)
        painter.fillRect(rect.adjusted(10, 10, -10, -10), QColor(4, 20, 19, 150))
        painter.setPen(QPen(CYAN, 2))
        painter.drawRect(rect)
        painter.setPen(QPen(QColor("#153336"), 1))
        for x in range(int(rect.left()) + 40, int(rect.right()), 42):
            painter.drawLine(QPointF(x, rect.top() + 18), QPointF(x + 18, rect.top() + 18))
        painter.setPen(QPen(HUD_RED, 1))
        painter.drawLine(QPointF(rect.left() + 22, rect.bottom() - 18), QPointF(rect.left() + 120, rect.bottom() - 18))
        painter.drawLine(QPointF(rect.right() - 160, rect.top() + 18), QPointF(rect.right() - 42, rect.top() + 18))

        app = QApplication.instance()
        app_family = app.property("appFontFamily") if app is not None else None
        family = app_family or "Segoe UI"
        painter.setFont(_fitted_font(family, "CYCLOVIZ VIEWPORT", rect, max_size=20, min_size=10))
        painter.setPen(QPen(QColor("#003744"), 5))
        painter.drawText(rect, Qt.AlignCenter, "CYCLOVIZ VIEWPORT")
        painter.setPen(QPen(TEXT_CYAN, 1))
        painter.drawText(rect, Qt.AlignCenter, "CYCLOVIZ VIEWPORT")


class CnlCircleDisplay(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(360, 360)
        self.title = "Monitoring"
        self.preview_lines: list[str] = []

    def set_preview(self, title: str, lines: list[str]) -> None:
        self.title = title
        self.preview_lines = lines
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        size = min(self.width(), self.height()) - 8
        rect = QRectF(
            (self.width() - size) / 2,
            (self.height() - size) / 2,
            size,
            size,
        )
        painter.setBrush(QColor("#050909"))
        painter.setPen(QPen(CYAN, 2))
        painter.drawEllipse(rect)
        painter.setPen(QPen(QColor("#15383b"), 1))
        painter.drawEllipse(rect.adjusted(24, 24, -24, -24))
        painter.drawEllipse(rect.adjusted(58, 58, -58, -58))

        center = rect.center()
        painter.setPen(QPen(QColor("#214f52"), 1))
        painter.drawLine(QPointF(center.x(), rect.top() + 28), QPointF(center.x(), rect.bottom() - 28))
        painter.drawLine(QPointF(rect.left() + 28, center.y()), QPointF(rect.right() - 28, center.y()))

        painter.setPen(QPen(HUD_RED, 1))
        for index in range(5):
            y = rect.top() + 96 + index * 34
            painter.drawLine(QPointF(center.x() - 125, y), QPointF(center.x() + 40 + index * 12, y + 18))

        app = QApplication.instance()
        app_family = app.property("appFontFamily") if app is not None else None
        family = app_family or "Segoe UI"
        title_rect = QRectF(rect.left() + 70, rect.top() + 72, rect.width() - 140, 58)
        painter.setFont(_fitted_font(family, self.title.upper(), title_rect, max_size=20, min_size=9))
        painter.setPen(QPen(QColor("#113437"), 5))
        painter.drawText(title_rect, Qt.AlignCenter, self.title.upper())
        painter.setPen(QPen(TEXT_CYAN, 1))
        painter.drawText(title_rect, Qt.AlignCenter, self.title.upper())

        painter.setFont(_fitted_font(family, "DATA VISUALIZATION PREVIEW", rect, max_size=10, min_size=7, weight=QFont.Normal))
        painter.setPen(QColor(216, 253, 255, 190))
        text_y = center.y() + 20
        for line in self.preview_lines[:4]:
            painter.drawText(
                QRectF(rect.left() + 96, text_y, rect.width() - 192, 28),
                Qt.AlignCenter,
                line.upper(),
            )
            text_y += 34


class CnlMonitorSelectionButton(QPushButton):
    def __init__(self, title: str, description: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.description = description
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(86)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFlat(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet("background: transparent; border: 0; color: transparent;")

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        selected = bool(self.property("selected"))
        circle_size = min(62, self.height() - 10)
        circle = QRectF(4, (self.height() - circle_size) / 2, circle_size, circle_size)
        box = QRectF(circle.right() + 28, (self.height() - 52) / 2, self.width() - circle.right() - 34, 52)

        fill = QColor("#071313")
        if selected:
            fill = QColor("#35f4ff")
        painter.setBrush(fill)
        painter.setPen(QPen(CYAN, 3 if selected else 2))
        painter.drawEllipse(circle)

        painter.setBrush(QColor("#071313"))
        painter.setPen(QPen(CYAN, 3 if selected else 2))
        painter.drawRoundedRect(box, 3, 3)
        painter.setPen(QPen(HUD_RED, 1))
        painter.drawLine(QPointF(box.left() + 8, box.bottom() - 7), QPointF(box.left() + 58, box.bottom() - 7))

        app = QApplication.instance()
        app_family = app.property("appFontFamily") if app is not None else None
        family = app_family or "Segoe UI"
        title_rect = box.adjusted(18, 4, -16, -24)
        painter.setFont(_fitted_font(family, self.title.upper(), title_rect, max_size=13, min_size=7))
        painter.setPen(QPen(QColor("#12363a"), 4))
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, self.title.upper())
        painter.setPen(QPen(TEXT_CYAN if not selected else QColor("#031315"), 1))
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, self.title.upper())

        desc_rect = box.adjusted(18, 34, -16, -5)
        painter.setFont(_fitted_font(family, self.description.upper(), desc_rect, max_size=8, min_size=6, weight=QFont.Normal))
        painter.setPen(QColor(216, 253, 255, 155))
        painter.drawText(desc_rect, Qt.AlignLeft | Qt.AlignVCenter, self.description.upper())


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
        painter.setPen(QPen(QColor("#551924"), 2))
        painter.drawLine(QPointF(rect.left(), baseline + 6), QPointF(center - 150, baseline + 6))
        painter.drawLine(QPointF(center + 150, baseline + 6), QPointF(rect.right(), baseline + 6))

        painter.setPen(QPen(CYAN, 2))
        tab = QPainterPath()
        tab.moveTo(rect.left() + 48, baseline - 2)
        tab.lineTo(center - 235, baseline - 2)
        tab.lineTo(center - 205, baseline - 14)
        tab.lineTo(center + 205, baseline - 14)
        tab.lineTo(center + 235, baseline - 2)
        tab.lineTo(rect.right() - 48, baseline - 2)
        painter.drawPath(tab)

        painter.setPen(QPen(QColor("#2fefff"), 1))
        painter.drawLine(QPointF(rect.left() + 110, baseline), QPointF(center - 180, baseline))
        painter.drawLine(QPointF(center + 180, baseline), QPointF(rect.right() - 110, baseline))

        for x in (center - 170, center + 170):
            accent = QRectF(x - 5, baseline - 5, 10, 10)
            painter.fillRect(accent, QColor("#061a1d"))
            painter.setPen(QPen(CYAN, 1))
            painter.drawRect(accent)

        painter.setPen(QPen(QColor("#1b0508"), 5))
        painter.drawText(title_rect, Qt.AlignCenter, self.title)
        painter.setPen(QPen(QColor("#c84956"), 1))
        painter.drawText(title_rect.translated(1, 1), Qt.AlignCenter, self.title)
        painter.setPen(QPen(TEXT_CYAN, 1))
        painter.drawText(title_rect, Qt.AlignCenter, self.title)


class PageShell(QWidget):
    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self.setObjectName("page")

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        header = CnlTitleBar(title)

        subheader = QLabel(subtitle)
        subheader.setObjectName("subheader")
        subheader.hide()

        self.layout.addSpacing(2)
        self.layout.addWidget(header, 0, Qt.AlignHCenter)
        self.layout.addWidget(subheader)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        gradient = QLinearGradient(0, self.height(), self.width(), 0)
        gradient.setColorAt(0, QColor("#020303"))
        gradient.setColorAt(0.52, QColor("#071313"))
        gradient.setColorAt(1, QColor("#123f42"))
        painter.fillRect(self.rect(), gradient)

        painter.setPen(QPen(QColor(20, 44, 44, 150), 3))
        spacing = 12
        for y in range(5, self.height(), spacing):
            for x in range(5, self.width(), spacing):
                painter.drawPoint(x, y)

        painter.setPen(QPen(QColor(125, 26, 38, 115), 1))
        painter.drawLine(QPointF(18, 38), QPointF(90, 38))
        painter.drawLine(QPointF(self.width() - 220, 26), QPointF(self.width() - 96, 26))
        painter.drawLine(QPointF(self.width() - 96, 26), QPointF(self.width() - 64, 2))
        painter.drawLine(QPointF(30, self.height() - 32), QPointF(180, self.height() - 32))


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
        back_button = QPushButton("Back Home")
        back_button.setObjectName("backButton")
        back_button.setCursor(Qt.PointingHandCursor)
        back_button.clicked.connect(lambda checked=False: show_home())
        nav.addWidget(back_button)
        nav.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        nav.setContentsMargins(36, 6, 36, 0)
        self.layout.addLayout(nav)

        panel = QFrame()
        panel.setObjectName("workspace")
        grid = QGridLayout(panel)
        grid.setContentsMargins(24, 14, 24, 24)
        grid.setSpacing(14)

        for index, (page_title, purpose) in enumerate(pages):
            button = QPushButton(f"{page_title}\n{purpose}")
            button.setObjectName("pageButton")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(
                lambda checked=False, title=page_title, text=purpose: open_page(
                    title, text
                )
            )
            grid.addWidget(button, index // columns, index % columns)

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
        back_button = QPushButton(back_label)
        back_button.setObjectName("backButton")
        back_button.setCursor(Qt.PointingHandCursor)
        back_button.clicked.connect(lambda checked=False: go_back())
        nav.addWidget(back_button)
        nav.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
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
        panel_layout.addLayout(metric_grid)

        chart = QLabel("Live chart area")
        chart.setObjectName("chartPlaceholder")
        chart.setAlignment(Qt.AlignCenter)
        chart.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        panel_layout.addWidget(chart, 1)

        self.table = QTableWidget(len(channels), 3)
        self.table.setHorizontalHeaderLabels(["Channel", "Value", "Status"])
        for row, channel in enumerate(channels):
            self.table.setItem(row, 0, QTableWidgetItem(channel))
            self.table.setItem(row, 1, QTableWidgetItem("--"))
            self.table.setItem(row, 2, QTableWidgetItem("Idle"))
        panel_layout.addWidget(self.table)
        panel.setLayout(panel_layout)


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
        nav.setContentsMargins(36, 4, 36, 0)
        back_button = QPushButton("Back Home")
        back_button.setObjectName("backButton")
        back_button.setCursor(Qt.PointingHandCursor)
        back_button.clicked.connect(lambda checked=False: show_home())
        nav.addWidget(back_button)
        nav.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        self.layout.addLayout(nav)

        body = QHBoxLayout()
        body.setContentsMargins(78, 10, 150, 34)
        body.setSpacing(58)

        self.preview = CnlCircleDisplay()
        body.addWidget(self.preview, 4)

        status_column = QVBoxLayout()
        status_column.setSpacing(24)
        status_column.addStretch(1)
        for index, (title, purpose) in enumerate(self.pages):
            button = CnlMonitorSelectionButton(title, purpose)
            button.clicked.connect(lambda checked=False, idx=index: self._activate_selection(idx))
            self.selection_buttons.append(button)
            status_column.addWidget(button)
        status_column.addStretch(1)
        body.addLayout(status_column, 3)
        self.layout.addLayout(body, 1)
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
