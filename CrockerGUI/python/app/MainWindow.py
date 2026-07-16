from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from python.app.Automation.AiControlPage import AiControlPage
from python.app.Automation.AiOnOffPage import AiOnOffPage
from python.app.Controls.AlarmPage import AlarmPage
from python.app.Controls.BeamRangePage import BeamRangePage
from python.app.Controls.FieldCtrlPage import FieldCtrlPage
from python.app.Controls.ManualControlsPage import ManualControlsPage
from python.app.HomePage import HomePage
from python.app.Controls.SnapshotPage import SnapshotPage
from python.app.Configuration.ConfigurationPage import ConfigurationPage
from python.app.Configuration.DatabaseMonitoringPage import DatabaseMonitoringPage
from python.app.Configuration.RecallPage import RecallPage
from python.app.Configuration.ScalingPage import ScalingPage
from python.app.Configuration.SettingsPage import SettingsPage
from python.app.Monitoring.BeamSourceExtractionPage import BeamSourceExtractionPage
from python.app.Monitoring.BeamTransportMonitoringPage import BeamTransportMonitoringPage
from python.app.Monitoring.MagneticFieldMonitoringPage import MagneticFieldMonitoringPage
from python.app.Monitoring.MonitoringPage import MonitoringPage
from python.app.Monitoring.RfPowerMonitoringPage import RfPowerMonitoringPage
from python.app.Monitoring.VacuumBeamMonitoringPage import VacuumBeamMonitoringPage


PAGE_BUILDERS = {
    "Monitoring": MonitoringPage,
    "Manual Controls": ManualControlsPage,
    "Configuration": ConfigurationPage,
    "AI Control": AiControlPage,
}

DETAIL_BUILDERS = {
    "Magnetic Field Monitoring": ("Monitoring", MagneticFieldMonitoringPage),
    "Beam Transport Monitoring": ("Monitoring", BeamTransportMonitoringPage),
    "Beam Source & Extraction": ("Monitoring", BeamSourceExtractionPage),
    "Vacuum / Beam Monitoring": ("Monitoring", VacuumBeamMonitoringPage),
    "RF Power Monitoring": ("Monitoring", RfPowerMonitoringPage),
    "Field Ctrl": ("Manual Controls", FieldCtrlPage),
    "Beam Range": ("Manual Controls", BeamRangePage),
    "Alarm": ("Manual Controls", AlarmPage),
    "Snapshot": ("Manual Controls", SnapshotPage),
    "Database Monitoring": ("Configuration", DatabaseMonitoringPage),
    "Recall": ("Configuration", RecallPage),
    "Settings": ("Configuration", SettingsPage),
    "Scaling": ("Configuration", ScalingPage),
    "AI ON OFF": ("AI Control", AiOnOffPage),
}


class MainWindow(QMainWindow):
    def __init__(self, backend_mode: str, zmq_endpoint: str) -> None:
        super().__init__()

        self.backend_mode = backend_mode
        self.zmq_endpoint = zmq_endpoint

        self.setWindowTitle(f"Crocker Digitalization GUI - {backend_mode.upper()}")
        self.resize(1500, 900)
        self.setMinimumSize(1280, 820)

        self.stack = QStackedWidget()
        self.stack.setObjectName("root")
        self.pages: dict[str, QWidget] = {}
        self.detail_parent: dict[str, str] = {}

        home = HomePage(list(PAGE_BUILDERS), self.show_category)
        self.stack.addWidget(home)
        self.pages["Home"] = home

        for category, page_builder in PAGE_BUILDERS.items():
            category_page = page_builder(self.show_home, self.open_placeholder)
            self.stack.addWidget(category_page)
            self.pages[category] = category_page

        for title, (parent_category, page_builder) in DETAIL_BUILDERS.items():
            if title == "Field Ctrl":
                detail_page = page_builder(
                    lambda checked=False, category=parent_category: self.show_category(
                        category
                    ),
                    backend_mode=self.backend_mode,
                    zmq_endpoint=self.zmq_endpoint,
                )
                self.stack.addWidget(detail_page)
                self.pages[title] = detail_page
                self.detail_parent[title] = parent_category
                continue

            detail_page = page_builder(
                lambda checked=False, category=parent_category: self.show_category(
                    category
                )
            )
            self.stack.addWidget(detail_page)
            self.pages[title] = detail_page
            self.detail_parent[title] = parent_category

        self.setCentralWidget(self.stack)
        self.apply_styles()

    def show_home(self) -> None:
        self.stack.setCurrentWidget(self.pages["Home"])

    def show_category(self, category: str) -> None:
        self.stack.setCurrentWidget(self.pages[category])

    def open_placeholder(self, title: str, purpose: str) -> None:
        self.stack.setCurrentWidget(self.pages[title])

    def apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QStackedWidget#root,
            QWidget#page,
            QDialog {
                background: qlineargradient(
                    x1: 0, y1: 0,
                    x2: 1, y2: 1,
                    stop: 0 #17202a,
                    stop: 0.45 #253341,
                    stop: 1 #263227
                );
                color: #f4f7f8;
                font-family: Segoe UI, Arial, sans-serif;
                font-size: 14px;
            }

            QLabel#header {
                font-size: 30px;
                font-weight: 700;
            }

            QLabel#subheader {
                color: #bfd0d7;
                font-size: 15px;
            }

            QFrame#workspace {
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 8px;
            }

            QPushButton {
                background-color: rgba(255, 255, 255, 0.12);
                border: 1px solid rgba(255, 255, 255, 0.22);
                border-radius: 6px;
                color: #f4f7f8;
                font-weight: 600;
                min-height: 34px;
                padding: 6px 12px;
                text-align: left;
            }

            QPushButton#categoryButton {
                min-height: 120px;
                min-width: 180px;
                font-size: 17px;
                text-align: center;
            }

            QPushButton#pageButton {
                min-height: 92px;
                font-size: 14px;
            }

            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.18);
                border-color: rgba(255, 255, 255, 0.34);
            }

            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.1);
            }

            QLabel#workspaceTitle {
                font-size: 18px;
                font-weight: 700;
            }

            QLabel#workspaceBody {
                color: #c7d7dc;
                font-size: 16px;
            }

            QLabel#dialogHeader {
                color: #f4f7f8;
                font-size: 24px;
                font-weight: 700;
            }

            QLabel#dialogBody,
            QLabel#dialogPlaceholder {
                color: #d8e8ed;
                font-size: 15px;
            }

            QLabel#dialogPlaceholder {
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 8px;
            }

            QLabel#metricCard {
                background-color: rgba(255, 255, 255, 0.1);
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 8px;
                color: #eef6f8;
                font-size: 15px;
                font-weight: 600;
                min-height: 74px;
                padding: 10px;
            }

            QLabel#chartPlaceholder {
                background-color: rgba(0, 0, 0, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 8px;
                color: #c7d7dc;
                font-size: 16px;
                min-height: 170px;
            }

            QLineEdit,
            QDoubleSpinBox,
            QTableWidget {
                background-color: rgba(255, 255, 255, 0.92);
                border: 1px solid rgba(255, 255, 255, 0.3);
                border-radius: 5px;
                color: #1b252e;
                min-height: 28px;
            }

            QTableWidget {
                gridline-color: #b7c2c8;
                selection-background-color: #5f7f95;
            }

            QHeaderView::section {
                background-color: #dfe8ec;
                color: #1b252e;
                font-weight: 600;
                padding: 5px;
            }

            QCheckBox#toggleRow {
                color: #f4f7f8;
                font-size: 16px;
                min-height: 36px;
            }

            QProgressBar {
                background-color: rgba(255, 255, 255, 0.12);
                border: 1px solid rgba(255, 255, 255, 0.22);
                border-radius: 6px;
                color: #f4f7f8;
                min-height: 24px;
                text-align: center;
            }

            QProgressBar::chunk {
                background-color: #79a98b;
                border-radius: 5px;
            }

            QWidget#fieldController {
                background: transparent;
            }

            QLabel#fieldInstruction {
                background-color: rgba(4, 14, 28, 0.52);
                border: 1px solid rgba(74, 226, 255, 0.28);
                border-radius: 6px;
                color: #dffaff;
                font-size: 14px;
                font-weight: 600;
                min-height: 44px;
                padding: 8px 12px;
            }

            QLabel#fieldHeader {
                color: #d6f6ff;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 0;
            }

            QPushButton#fieldBulk {
                background-color: rgba(0, 28, 42, 0.72);
                border: 1px solid rgba(74, 226, 255, 0.42);
                color: #dffaff;
                min-height: 26px;
                padding: 3px 8px;
                text-align: center;
            }

            QFrame#fieldBackendStatus {
                background-color: rgba(4, 14, 28, 0.62);
                border: 1px solid rgba(74, 226, 255, 0.28);
                border-radius: 6px;
            }

            QLabel#fieldStatusDot {
                background-color: #ff3e3e;
                border: 1px solid rgba(255, 255, 255, 0.58);
                border-radius: 9px;
            }

            QLabel#fieldStatusDot[connected="true"] {
                background-color: #7cffb2;
                border: 1px solid rgba(234, 255, 255, 0.95);
            }

            QLabel#fieldStatusText {
                color: #dffaff;
                font-size: 12px;
                font-weight: 700;
            }

            QFrame#fieldRow {
                background-color: rgba(4, 14, 28, 0.54);
                border: 1px solid rgba(74, 226, 255, 0.25);
                border-radius: 6px;
            }

            QFrame#fieldRow[selected="true"] {
                background-color: rgba(0, 87, 106, 0.68);
                border: 2px solid rgba(92, 244, 255, 0.86);
            }

            QLabel#fieldName {
                color: #e9fbff;
                font-size: 13px;
                font-weight: 700;
            }

            QLabel#fieldValue {
                background-color: rgba(0, 22, 32, 0.72);
                border: 1px solid rgba(0, 208, 255, 0.54);
                border-radius: 4px;
                color: #7cffb2;
                font-family: Consolas, monospace;
                font-size: 14px;
                font-weight: 600;
                min-width: 74px;
                padding: 4px;
            }

            QPushButton#fieldSelect,
            QPushButton#fieldNudge,
            QPushButton#fieldAction,
            QPushButton#fieldDigitArrow {
                text-align: center;
            }

            QPushButton#fieldSelect {
                min-height: 24px;
                padding: 2px 8px;
            }

            QLabel#fieldMetric,
            QFrame#fieldEditor {
                background-color: rgba(4, 14, 28, 0.56);
                border: 1px solid rgba(74, 226, 255, 0.22);
                border-radius: 6px;
                color: #e9fbff;
                font-weight: 700;
                min-height: 58px;
                padding: 8px;
            }

            QLabel#fieldEditorTitle {
                color: #7cffb2;
                font-size: 15px;
                font-weight: 700;
                min-width: 120px;
            }

            QDoubleSpinBox#fieldTargetInput {
                background-color: rgba(0, 20, 30, 0.95);
                border: 1px solid rgba(0, 208, 255, 0.72);
                border-radius: 5px;
                color: #7cffb2;
                font-family: Consolas, monospace;
                font-size: 18px;
                font-weight: 700;
                min-height: 40px;
                min-width: 260px;
                padding: 4px 10px;
            }

            QFrame#fieldDigitAdjuster {
                background-color: rgba(0, 13, 21, 0.54);
                border: 1px solid rgba(0, 208, 255, 0.28);
                border-radius: 6px;
                padding: 0;
            }

            QLabel#fieldDigit {
                background-color: rgba(0, 20, 30, 0.95);
                border: 1px solid rgba(0, 208, 255, 0.50);
                border-radius: 4px;
                color: #7cffb2;
                font-family: Consolas, monospace;
                font-size: 20px;
                font-weight: 700;
                max-height: 36px;
                min-height: 36px;
                min-width: 42px;
                padding: 1px 4px;
            }

            QLabel#fieldDigit[selected="true"] {
                background-color: rgba(0, 102, 122, 0.92);
                border: 2px solid rgba(124, 255, 178, 0.95);
                color: #eaffff;
            }

            QLabel#fieldDigitDecimal {
                color: #dffaff;
                font-family: Consolas, monospace;
                font-size: 20px;
                font-weight: 700;
                max-height: 34px;
                min-height: 34px;
                min-width: 8px;
            }

            QPushButton#fieldDigitArrow {
                background-color: rgba(0, 30, 42, 0.72);
                border: 1px solid rgba(74, 226, 255, 0.32);
                border-radius: 4px;
                color: #7cffb2;
                font-size: 10px;
                font-weight: 700;
                max-height: 26px;
                min-height: 26px;
                min-width: 42px;
                padding: 0;
            }

            QSlider#fieldPowerSlider {
                min-height: 28px;
            }

            QSlider#fieldPowerSlider::groove:horizontal {
                background-color: rgba(0, 24, 34, 0.90);
                border: 1px solid rgba(0, 208, 255, 0.55);
                border-radius: 4px;
                height: 10px;
            }

            QSlider#fieldPowerSlider::sub-page:horizontal {
                background-color: #00d0ff;
                border-radius: 4px;
            }

            QSlider#fieldPowerSlider::handle:horizontal {
                background-color: #7cffb2;
                border: 1px solid #eaffff;
                border-radius: 7px;
                margin: -4px 0;
                width: 16px;
            }

            QPushButton#fieldNudge,
            QPushButton#fieldAction {
                min-height: 28px;
                padding: 4px 8px;
            }

            QPushButton#fieldAction {
                min-height: 34px;
            }
            """
        )


def run_app(backend_mode: str, zmq_endpoint: str = "tcp://0.0.0.0:5555") -> int:
    app = QApplication([])
    window = MainWindow(backend_mode, zmq_endpoint)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit("Use python main.py -simulation or python main.py -ZMQ")
