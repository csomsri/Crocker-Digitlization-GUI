from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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


class PageShell(QWidget):
    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self.setObjectName("page")

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(32, 28, 32, 28)
        self.layout.setSpacing(18)

        header = QLabel(title)
        header.setObjectName("header")

        subheader = QLabel(subtitle)
        subheader.setObjectName("subheader")

        self.layout.addWidget(header)
        self.layout.addWidget(subheader)


class CategoryPage(PageShell):
    def __init__(
        self,
        title: str,
        pages: list[PageSpec],
        show_home: Callable[[], None],
        open_page: Callable[[str, str], None],
    ) -> None:
        super().__init__(title, "Select a UI page")

        nav = QHBoxLayout()
        back_button = QPushButton("Back Home")
        back_button.setCursor(Qt.PointingHandCursor)
        back_button.clicked.connect(lambda checked=False: show_home())
        nav.addWidget(back_button)
        nav.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        self.layout.addLayout(nav)

        panel = QFrame()
        panel.setObjectName("workspace")
        grid = QGridLayout(panel)
        grid.setContentsMargins(24, 24, 24, 24)
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
            grid.addWidget(button, index // 2, index % 2)

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
        back_button.setCursor(Qt.PointingHandCursor)
        back_button.clicked.connect(lambda checked=False: go_back())
        nav.addWidget(back_button)
        nav.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        self.layout.addLayout(nav)

    def add_workspace(self) -> tuple[QFrame, QVBoxLayout]:
        panel = QFrame()
        panel.setObjectName("workspace")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(24, 24, 24, 24)
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
