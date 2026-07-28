from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QSizePolicy, QVBoxLayout

from python.app.PageShell import DetailPage


class OptimizationPage(DetailPage):
    def __init__(self, go_back: Callable[[], None]) -> None:
        super().__init__(
            "Optimization",
            "Optimize and stabilize beam performance",
            "Back to Automation",
            go_back,
        )

        _, panel_layout = self.add_workspace()
        workspace = QFrame()
        workspace.setObjectName("fieldEditor")
        workspace.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        summary = QLabel(
            "Bayesian Optimization workspace\n\n"
            "Use this page for tuning experiments that search PID gains or beam settings. "
            "Live PID channel control stays in Field Ctrl so operators can switch a channel "
            "between manual and closed-loop control without starting an optimization run."
        )
        summary.setObjectName("chartPlaceholder")
        summary.setAlignment(Qt.AlignCenter)
        summary.setWordWrap(True)
        summary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(summary, 1)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for row, (name, value) in enumerate(
            (
                ("Objective", "Not configured"),
                ("Search space", "PID gains / channel setpoints"),
                ("Run state", "Idle"),
            )
        ):
            label = QLabel(name)
            label.setObjectName("fieldHeader")
            metric = QLabel(value)
            metric.setObjectName("fieldMetric")
            metric.setAlignment(Qt.AlignCenter)
            grid.addWidget(label, row, 0)
            grid.addWidget(metric, row, 1)
        layout.addLayout(grid)

        panel_layout.addWidget(workspace, 1)
