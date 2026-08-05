from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QStackedWidget,
    QWidget,
)
from PySide6.QtGui import QFontDatabase
from pathlib import Path
from threading import Event, Thread

from python.app.Automation.AutomationPage import AutomationPage
from python.app.Automation.ExplorationPage import ExplorationPage
from python.app.Automation.OptimizationPage import OptimizationPage
from python.app.Automation.PidControlPage import PidControlPage
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
from source.Python.Data.pipeline_manager import DataPipelineManager
from source.Python.Data.pipeline_schema import DEFAULT_DB_PATH


PAGE_BUILDERS = {
    "Monitoring": MonitoringPage,
    "Manual Controls": ManualControlsPage,
    "Configuration": ConfigurationPage,
    "Automation": AutomationPage,
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
    "Exploration": ("Automation", ExplorationPage),
    "PID Control": ("Automation", PidControlPage),
    "Assisted Tuning": ("Automation", OptimizationPage),
}


class MainWindow(QMainWindow):
    def __init__(
        self,
        backend_mode: str,
        zmq_endpoint: str,
        simulation_mode: str | None = None,
        enable_data_pipeline: bool = False,
        db_path: str | Path = DEFAULT_DB_PATH,
    ) -> None:
        super().__init__()

        self.backend_mode = backend_mode
        self.zmq_endpoint = zmq_endpoint
        self.simulation_mode = simulation_mode
        self.enable_data_pipeline = enable_data_pipeline
        self.db_path = Path(db_path)
        self._data_pipeline: DataPipelineManager | None = None

        mode_title = simulation_mode or backend_mode
        self.setWindowTitle(f"Crocker Digitalization GUI - {mode_title.upper()}")
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
            if title in {"Field Ctrl", "PID Control", "Assisted Tuning"}:
                field_backend_mode = (
                    "zmq" if self.simulation_mode == "cyclotron" else self.backend_mode
                )
                detail_page = page_builder(
                    lambda checked=False, category=parent_category: self.show_category(
                        category
                    ),
                    backend_mode=field_backend_mode,
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
        if self.simulation_mode == "cyclotron":
            self._start_cyclotron_plant()
        if self.enable_data_pipeline:
            self._start_data_pipeline()

    def _load_app_font(self) -> str:
        font_path = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "FuturisticArmour-1p84.ttf"
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id == -1:
            return "Segoe UI"
        families = QFontDatabase.applicationFontFamilies(font_id)
        return families[0] if families else "Segoe UI"

    def _start_cyclotron_plant(self) -> None:
        from source.Python.Simulator.ZMQSimulator import CyclotronPlant, ZMQSimulator

        self._cyclotron_stop = Event()
        endpoint = self.zmq_endpoint.replace("0.0.0.0", "127.0.0.1")

        def run_plant() -> None:
            simulator = ZMQSimulator(endpoint)
            simulator.stream(
                rate_hz=20.0,
                stop_event=self._cyclotron_stop,
                plant=CyclotronPlant(),
            )

        self._cyclotron_thread = Thread(
            target=run_plant,
            name="cyclotron-zmq-plant",
            daemon=True,
        )
        self._cyclotron_thread.start()

    def _start_data_pipeline(self) -> None:
        crocker_root = Path(__file__).resolve().parents[2]
        db_path = self.db_path
        if not db_path.is_absolute():
            db_path = crocker_root / db_path
        self._data_pipeline = DataPipelineManager(
            crocker_root=crocker_root,
            db_path=db_path,
            source="smoke",
            rate_hz=20.0,
        )
        self._data_pipeline.start()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if self._data_pipeline is not None:
            self._data_pipeline.stop()
        stop = getattr(self, "_cyclotron_stop", None)
        if stop is not None:
            stop.set()
        super().closeEvent(event)

    def show_home(self) -> None:
        self.stack.setCurrentWidget(self.pages["Home"])

    def show_category(self, category: str) -> None:
        self.stack.setCurrentWidget(self.pages[category])

    def open_placeholder(self, title: str, purpose: str) -> None:
        self.stack.setCurrentWidget(self.pages[title])

    def apply_styles(self) -> None:
        app_font = self._load_app_font()
        app = QApplication.instance()
        if app is not None:
            app.setProperty("appFontFamily", app_font)
        self.setStyleSheet(
            """
            QStackedWidget#root,
            QWidget#page,
            QDialog {
                background: transparent;
                color: #6df8ff;
                font-family: "__APP_FONT__", Segoe UI, Arial, sans-serif;
                font-size: 14px;
            }

            QLabel#header {
                background: transparent;
                border: none;
                color: #6df8ff;
                font-family: "__APP_FONT__", Segoe UI, Arial, sans-serif;
                font-size: 20px;
                font-weight: 700;
                padding: 0;
            }

            QLabel#subheader {
                color: #6df8ff;
                font-size: 15px;
            }

            QFrame#workspace {
                background-color: rgba(3, 12, 12, 0.90);
                border: 1px solid #35f4ff;
                border-radius: 12px;
            }

            QPushButton {
                background-color: rgba(5, 17, 18, 0.94);
                border: 1px solid #35f4ff;
                border-radius: 4px;
                color: #6df8ff;
                font-weight: 600;
                min-height: 34px;
                padding: 6px 12px;
                text-align: left;
            }

            QPushButton#backButton {
                max-width: 150px;
                text-align: center;
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
                background-color: rgba(23, 66, 68, 0.92);
                border-color: #b9fbff;
            }

            QPushButton:pressed {
                background-color: rgba(119, 29, 45, 0.55);
                border-color: #ff5169;
            }

            QSplitter::handle {
                background-color: rgba(53, 244, 255, 0.20);
            }

            QScrollBar:vertical,
            QScrollBar:horizontal {
                background-color: rgba(2, 10, 12, 0.96);
                border: 1px solid rgba(53, 244, 255, 0.28);
                margin: 0;
            }

            QScrollBar::handle:vertical,
            QScrollBar::handle:horizontal {
                background-color: rgba(53, 244, 255, 0.45);
                border-radius: 3px;
                min-height: 24px;
                min-width: 24px;
            }

            QScrollBar::add-line,
            QScrollBar::sub-line {
                height: 0;
                width: 0;
            }

            QLabel#workspaceTitle {
                font-size: 18px;
                font-family: "__APP_FONT__", Segoe UI, Arial, sans-serif;
                font-weight: 700;
            }

            QLabel#workspaceBody {
                color: #b9fbff;
                font-size: 16px;
            }

            QLabel#dialogHeader {
                color: #6df8ff;
                font-family: "__APP_FONT__", Segoe UI, Arial, sans-serif;
                font-size: 24px;
                font-weight: 700;
            }

            QLabel#dialogBody,
            QLabel#dialogPlaceholder {
                color: #b9fbff;
                font-size: 15px;
            }

            QLabel#dialogPlaceholder {
                background-color: rgba(4, 14, 15, 0.92);
                border: 1px solid rgba(53, 244, 255, 0.60);
                border-radius: 8px;
            }

            QLabel#metricCard {
                background-color: rgba(4, 17, 18, 0.92);
                border: 1px solid rgba(53, 244, 255, 0.48);
                border-radius: 8px;
                color: #d8fdff;
                font-size: 15px;
                font-weight: 600;
                min-height: 74px;
                padding: 10px;
            }

            QLabel#chartPlaceholder {
                background-color: rgba(0, 0, 0, 0.72);
                border: 1px solid rgba(53, 244, 255, 0.55);
                border-radius: 8px;
                color: #6df8ff;
                font-size: 16px;
                min-height: 170px;
            }

            QLineEdit,
            QDoubleSpinBox,
            QComboBox,
            QTableWidget {
                background-color: rgba(2, 12, 13, 0.96);
                border: 1px solid rgba(53, 244, 255, 0.58);
                border-radius: 5px;
                color: #d8fdff;
                min-height: 28px;
                selection-background-color: rgba(189, 48, 68, 0.55);
                selection-color: #ffffff;
            }

            QTableWidget {
                gridline-color: rgba(53, 244, 255, 0.22);
                alternate-background-color: rgba(16, 38, 38, 0.68);
            }

            QHeaderView::section {
                background-color: rgba(5, 17, 18, 0.98);
                border: 1px solid rgba(53, 244, 255, 0.42);
                color: #6df8ff;
                font-weight: 600;
                padding: 5px;
            }

            QCheckBox#toggleRow {
                color: #d8fdff;
                font-size: 16px;
                min-height: 36px;
            }

            QProgressBar {
                background-color: rgba(2, 12, 13, 0.96);
                border: 1px solid rgba(53, 244, 255, 0.58);
                border-radius: 6px;
                color: #d8fdff;
                min-height: 24px;
                text-align: center;
            }

            QProgressBar::chunk {
                background-color: #35f4ff;
                border-radius: 5px;
            }

            QWidget#fieldController {
                background: transparent;
            }

            QLabel#fieldInstruction {
                background-color: rgba(4, 14, 15, 0.78);
                border: 1px solid rgba(53, 244, 255, 0.52);
                border-radius: 8px;
                color: #d8fdff;
                font-size: 14px;
                font-weight: 600;
                min-height: 44px;
                padding: 8px 12px;
            }

            QLabel#fieldHeader {
                color: #d8fdff;
                font-family: "__APP_FONT__", Segoe UI, Arial, sans-serif;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 0;
            }

            QPushButton#fieldBulk {
                background-color: rgba(5, 17, 18, 0.94);
                border: 1px solid rgba(53, 244, 255, 0.58);
                color: #d8fdff;
                min-height: 26px;
                padding: 3px 8px;
                text-align: center;
            }

            QFrame#fieldBackendStatus {
                background-color: rgba(4, 14, 15, 0.90);
                border: 1px solid rgba(53, 244, 255, 0.52);
                border-radius: 10px;
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
                color: #d8fdff;
                font-size: 12px;
                font-weight: 700;
            }

            QFrame#fieldRow {
                background-color: rgba(2, 10, 12, 0.92);
                border: 1px solid rgba(53, 244, 255, 0.32);
                border-radius: 8px;
            }

            QFrame#fieldRow[selected="true"] {
                background-color: rgba(18, 74, 77, 0.76);
                border: 2px solid rgba(109, 248, 255, 0.92);
            }

            QLabel#fieldName {
                color: #d8fdff;
                font-size: 13px;
                font-weight: 700;
            }

            QLabel#fieldValue {
                background-color: rgba(3, 18, 19, 0.96);
                border: 1px solid rgba(53, 244, 255, 0.58);
                border-radius: 4px;
                color: #8fffd2;
                font-family: "__APP_FONT__", Consolas, monospace;
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
                background-color: rgba(4, 14, 15, 0.90);
                border: 1px solid rgba(53, 244, 255, 0.42);
                border-radius: 10px;
                color: #d8fdff;
                font-weight: 700;
                min-height: 58px;
                padding: 8px;
            }

            QLabel#fieldEditorTitle {
                color: #8fffd2;
                font-family: "__APP_FONT__", Segoe UI, Arial, sans-serif;
                font-size: 15px;
                font-weight: 700;
                min-width: 120px;
            }

            QDoubleSpinBox#fieldTargetInput {
                background-color: rgba(3, 18, 19, 0.96);
                border: 1px solid rgba(53, 244, 255, 0.70);
                border-radius: 5px;
                color: #8fffd2;
                font-family: "__APP_FONT__", Consolas, monospace;
                font-size: 18px;
                font-weight: 700;
                min-height: 40px;
                min-width: 260px;
                padding: 4px 10px;
            }

            QFrame#fieldDigitAdjuster {
                background-color: rgba(2, 10, 12, 0.90);
                border: 1px solid rgba(53, 244, 255, 0.38);
                border-radius: 8px;
                padding: 0;
            }

            QLabel#fieldDigit {
                background-color: rgba(3, 18, 19, 0.96);
                border: 1px solid rgba(53, 244, 255, 0.54);
                border-radius: 4px;
                color: #8fffd2;
                font-family: "__APP_FONT__", Consolas, monospace;
                font-size: 20px;
                font-weight: 700;
                max-height: 36px;
                min-height: 36px;
                min-width: 42px;
                padding: 1px 4px;
            }

            QLabel#fieldDigit[selected="true"] {
                background-color: rgba(25, 93, 96, 0.92);
                border: 2px solid rgba(143, 255, 210, 0.95);
                color: #eaffff;
            }

            QLabel#fieldDigitDecimal {
                color: #d8fdff;
                font-family: "__APP_FONT__", Consolas, monospace;
                font-size: 20px;
                font-weight: 700;
                max-height: 34px;
                min-height: 34px;
                min-width: 8px;
            }

            QPushButton#fieldDigitArrow {
                background-color: rgba(5, 17, 18, 0.94);
                border: 1px solid rgba(53, 244, 255, 0.46);
                border-radius: 4px;
                color: #8fffd2;
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
                background-color: rgba(2, 10, 12, 0.96);
                border: 1px solid rgba(53, 244, 255, 0.55);
                border-radius: 4px;
                height: 10px;
            }

            QSlider#fieldPowerSlider::sub-page:horizontal {
                background-color: #35f4ff;
                border-radius: 4px;
            }

            QSlider#fieldPowerSlider::handle:horizontal {
                background-color: #8fffd2;
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

            QFrame#pidPanel {
                background-color: rgba(4, 14, 15, 0.90);
                border: 1px solid rgba(53, 244, 255, 0.42);
                border-radius: 10px;
            }

            QLabel#pidTitle {
                color: #d8fdff;
                font-family: "__APP_FONT__", Segoe UI, Arial, sans-serif;
                font-size: 15px;
                font-weight: 700;
            }

            QLabel#pidStatus {
                color: #8fffd2;
                font-family: "__APP_FONT__", Consolas, monospace;
                font-size: 12px;
                font-weight: 700;
            }

            QLabel#pidFieldLabel {
                color: #d8fdff;
                font-size: 12px;
                font-weight: 700;
            }

            QComboBox#pidChannelSelect,
            QDoubleSpinBox#pidSpin {
                background-color: rgba(3, 18, 19, 0.96);
                border: 1px solid rgba(53, 244, 255, 0.48);
                border-radius: 5px;
                color: #eaffff;
                min-height: 28px;
                padding: 3px 8px;
            }

            QPushButton#pidEnable {
                background-color: rgba(5, 35, 34, 0.82);
                border: 1px solid rgba(53, 244, 255, 0.50);
                color: #eaffff;
                min-height: 28px;
                text-align: center;
            }

            QPushButton#pidEnable:checked {
                background-color: rgba(20, 126, 92, 0.82);
                border: 1px solid rgba(234, 255, 255, 0.82);
            }

            QPushButton#pidArm {
                background-color: rgba(77, 40, 20, 0.82);
                border: 1px solid rgba(255, 136, 74, 0.54);
                color: #ffd8c8;
                min-height: 28px;
                text-align: center;
            }

            QPushButton#pidArm:checked {
                background-color: rgba(130, 88, 20, 0.88);
                border: 1px solid rgba(255, 226, 150, 0.82);
            }

            QPushButton#pidStop {
                background-color: rgba(96, 20, 31, 0.84);
                border: 1px solid rgba(255, 81, 105, 0.62);
                color: #ffe4e4;
                min-height: 28px;
                text-align: center;
            }
            """.replace("__APP_FONT__", app_font)
        )


def run_app(
    backend_mode: str,
    zmq_endpoint: str = "tcp://0.0.0.0:5555",
    simulation_mode: str | None = None,
    enable_data_pipeline: bool = False,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    app = QApplication([])
    window = MainWindow(
        backend_mode,
        zmq_endpoint,
        simulation_mode,
        enable_data_pipeline,
        db_path,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(
        "Use python main.py -simulation -smoke, "
        "python main.py -simulation -cyclotron, or python main.py -ZMQ"
    )
