from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QStackedWidget,
    QWidget,
)
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QFontDatabase
from pathlib import Path
from threading import Event, Thread

from python.app.Automation.AutomationPage import AutomationPage
from python.app.Automation.PidControlPage import PidControlPage
from python.app.CyberpunkMotion import CyberpunkMotionController
from python.app.Controls.AlarmPage import AlarmPage
from python.app.Controls.BeamRangePage import BeamRangePage
from python.app.Controls.FieldCtrlPage import FieldCtrlPage
from python.app.Controls.ManualControlsPage import ManualControlsPage
from python.app.HomePage import HomePage
from python.app.Controls.SnapshotPage import SnapshotPage
from python.app.Configuration.ConfigurationPage import ConfigurationPage
from python.app.Configuration.DatabaseMonitoringPage import (
    DatabaseMonitoringPage,
)
from python.app.Configuration.RecallPage import RecallPage
from python.app.Configuration.ScalingPage import ScalingPage
from python.app.Configuration.SettingsPage import SettingsPage
from python.app.Display.AssignedMonitorWindow import AssignedMonitorWindow
from python.app.Monitoring.BeamSourceExtractionPage import (
    BeamSourceExtractionPage,
)
from python.app.Monitoring.BeamTransportMonitoringPage import (
    BeamTransportMonitoringPage,
)
from python.app.Monitoring.MagneticFieldMonitoringPage import (
    MagneticFieldMonitoringPage,
)
from python.app.Monitoring.MonitoringPage import MonitoringPage
from python.app.Monitoring.RfPowerMonitoringPage import RfPowerMonitoringPage
from python.app.Monitoring.VacuumBeamMonitoringPage import (
    VacuumBeamMonitoringPage,
)
from source.Python.Data.pipeline_manager import DataPipelineManager
from source.Python.Data.pipeline_schema import DEFAULT_DB_PATH


PAGE_BUILDERS = {
    "Monitoring": MonitoringPage,
    "Manual Controls": ManualControlsPage,
    "Automation": AutomationPage,
    "Configuration": ConfigurationPage,
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
    "PID Control": ("Automation", PidControlPage),
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
        self._settings = QSettings("Crocker Nuclear Lab", "Digitalization")
        self._display_mode = self._settings.value(
            "display/mode", "Windowed", type=str
        )
        valid_modes = {"Windowed", "Borderless Window", "Full Screen"}
        if self._display_mode not in valid_modes:
            self._display_mode = "Windowed"
        self._windowed_geometry = None
        self._display_transition = 0
        self._monitor_windows: dict[str, AssignedMonitorWindow] = {}

        mode_title = simulation_mode or backend_mode
        self.setWindowTitle(
            f"Crocker Digitalization GUI - {mode_title.upper()}"
        )
        self.setMinimumSize(1280, 820)
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            # Leave room for the Windows frame and taskbar. At non-100% display
            # scaling, requesting a 1500x900 client area can exceed a 1500x900
            # logical desktop once native frame margins are added.
            initial_width = max(1280, min(1500, available.width() - 32))
            initial_height = max(820, min(900, available.height() - 64))
            self.resize(initial_width, initial_height)
        else:
            self.resize(1500, 900)

        self.stack = QStackedWidget()
        self.stack.setObjectName("root")
        self.pages: dict[str, QWidget] = {}
        self.detail_parent: dict[str, str] = {}

        home = HomePage(list(PAGE_BUILDERS), self.show_category, self.close)
        self.stack.addWidget(home)
        self.pages["Home"] = home

        for category, page_builder in PAGE_BUILDERS.items():
            category_page = page_builder(self.show_home, self.open_placeholder)
            self.stack.addWidget(category_page)
            self.pages[category] = category_page

        for title, (parent_category, page_builder) in DETAIL_BUILDERS.items():
            if title in {"Field Ctrl", "PID Control"}:
                field_backend_mode = (
                    "zmq"
                    if self.simulation_mode == "cyclotron"
                    else self.backend_mode
                )
                detail_page = page_builder(
                    lambda checked=False, category=parent_category:
                        self.show_category(category),
                    backend_mode=field_backend_mode,
                    zmq_endpoint=self.zmq_endpoint,
                )
                self.stack.addWidget(detail_page)
                self.pages[title] = detail_page
                self.detail_parent[title] = parent_category
                continue

            if title == "Settings":
                detail_page = page_builder(
                    lambda checked=False, category=parent_category:
                        self.show_category(category),
                    set_display_mode=self.set_display_mode,
                    current_display_mode=self._display_mode,
                    monitor_entries=self._monitor_entries(),
                    page_names=self._assignable_page_names(),
                    apply_monitor_assignments=self.apply_monitor_assignments,
                )
                self.stack.addWidget(detail_page)
                self.pages[title] = detail_page
                self.detail_parent[title] = parent_category
                continue

            detail_page = page_builder(
                lambda checked=False, category=parent_category:
                    self.show_category(category)
            )
            self.stack.addWidget(detail_page)
            self.pages[title] = detail_page
            self.detail_parent[title] = parent_category

        self.setCentralWidget(self.stack)
        self.apply_styles()
        self.motion = CyberpunkMotionController(self.stack, self)
        self.motion.attach_to(self)
        if self.simulation_mode == "cyclotron":
            self._start_cyclotron_plant()
        if self.enable_data_pipeline:
            self._start_data_pipeline()
        app = QApplication.instance()
        if app is not None:
            app.screenAdded.connect(lambda screen: self._screens_changed())
            app.screenRemoved.connect(lambda screen: self._screens_changed())
        QTimer.singleShot(
            0,
            lambda: self.set_display_mode(self._display_mode, save=False),
        )
        QTimer.singleShot(100, self._restore_monitor_assignments)

    def _assignable_page_names(self) -> list[str]:
        detail_names = (
            name for name in DETAIL_BUILDERS if name != "Settings"
        )
        return ["Home", *PAGE_BUILDERS.keys(), *detail_names]

    def _monitor_entries(self) -> list[dict[str, object]]:
        main_screen = self.screen()
        entries: list[dict[str, object]] = []
        for screen in QApplication.screens()[:4]:
            name = screen.name()
            entries.append({
                "name": name,
                "occupied": screen is main_screen,
                "assignment": self._settings.value(
                    f"monitors/{name}/page", "", type=str
                ),
            })
        return entries

    def _screens_changed(self) -> None:
        available = {screen.name() for screen in QApplication.screens()}
        for name, window in list(self._monitor_windows.items()):
            if name not in available:
                window.close()
                del self._monitor_windows[name]
        settings_page = self.pages.get("Settings")
        if isinstance(settings_page, SettingsPage):
            settings_page.set_monitor_entries(self._monitor_entries())

    def _restore_monitor_assignments(self) -> None:
        assignments = {
            str(entry["name"]): str(entry["assignment"])
            for entry in self._monitor_entries()
        }
        self.apply_monitor_assignments(assignments)

    def apply_monitor_assignments(self, assignments: dict[str, str]) -> None:
        screens = {
            screen.name(): screen for screen in QApplication.screens()[:4]
        }
        main_screen = self.screen()
        for name, screen in screens.items():
            page_name = assignments.get(name, "")
            self._settings.setValue(f"monitors/{name}/page", page_name)

            if screen is main_screen:
                window = self._monitor_windows.pop(name, None)
                if window is not None:
                    window.close()
                if page_name in self.pages:
                    self.stack.setCurrentWidget(self.pages[page_name])
                continue

            if not page_name:
                window = self._monitor_windows.pop(name, None)
                if window is not None:
                    window.close()
                continue

            window = self._monitor_windows.get(name)
            if window is None:
                window = AssignedMonitorWindow(self, name)
                self._monitor_windows[name] = window
            window.set_page(page_name)
            window.winId()
            handle = window.windowHandle()
            if handle is not None:
                handle.setScreen(screen)
            window.setGeometry(screen.geometry())
            window.showFullScreen()
        self._settings.sync()

    def create_assigned_page(
        self,
        page_name: str,
        host: AssignedMonitorWindow,
    ) -> QWidget:
        if page_name == "Home":
            return HomePage(list(PAGE_BUILDERS), host.set_page, host.close)
        if page_name in PAGE_BUILDERS:
            builder = PAGE_BUILDERS[page_name]
            return builder(
                lambda: host.set_page("Home"),
                lambda title, purpose: host.set_page(title),
            )
        if page_name in DETAIL_BUILDERS:
            parent_category, builder = DETAIL_BUILDERS[page_name]
            go_back = lambda checked=False: host.set_page(parent_category)
            if page_name in {"Field Ctrl", "PID Control"}:
                field_backend_mode = (
                    "zmq"
                    if self.simulation_mode == "cyclotron"
                    else self.backend_mode
                )
                return builder(
                    go_back,
                    backend_mode=field_backend_mode,
                    zmq_endpoint=self.zmq_endpoint,
                )
            return builder(go_back)
        fallback = QWidget()
        return fallback

    def set_display_mode(self, mode: str, save: bool = True) -> None:
        if mode not in {"Windowed", "Borderless Window", "Full Screen"}:
            return

        leaving_normal_window = (
            self._display_mode == "Windowed"
            and self.isVisible()
            and not self.isMaximized()
        )
        if leaving_normal_window:
            self._windowed_geometry = self.geometry()

        self._display_mode = mode
        self._display_transition += 1
        transition = self._display_transition
        if save:
            self._settings.setValue("display/mode", mode)
            self._settings.sync()

        # Changing FramelessWindowHint recreates the native window on Windows.
        # Hide it first, update the flags once, then show it in the requested
        # state. Use a borderless desktop-sized window for Full Screen instead
        # of Qt's native WindowFullScreen state to avoid focus churn on Windows.
        self.hide()
        self.setWindowState(Qt.WindowState.WindowNoState)
        flags = self.windowFlags()
        if mode in {"Borderless Window", "Full Screen"}:
            flags |= Qt.WindowType.FramelessWindowHint
        else:
            flags &= ~Qt.WindowType.FramelessWindowHint
        self.setWindowFlags(flags)

        def finish_transition() -> None:
            if transition != self._display_transition:
                return
            if mode == "Windowed":
                self.setWindowState(Qt.WindowState.WindowNoState)
                self.show()
                if self._windowed_geometry is not None:
                    self.setGeometry(self._windowed_geometry)
            elif mode == "Borderless Window":
                self.setWindowState(Qt.WindowState.WindowMaximized)
                self.show()
            else:
                screen = self.screen() or QApplication.primaryScreen()
                if screen is not None:
                    self.setGeometry(screen.availableGeometry())
                self.setWindowState(Qt.WindowState.WindowNoState)
                self.show()

        QTimer.singleShot(0, finish_transition)

    def _load_app_font(self) -> str:
        font_path = (
            Path(__file__).resolve().parents[2]
            / "assets"
            / "fonts"
            / "FuturisticArmour-1p84.ttf"
        )
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id == -1:
            return "Segoe UI"
        families = QFontDatabase.applicationFontFamilies(font_id)
        return families[0] if families else "Segoe UI"

    def _start_cyclotron_plant(self) -> None:
        from source.Python.Simulator.ZMQSimulator import (
            CyclotronPlant,
            ZMQSimulator,
        )

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
        for window in self._monitor_windows.values():
            window.close()
        self._monitor_windows.clear()
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
                border-radius: 0;
            }

            QFrame#fieldControlWorkspace {
                background-color: rgba(3, 12, 12, 0.90);
                border: 1px solid #35f4ff;
                border-radius: 0;
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

            QPushButton#pidBackButton {
                background-color: rgba(5, 17, 18, 0.94);
                border: 1px solid #35f4ff;
                border-radius: 4px;
                color: #6df8ff;
                margin-left: 18px;
                margin-bottom: 8px;
                max-width: 150px;
                min-height: 34px;
                padding: 6px 12px;
                text-align: center;
            }

            QPushButton#pidBackButton:hover {
                background-color: #35f4ff;
                border-color: #35f4ff;
                color: #031315;
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

            QPushButton#pageButton:hover,
            QPushButton#categoryButton:hover,
            QPushButton#backButton:hover {
                background-color: #35f4ff;
                border-color: #35f4ff;
                color: #031315;
            }

            QLabel#settingsHeading {
                color: #8fffd2;
                font-size: 18px;
                font-weight: 700;
                padding-top: 8px;
            }

            QLabel#settingsDescription {
                color: rgba(216, 253, 255, 0.78);
                font-size: 13px;
                padding-bottom: 6px;
            }

            QFrame#displayModePanel {
                background-color: rgba(2, 10, 11, 0.88);
                border: 1px solid rgba(53, 244, 255, 0.36);
                border-radius: 7px;
            }

            QFrame#monitorMapPanel {
                background-color: rgba(2, 9, 10, 0.94);
                border: 1px solid rgba(53, 244, 255, 0.36);
                border-radius: 8px;
            }

            QLabel#monitorMapHeading {
                color: #d8fdff;
                font-size: 14px;
                font-weight: 700;
                padding: 2px 4px 8px 4px;
            }

            QFrame#monitorCanvas {
                background-color: rgba(10, 25, 26, 0.84);
                border-top: 1px solid rgba(53, 244, 255, 0.18);
                border-radius: 5px;
            }

            QPushButton#monitorTile {
                background-color: rgba(18, 43, 44, 0.92);
                border: 1px solid rgba(53, 244, 255, 0.48);
                border-radius: 8px;
                color: rgba(216, 253, 255, 0.78);
                font-size: 15px;
                font-weight: 700;
                text-align: center;
            }

            QPushButton#monitorTile:hover {
                background-color: rgba(24, 65, 66, 0.96);
                border-color: #b9fbff;
                color: #eaffff;
            }

            QPushButton#monitorTile:checked {
                background-color: rgba(25, 73, 70, 0.96);
                border: 2px solid #8fffd2;
                color: #effff8;
            }

            QLabel#monitorAssignmentLabel {
                color: #8fffd2;
                font-size: 12px;
                font-weight: 700;
                min-width: 180px;
            }

            QComboBox#monitorPageSelect {
                background-color: rgba(2, 10, 11, 0.94);
                border: 1px solid rgba(53, 244, 255, 0.68);
                border-radius: 5px;
                color: #d8fdff;
                min-height: 32px;
                padding: 3px 8px;
            }

            QComboBox#monitorPageSelect:disabled {
                border-color: rgba(143, 255, 210, 0.42);
                color: rgba(143, 255, 210, 0.70);
            }

            QPushButton#displayModeButton {
                min-height: 58px;
                text-align: center;
                font-size: 14px;
            }

            QPushButton#displayModeButton:checked {
                background-color: rgba(20, 126, 92, 0.82);
                border: 2px solid #8fffd2;
                color: #effff8;
            }

            QPushButton#applySettingsButton {
                min-height: 48px;
                background-color: rgba(20, 126, 92, 0.82);
                border: 2px solid #8fffd2;
                color: #effff8;
                font-size: 15px;
                font-weight: 700;
                text-align: center;
            }

            QPushButton#applySettingsButton:hover {
                background-color: rgba(28, 164, 119, 0.92);
                border-color: #d9ffef;
            }

            QPushButton#homeExitButton {
                background-color: rgba(72, 12, 22, 0.88);
                border: 1px solid rgba(255, 81, 105, 0.78);
                color: #ff9aaa;
                font-size: 16px;
                font-weight: 700;
                text-align: center;
            }

            QPushButton#homeExitButton:hover {
                background-color: rgba(125, 20, 35, 0.94);
                border-color: #ff8798;
                color: #fff0f2;
            }

            QPushButton:hover {
                background-color: rgba(12, 43, 46, 0.96);
                border-color: #b9fbff;
                color: #eaffff;
            }

            QPushButton[cyberpunkHover="true"] {
                background-color: rgba(12, 43, 46, 0.98);
                border: 1px solid rgba(185, 251, 255, 0.96);
                color: #eaffff;
            }

            QPushButton:pressed {
                background-color: rgba(119, 29, 45, 0.55);
                border-color: #ff5169;
                color: #ffffff;
            }

            QPushButton[cyberpunkPressed="true"] {
                background-color: rgba(119, 29, 45, 0.68);
                border: 1px solid rgba(255, 81, 105, 0.95);
                color: #ffffff;
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

            QLineEdit:focus,
            QDoubleSpinBox:focus,
            QComboBox:focus {
                background-color: rgba(4, 24, 27, 0.98);
                border: 1px solid rgba(255, 81, 105, 0.82);
                color: #eaffff;
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

            QFrame#pidPanel QCheckBox#toggleRow {
                background-color: rgba(3, 15, 16, 0.82);
                border: 1px solid rgba(53, 244, 255, 0.24);
                border-radius: 6px;
                color: rgba(216, 253, 255, 0.76);
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 13px;
                min-height: 28px;
                padding: 3px 9px;
            }

            QFrame#pidPanel QCheckBox#toggleRow:hover {
                border-color: rgba(53, 244, 255, 0.68);
                color: #eaffff;
            }

            QFrame#pidPanel QCheckBox#toggleRow:checked {
                background-color: rgba(20, 126, 92, 0.64);
                border-color: rgba(143, 255, 210, 0.92);
                color: #eaffff;
            }

            QFrame#pidPanel QCheckBox#toggleRow::indicator {
                background-color: rgba(1, 8, 9, 0.96);
                border: 1px solid rgba(216, 253, 255, 0.48);
                border-radius: 7px;
                height: 14px;
                image: none;
                width: 14px;
            }

            QFrame#pidPanel QCheckBox#toggleRow::indicator:checked {
                background-color: #8fffd2;
                border-color: #eaffff;
                image: none;
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
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #35f4ff,
                    stop: 0.55 #8fffd2,
                    stop: 1 #ff5169
                );
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

            QLabel#pidStatusCard {
                background-color: rgba(2, 10, 11, 0.86);
                border: 1px solid rgba(53, 244, 255, 0.28);
                border-radius: 6px;
                color: #d8fdff;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 11px;
                font-weight: 600;
                padding: 6px 10px;
            }

            QFrame#pidControllerState {
                background-color: rgba(4, 24, 25, 0.92);
                border: 1px solid rgba(143, 255, 210, 0.48);
                border-radius: 6px;
            }

            QLabel#pidControllerMetric {
                background-color: rgba(2, 12, 13, 0.86);
                border: 1px solid rgba(53, 244, 255, 0.24);
                border-radius: 4px;
                color: #8fffd2;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 11px;
                font-weight: 600;
                padding: 3px 8px;
            }

            QWidget#pidVisualizationViewport {
                background-color: rgba(1, 7, 8, 0.96);
                border: 1px solid rgba(53, 244, 255, 0.42);
                border-radius: 9px;
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
                font-family: Consolas, "Cascadia Mono", monospace;
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
                font-family: Consolas, "Cascadia Mono", monospace;
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
                font-family: Consolas, "Cascadia Mono", monospace;
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
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #35f4ff,
                    stop: 0.65 #8fffd2,
                    stop: 1 #ff5169
                );
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

            QFrame#pidControlTitlePanel {
                background-color: rgba(5, 25, 26, 0.72);
                border: none;
                border-left: 3px solid #8fffd2;
                border-radius: 3px;
            }

            QLabel#pidControlTitle,
            QLabel#pidControlSubtitle {
                background: transparent;
                border: none;
                font-family: "Segoe UI", Arial, sans-serif;
            }

            QLabel#pidControlTitle {
                color: #eaffff;
                font-size: 17px;
                font-weight: 700;
                letter-spacing: 1px;
            }

            QLabel#pidControlSubtitle {
                color: rgba(143, 255, 210, 0.70);
                font-size: 9px;
                font-weight: 600;
                letter-spacing: 1px;
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
            QComboBox#pidTunerChannel,
            QComboBox#pidTunerProfile,
            QComboBox#pidTunerSafetyProfile,
            QSpinBox#pidSpin,
            QDoubleSpinBox#pidSpin {
                background-color: rgba(3, 18, 19, 0.96);
                border: 1px solid rgba(53, 244, 255, 0.48);
                border-radius: 5px;
                color: #eaffff;
                min-height: 28px;
                padding: 3px 8px;
            }

            QLabel#pidTunerSubtitle {
                color: rgba(216, 253, 255, 0.70);
                font-size: 12px;
            }

            QFrame#pidCandidatePanel {
                background-color: rgba(2, 10, 11, 0.90);
                border: 1px solid rgba(53, 244, 255, 0.38);
                border-radius: 7px;
            }

            QFrame#pidBoundsPanel {
                background-color: rgba(2, 10, 11, 0.72);
                border: 1px solid rgba(53, 244, 255, 0.30);
                border-radius: 7px;
            }

            QFrame#pidBoundCard {
                background-color: rgba(4, 19, 20, 0.88);
                border: 1px solid rgba(53, 244, 255, 0.28);
                border-radius: 5px;
            }

            QLabel#pidSectionTitle,
            QLabel#pidBoundTitle,
            QLabel#pidBoundSummary,
            QLabel#pidBoundLabel {
                border: none;
                color: #d8fdff;
                font-family: "Segoe UI", Arial, sans-serif;
            }

            QLabel#pidSectionTitle,
            QLabel#pidBoundTitle {
                font-size: 12px;
                font-weight: 700;
            }

            QLabel#pidBoundTitle {
                color: #8fffd2;
                font-size: 17px;
            }

            QLabel#pidBoundSummary {
                color: #eaffff;
                font-size: 14px;
                font-weight: 600;
                padding: 4px 2px;
            }

            QLabel#pidBoundLabel {
                color: rgba(216, 253, 255, 0.70);
                font-size: 10px;
            }

            QPushButton#pidCompactAction {
                min-height: 22px;
                padding: 2px 9px;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 11px;
                text-align: center;
            }

            QLabel#pidTunerStatus {
                background-color: rgba(5, 23, 24, 0.96);
                border: 1px solid rgba(143, 255, 210, 0.58);
                border-radius: 5px;
                color: #d8fdff;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 12px;
                font-weight: 600;
                min-height: 26px;
                padding: 6px 10px;
            }

            QLabel#pidCandidateValue,
            QLabel#pidStatusValue {
                background-color: rgba(7, 31, 32, 0.96);
                border: 1px solid rgba(53, 244, 255, 0.64);
                border-radius: 5px;
                color: #eaffff;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 13px;
                font-weight: 600;
                padding: 5px 9px;
            }

            QLabel#pidStatusValue {
                background-color: rgba(4, 19, 20, 0.96);
                border-color: rgba(53, 244, 255, 0.38);
                color: rgba(216, 253, 255, 0.90);
                font-size: 12px;
            }

            QFrame#pidTunerViewport {
                background-color: rgba(1, 7, 8, 0.94);
                border: 1px solid rgba(53, 244, 255, 0.42);
                border-radius: 10px;
            }

            QPushButton#pidTunerOpen,
            QPushButton#pidTunerBack,
            QPushButton#pidApplyTunedGains {
                min-height: 28px;
                padding: 4px 12px;
                text-align: center;
            }

            QPushButton#pidApplyTunedGains:enabled {
                background-color: rgba(20, 126, 92, 0.82);
                border-color: rgba(143, 255, 210, 0.82);
                color: #eaffff;
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
