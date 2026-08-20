from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QStackedWidget,
    QWidget,
)
from PySide6.QtCore import QMargins, QRect, QSettings, Qt, QTimer
from PySide6.QtGui import QFontDatabase
from pathlib import Path
import socket
from threading import Event, Thread

from python.app.Automation.AutomationPage import AutomationPage
from python.app.Automation.PidControlPage import PidControlPage
from python.app.UIAnimation import UIAnimationController
from python.app.Controls.AlarmPage import AlarmPage
from python.app.Controls.BeamRangePage import BeamRangePage
from python.app.Controls.FieldCtrlPage import FieldCtrlPage
from python.app.Controls.ManualControlsPage import ManualControlsPage
from python.app.HomePage import HomePage
from python.app.Controls.SnapshotPage import SnapshotPage
from python.app.Configuration.ConfigurationPage import ConfigurationPage
from python.app.Configuration.RecallPage import RecallPage
from python.app.Configuration.ScalingPage import ScalingPage
from python.app.Configuration.SettingsPage import SettingsPage
from python.app.Display.AssignedMonitorWindow import AssignedMonitorWindow, screen_key
from python.app.Monitoring.BeamSourceExtractionPage import (
    BeamSourceExtractionPage,
)
from python.app.Monitoring.BeamTransportMonitoringPage import (
    BeamTransportMonitoringPage,
)
from python.app.Monitoring.DatabaseHistoryPage import DatabaseHistoryPage
from python.app.Monitoring.MagneticFieldMonitoringPage import (
    MagneticFieldMonitoringPage,
)
from python.app.Monitoring.MonitoringPage import MonitoringPage
from python.app.Monitoring.DisplayControllerPage import DisplayControllerPage
from python.app.Monitoring.RfPowerMonitoringPage import RfPowerMonitoringPage
from python.app.Monitoring.VacuumBeamMonitoringPage import (
    VacuumBeamMonitoringPage,
)
from python.app.widgets.MagneticFieldWidgets import FIELD_PLOT_SAMPLE_RATE_HZ
from source.Python.Data.pipeline_manager import DataPipelineManager
from source.Python.Data.pipeline_schema import DEFAULT_DB_PATH
from source.Python.Services.AlarmService import AlarmService
from source.Python.Services.BeamCalibrationService import BeamCalibrationService


PAGE_BUILDERS = {
    "Monitoring": MonitoringPage,
    "Manual Controls": ManualControlsPage,
    "Automation": AutomationPage,
    "Configuration": ConfigurationPage,
}

WINDOW_RESOLUTIONS = {
    "1280 x 820": (1280, 820),
    "1366 x 768": (1366, 768),
    "1440 x 900": (1440, 900),
    "1600 x 900": (1600, 900),
    "1920 x 1080": (1920, 1080),
}

DETAIL_BUILDERS = {
    "Magnetic Field Monitoring": ("Monitoring", MagneticFieldMonitoringPage),
    "Beam Transport Monitoring": ("Monitoring", BeamTransportMonitoringPage),
    "Beam Source & Extraction": ("Monitoring", BeamSourceExtractionPage),
    "Vacuum / Beam Monitoring": ("Monitoring", VacuumBeamMonitoringPage),
    "RF Power Monitoring": ("Monitoring", RfPowerMonitoringPage),
    "Display Controller": ("Monitoring", DisplayControllerPage),
    "Field Ctrl": ("Manual Controls", FieldCtrlPage),
    "Beam Range": ("Manual Controls", BeamRangePage),
    "Alarm": ("Manual Controls", AlarmPage),
    "Snapshot": ("Manual Controls", SnapshotPage),
    "Database History": ("Configuration", DatabaseHistoryPage),
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
        self.simulation_mode = simulation_mode
        self.zmq_endpoint = self._simulation_endpoint(zmq_endpoint, simulation_mode)
        self.enable_data_pipeline = enable_data_pipeline
        self.db_path = Path(db_path)
        self._data_pipeline: DataPipelineManager | None = None
        self._crocker_root = Path(__file__).resolve().parents[2]
        pipeline_db_path = self.db_path if self.db_path.is_absolute() else self._crocker_root / self.db_path
        self.beam_calibration = BeamCalibrationService(self._crocker_root / "config" / "beam_cal.json")
        self.alarm_service = AlarmService(self._crocker_root / "config" / "alarm_config.json", pipeline_db_path)
        self._settings = QSettings("Crocker Nuclear Lab", "Digitalization")
        self._display_mode = self._settings.value(
            "display/mode", "Windowed", type=str
        )
        self._window_resolution = self._settings.value(
            "display/window_resolution", "1280 x 820", type=str
        )
        valid_modes = {"Windowed", "Borderless Window", "Full Screen"}
        if self._display_mode not in valid_modes:
            self._display_mode = "Windowed"
        if self._window_resolution not in WINDOW_RESOLUTIONS:
            self._window_resolution = "1280 x 820"
        self._windowed_geometry = None
        self._display_transition = 0
        self._monitor_windows: dict[str, AssignedMonitorWindow] = {}
        raw_controller_monitors = self._settings.value(
            "display/controller_monitors", [], type=list
        )
        self._controller_monitors = {str(value) for value in raw_controller_monitors}
        self._controller_layout = self._settings.value(
            "display/controller_layout", "Auto", type=str
        )
        if self._controller_layout not in {"Auto", "Compact", "Full"}:
            self._controller_layout = "Auto"

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
                field_backend_mode = self.backend_mode
                if title == "Field Ctrl" and self.simulation_mode in {"cyclotron", "smoke2"}:
                    field_backend_mode = "zmq"
                elif title == "PID Control" and self.simulation_mode == "cyclotron":
                    field_backend_mode = "zmq"
                elif title == "PID Control" and self.backend_mode == "zmq":
                    field_backend_mode = "offline"
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
                    set_window_resolution=self.set_window_resolution,
                    current_display_mode=self._display_mode,
                    current_window_resolution=self._window_resolution,
                    monitor_entries=self._monitor_entries(),
                    page_names=self._assignable_page_names(),
                    apply_monitor_assignments=self.apply_monitor_assignments,
                    controller_layout=self._controller_layout,
                    apply_controller_settings=self.apply_controller_settings,
                )
                self.stack.addWidget(detail_page)
                self.pages[title] = detail_page
                self.detail_parent[title] = parent_category
                continue

            if title == "Database History":
                detail_page = page_builder(
                    lambda checked=False, category=parent_category:
                        self.show_category(category),
                    db_path=self.db_path,
                    back_label="Back to Settings",
                )
                self.stack.addWidget(detail_page)
                self.pages[title] = detail_page
                self.detail_parent[title] = parent_category
                continue

            if title == "Display Controller":
                detail_page = page_builder(
                    lambda checked=False, category=parent_category:
                        self.show_category(category),
                    monitoring_pages=self._monitoring_page_names(),
                    monitor_entries=self._monitor_entries,
                    show_on_monitor=self.show_monitoring_page,
                    controller_layout=lambda: self._controller_layout,
                )
                self.stack.addWidget(detail_page)
                self.pages[title] = detail_page
                self.detail_parent[title] = parent_category
                continue

            if title == "Beam Range":
                detail_page = page_builder(
                    lambda checked=False, category=parent_category:
                        self.show_category(category),
                    get_beam_state=self.current_beam_state,
                    get_beam_ranges=self.beam_calibration.ranges_dict,
                    set_manual_range=self.set_manual_beam_range,
                    reload_config=self.reload_beam_calibration,
                )
                self.stack.addWidget(detail_page)
                self.pages[title] = detail_page
                self.detail_parent[title] = parent_category
                continue

            if title == "Alarm":
                detail_page = page_builder(
                    lambda checked=False, category=parent_category:
                        self.show_category(category),
                    get_alarms=self.current_alarms,
                    acknowledge=self.acknowledge_alarms,
                    reload_config=self.reload_alarm_config,
                    get_config=self.alarm_service.config_dict,
                )
                self.stack.addWidget(detail_page)
                self.pages[title] = detail_page
                self.detail_parent[title] = parent_category
                continue

            if title == "Scaling":
                detail_page = page_builder(
                    lambda checked=False, category=parent_category:
                        self.show_category(category),
                    apply_live_scaling=self.apply_live_scaling,
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
        self.motion = UIAnimationController(self.stack, self)
        self.motion.attach_to(self)
        if self.simulation_mode in {"cyclotron", "smoke2"}:
            self._start_zmq_simulation_plant(self.simulation_mode)
        if self.enable_data_pipeline:
            self._start_data_pipeline()
        app = QApplication.instance()
        if app is not None:
            app.screenAdded.connect(lambda screen: self._screens_changed())
            app.screenRemoved.connect(lambda screen: self._screens_changed())
        QTimer.singleShot(
            0,
            lambda: self.set_display_mode(self._display_mode, save=False, force=True),
        )

    def _assignable_page_names(self) -> list[str]:
        detail_names = (
            name for name in DETAIL_BUILDERS if name != "Settings"
        )
        return ["Home", *PAGE_BUILDERS.keys(), *detail_names]

    def _monitoring_page_names(self) -> list[str]:
        return [
            name for name, (parent, _builder) in DETAIL_BUILDERS.items()
            if parent == "Monitoring" and name != "Display Controller"
        ]

    def _monitor_entries(self) -> list[dict[str, object]]:
        main_screen = self.screen()
        main_screen_id = screen_key(main_screen) if main_screen is not None else ""
        current_page = self._current_page_name()
        entries: list[dict[str, object]] = []
        for screen in QApplication.screens()[:4]:
            screen_id = screen_key(screen)
            name = screen.name()
            geometry = screen.geometry()
            occupied = screen_id == main_screen_id
            assigned_window = self._monitor_windows.get(screen_id)
            assignment = (
                assigned_window.page_name
                if assigned_window is not None
                else ""
            )
            entries.append({
                "id": screen_id,
                "name": name,
                "label": f"{name} ({geometry.x()}, {geometry.y()}) {geometry.width()}x{geometry.height()}",
                "occupied": occupied,
                "assignment": current_page if occupied else assignment,
                "controller_enabled": screen_id in self._controller_monitors,
            })
        return entries

    def _current_page_name(self) -> str:
        current = self.stack.currentWidget()
        for name, page in self.pages.items():
            if page is current:
                return name
        return ""

    def _refresh_settings_monitors(self) -> None:
        settings_page = self.pages.get("Settings")
        if isinstance(settings_page, SettingsPage):
            settings_page.set_monitor_entries(self._monitor_entries())

    def _screens_changed(self) -> None:
        available = {screen_key(screen) for screen in QApplication.screens()}
        for screen_id, window in list(self._monitor_windows.items()):
            if screen_id not in available:
                window.close()
                del self._monitor_windows[screen_id]
        settings_page = self.pages.get("Settings")
        if isinstance(settings_page, SettingsPage):
            settings_page.set_monitor_entries(self._monitor_entries())

    def apply_monitor_assignments(self, assignments: dict[str, str]) -> None:
        screens = {
            screen_key(screen): screen for screen in QApplication.screens()[:4]
        }
        main_screen = self.screen()
        main_screen_id = screen_key(main_screen) if main_screen is not None else ""
        for screen_id, screen in screens.items():
            page_name = assignments.get(screen_id, "")

            if screen_id == main_screen_id:
                window = self._monitor_windows.pop(screen_id, None)
                if window is not None:
                    window.close()
                if page_name in self.pages:
                    self.stack.setCurrentWidget(self.pages[page_name])
                continue

            if not page_name:
                window = self._monitor_windows.pop(screen_id, None)
                if window is not None:
                    window.close()
                continue

            window = self._monitor_windows.get(screen_id)
            if window is None:
                window = AssignedMonitorWindow(self, screen_id, screen.name())
                self._monitor_windows[screen_id] = window
            window.winId()
            handle = window.windowHandle()
            if handle is not None:
                handle.setScreen(screen)
            window.apply_display_mode(
                self._display_mode,
                self._window_resolution_size(),
            )
            window.set_page(page_name)

    def apply_controller_settings(self, screen_ids: set[str], layout: str) -> None:
        main_screen = self.screen()
        main_screen_id = screen_key(main_screen) if main_screen is not None else ""
        self._controller_monitors = set(screen_ids) - {main_screen_id}
        self._controller_layout = layout if layout in {"Auto", "Compact", "Full"} else "Auto"
        self._settings.setValue("display/controller_monitors", list(self._controller_monitors))
        self._settings.setValue("display/controller_layout", self._controller_layout)
        self._settings.sync()

    def show_monitoring_page(self, screen_id: str, page_name: str) -> bool:
        if screen_id not in self._controller_monitors:
            return False
        if page_name not in self._monitoring_page_names():
            return False
        screens = {screen_key(screen): screen for screen in QApplication.screens()[:4]}
        screen = screens.get(screen_id)
        if screen is None or screen is self.screen():
            return False
        window = self._monitor_windows.get(screen_id)
        if window is None:
            window = AssignedMonitorWindow(self, screen_id, screen.name())
            self._monitor_windows[screen_id] = window
        window.winId()
        handle = window.windowHandle()
        if handle is not None:
            handle.setScreen(screen)
        window.apply_display_mode(self._display_mode, self._window_resolution_size())
        window.set_page(page_name)
        return True

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
                if page_name == "PID Control" and self.backend_mode == "zmq" and self.simulation_mode is None:
                    field_backend_mode = "offline"
                return builder(
                    go_back,
                    backend_mode=field_backend_mode,
                    zmq_endpoint=self.zmq_endpoint,
                )
            if page_name == "Database History":
                return builder(
                    go_back,
                    db_path=self.db_path,
                    back_label="Back to Settings",
                )
            if page_name == "Beam Range":
                return builder(
                    go_back,
                    get_beam_state=self.current_beam_state,
                    get_beam_ranges=self.beam_calibration.ranges_dict,
                    set_manual_range=self.set_manual_beam_range,
                    reload_config=self.reload_beam_calibration,
                )
            if page_name == "Alarm":
                return builder(
                    go_back,
                    get_alarms=self.current_alarms,
                    acknowledge=self.acknowledge_alarms,
                    reload_config=self.reload_alarm_config,
                    get_config=self.alarm_service.config_dict,
                )
            if page_name == "Scaling":
                return builder(
                    go_back,
                    apply_live_scaling=self.apply_live_scaling,
                )
            if page_name == "Settings":
                return builder(
                    go_back,
                    set_display_mode=self.set_display_mode,
                    set_window_resolution=self.set_window_resolution,
                    current_display_mode=self._display_mode,
                    current_window_resolution=self._window_resolution,
                    monitor_entries=self._monitor_entries(),
                    page_names=self._assignable_page_names(),
                    apply_monitor_assignments=self.apply_monitor_assignments,
                    controller_layout=self._controller_layout,
                    apply_controller_settings=self.apply_controller_settings,
                )
            return builder(go_back)
        fallback = QWidget()
        return fallback

    def apply_live_scaling(self, scaling: dict[str, list[float] | list[bool]]) -> bool:
        field_page = self.pages.get("Field Ctrl")
        if isinstance(field_page, FieldCtrlPage):
            return field_page.apply_scaling(scaling)
        return False

    def set_display_mode(
        self,
        mode: str,
        save: bool = True,
        force: bool = False,
    ) -> None:
        if mode not in {"Windowed", "Borderless Window", "Full Screen"}:
            return
        if not force and mode == self._display_mode:
            if save:
                self._settings.setValue("display/mode", mode)
                self._settings.sync()
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

        flags = self.windowFlags()
        if flags & Qt.WindowType.FramelessWindowHint:
            flags &= ~Qt.WindowType.FramelessWindowHint
            self.setWindowFlags(flags)

        def finish_transition() -> None:
            if transition != self._display_transition:
                return
            if mode == "Windowed":
                if self.isFullScreen() or self.isMaximized():
                    self.setWindowState(Qt.WindowState.WindowNoState)
                    self.showNormal()
                self._apply_windowed_resolution()
            else:
                if not self.isFullScreen():
                    self.showFullScreen()
            for window in self._monitor_windows.values():
                window.apply_display_mode(mode, self._window_resolution_size())

        QTimer.singleShot(0, finish_transition)

    def set_window_resolution(self, resolution: str, save: bool = True) -> None:
        if resolution not in WINDOW_RESOLUTIONS:
            return
        if resolution == self._window_resolution:
            if save:
                self._settings.setValue("display/window_resolution", resolution)
                self._settings.sync()
            return
        self._window_resolution = resolution
        self._windowed_geometry = None
        if save:
            self._settings.setValue("display/window_resolution", resolution)
            self._settings.sync()
        if self._display_mode == "Windowed":
            self._apply_windowed_resolution()
        for window in self._monitor_windows.values():
            window.apply_display_mode(self._display_mode, self._window_resolution_size())

    def _window_resolution_size(self) -> tuple[int, int]:
        return WINDOW_RESOLUTIONS.get(self._window_resolution, WINDOW_RESOLUTIONS["1280 x 820"])

    def _apply_windowed_resolution(self) -> None:
        width, height = self._window_resolution_size()
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = self._safe_screen_rect(screen, available=True)
            margins = self._frame_margins()
            width = min(width, max(1, available.width() - margins.left() - margins.right()))
            height = min(height, max(1, available.height() - margins.top() - margins.bottom()))
            self.resize(width, height)
            self.move(
                available.x() + int((available.width() - width) / 2),
                available.y() + int((available.height() - height) / 2),
            )
        else:
            self.resize(width, height)

    def _frame_margins(self) -> QMargins:
        handle = self.windowHandle()
        if handle is None:
            return QMargins()
        return handle.frameMargins()

    def _safe_screen_rect(self, screen, available: bool) -> QRect:
        base = screen.availableGeometry() if available else screen.geometry()
        physical = screen.geometry()
        width = min(base.width(), physical.width())
        height = min(base.height(), physical.height())
        if width > 1 and width % 2:
            width -= 1
        if height > 1 and height % 2:
            height -= 1
        return QRect(base.x(), base.y(), max(1, width), max(1, height))

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

    def _simulation_endpoint(
        self,
        zmq_endpoint: str,
        simulation_mode: str | None,
    ) -> str:
        if simulation_mode not in {"cyclotron", "smoke2"}:
            return zmq_endpoint
        if zmq_endpoint not in {"tcp://0.0.0.0:5555", "tcp://127.0.0.1:5555"}:
            return zmq_endpoint
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            _host, port = probe.getsockname()
        return f"tcp://127.0.0.1:{port}"

    def _start_zmq_simulation_plant(self, simulation_mode: str) -> None:
        from source.Python.Simulator.ZMQSimulator import (
            CyclotronPlant,
            Smoke2Plant,
            ZMQSimulator,
        )

        self._simulation_plant_stop = Event()
        endpoint = self.zmq_endpoint.replace("0.0.0.0", "127.0.0.1")
        plant = CyclotronPlant() if simulation_mode == "cyclotron" else Smoke2Plant()

        def run_plant() -> None:
            simulator = ZMQSimulator(endpoint)
            simulator.stream(
                rate_hz=float(FIELD_PLOT_SAMPLE_RATE_HZ),
                stop_event=self._simulation_plant_stop,
                plant=plant,
            )

        self._simulation_plant_thread = Thread(
            target=run_plant,
            name=f"{simulation_mode}-zmq-plant",
            daemon=True,
        )
        self._simulation_plant_thread.start()

    def _start_data_pipeline(self) -> None:
        db_path = self.db_path
        if not db_path.is_absolute():
            db_path = self._crocker_root / db_path
        self._data_pipeline = DataPipelineManager(
            crocker_root=self._crocker_root,
            db_path=db_path,
            source=self.simulation_mode or self.backend_mode,
            rate_hz=float(FIELD_PLOT_SAMPLE_RATE_HZ),
            snapshot_source=self._transport_snapshot,
        )
        self._data_pipeline.start()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        for window in self._monitor_windows.values():
            window.close()
        self._monitor_windows.clear()
        if self._data_pipeline is not None:
            self._data_pipeline.stop()
        stop = getattr(self, "_simulation_plant_stop", None)
        if stop is not None:
            stop.set()
        super().closeEvent(event)

    def _transport_snapshot(self) -> dict | None:
        field_page = self.pages.get("Field Ctrl")
        if isinstance(field_page, FieldCtrlPage):
            snapshot = field_page.transport_snapshot()
            return self._update_addon_services(snapshot)
        return None

    def _update_addon_services(self, snapshot: dict | None) -> dict | None:
        if snapshot is None:
            return None
        beam_state = self.beam_calibration.update(snapshot).to_dict()
        alarms = [alarm.to_dict() for alarm in self.alarm_service.update(snapshot, beam_state)]
        snapshot["beam"] = beam_state
        snapshot["active_alarms"] = alarms
        return snapshot

    def current_beam_state(self) -> dict:
        return self.beam_calibration.update(self._latest_field_snapshot()).to_dict()

    def set_manual_beam_range(self, index: int) -> dict:
        return self.beam_calibration.set_manual_range(index).to_dict()

    def reload_beam_calibration(self) -> dict:
        self.beam_calibration.reload()
        return self.current_beam_state()

    def current_alarms(self) -> list[dict]:
        snapshot = self._latest_field_snapshot()
        beam_state = self.beam_calibration.update(snapshot).to_dict() if snapshot is not None else self.beam_calibration.state_dict()
        return [alarm.to_dict() for alarm in self.alarm_service.update(snapshot, beam_state)]

    def acknowledge_alarms(self) -> None:
        self.alarm_service.acknowledge()

    def reload_alarm_config(self) -> list[dict]:
        self.alarm_service.reload()
        return self.current_alarms()

    def _latest_field_snapshot(self) -> dict | None:
        field_page = self.pages.get("Field Ctrl")
        if isinstance(field_page, FieldCtrlPage):
            return field_page.transport_snapshot()
        return None

    def show_home(self) -> None:
        self.stack.setCurrentWidget(self.pages["Home"])
        self._refresh_settings_monitors()

    def show_category(self, category: str) -> None:
        self.stack.setCurrentWidget(self.pages[category])
        self._refresh_settings_monitors()

    def open_placeholder(self, title: str, purpose: str) -> None:
        self.stack.setCurrentWidget(self.pages[title])
        self._refresh_settings_monitors()

    def apply_styles(self) -> None:
        app_font = self._load_app_font()
        app = QApplication.instance()
        if app is not None:
            app.setProperty("appFontFamily", app_font)
        stylesheet = """
            QStackedWidget#root,
            QWidget#page,
            QDialog {
                background: transparent;
                color: #e5e7eb;
                font-family: "__APP_FONT__", Segoe UI, Arial, sans-serif;
                font-size: 14px;
            }

            QLabel#header {
                background: transparent;
                border: none;
                color: #e5e7eb;
                font-family: "__APP_FONT__", Segoe UI, Arial, sans-serif;
                font-size: 20px;
                font-weight: 700;
                padding: 0;
            }

            QLabel#subheader {
                color: #94a3b8;
                font-size: 15px;
            }

            QFrame#workspace {
                background-color: rgba(17, 24, 39, 0.86);
                border: 1px solid rgba(51, 65, 85, 0.92);
                border-radius: 8px;
            }

            QFrame#fieldControlWorkspace {
                background-color: rgba(17, 24, 39, 0.86);
                border: 1px solid rgba(51, 65, 85, 0.92);
                border-radius: 8px;
            }

            QPushButton {
                background-color: rgba(30, 41, 59, 0.82);
                border: 1px solid rgba(71, 85, 105, 0.88);
                border-radius: 7px;
                color: #e5e7eb;
                font-weight: 600;
                min-height: 34px;
                padding: 6px 12px;
                text-align: left;
            }

            QPushButton#backButton {
                max-width: 238px;
                min-height: 40px;
                text-align: center;
            }

            QPushButton#navBackButton,
            QPushButton#transitionCardButton,
            QPushButton#monitorSelectionButton {
                background: transparent;
                border: none;
                color: transparent;
                padding: 0;
                text-align: left;
            }

            QPushButton#pidBackButton {
                background-color: rgba(30, 41, 59, 0.82);
                border: 1px solid rgba(71, 85, 105, 0.88);
                border-radius: 7px;
                color: #e5e7eb;
                margin-left: 18px;
                margin-bottom: 8px;
                max-width: 150px;
                min-height: 34px;
                padding: 6px 12px;
                text-align: center;
            }

            QPushButton#pidBackButton:hover {
                background-color: rgba(51, 65, 85, 0.92);
                border-color: rgba(96, 165, 250, 0.72);
                color: #ffffff;
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
                background-color: rgba(51, 65, 85, 0.92);
                border-color: rgba(96, 165, 250, 0.72);
                color: #ffffff;
            }

            QLabel#settingsHeading {
                color: #bfdbfe;
                font-size: 18px;
                font-weight: 700;
                padding-top: 8px;
            }

            QLabel#settingsDescription {
                color: #94a3b8;
                font-size: 13px;
                padding-bottom: 6px;
            }

            QScrollArea#settingsScrollArea,
            QWidget#settingsScrollContent {
                background: transparent;
                border: none;
            }

            QFrame#displayModePanel {
                background-color: rgba(15, 23, 42, 0.88);
                border: 1px solid rgba(51, 65, 85, 0.90);
                border-radius: 7px;
            }

            QFrame#monitorMapPanel {
                background-color: rgba(15, 23, 42, 0.94);
                border: 1px solid rgba(51, 65, 85, 0.90);
                border-radius: 8px;
            }

            QLabel#monitorMapHeading {
                color: #e5e7eb;
                font-size: 14px;
                font-weight: 700;
                padding: 2px 4px 8px 4px;
            }

            QFrame#monitorCanvas {
                background-color: rgba(17, 24, 39, 0.84);
                border-top: 1px solid rgba(51, 65, 85, 0.72);
                border-radius: 5px;
            }

            QPushButton#monitorTile {
                background-color: rgba(30, 41, 59, 0.74);
                border: 1px solid rgba(71, 85, 105, 0.84);
                border-radius: 8px;
                color: #cbd5e1;
                font-size: 15px;
                font-weight: 700;
                text-align: center;
            }

            QPushButton#monitorTile:hover {
                background-color: rgba(51, 65, 85, 0.92);
                border-color: rgba(96, 165, 250, 0.72);
                color: #ffffff;
            }

            QPushButton#monitorTile:checked {
                background-color: rgba(37, 99, 235, 0.36);
                border: 2px solid rgba(96, 165, 250, 0.78);
                color: #eff6ff;
            }

            QLabel#monitorAssignmentLabel {
                color: #bfdbfe;
                font-size: 12px;
                font-weight: 700;
                min-width: 180px;
            }

            QFrame#monitorPagePicker {
                background-color: rgba(15, 23, 42, 0.90);
                border: 1px solid rgba(51, 65, 85, 0.86);
                border-radius: 8px;
            }

            QFrame#monitorPageGrid {
                background-color: transparent;
                border: none;
            }

            QLineEdit#monitorPageSearch {
                background-color: rgba(15, 23, 42, 0.96);
                border: 1px solid rgba(71, 85, 105, 0.88);
                border-radius: 5px;
                color: #e5e7eb;
                min-height: 32px;
                padding: 3px 10px;
            }

            QLineEdit#monitorPageSearch:focus {
                border-color: rgba(96, 165, 250, 0.88);
            }

            QPushButton#monitorPageTile {
                background-color: rgba(30, 41, 59, 0.76);
                border: 1px solid rgba(71, 85, 105, 0.84);
                border-radius: 6px;
                color: #cbd5e1;
                font-size: 12px;
                font-weight: 700;
                min-height: 34px;
                padding: 4px 8px;
                text-align: center;
            }

            QPushButton#monitorPageTile:hover {
                background-color: rgba(51, 65, 85, 0.92);
                border-color: rgba(96, 165, 250, 0.72);
                color: #ffffff;
            }

            QPushButton#monitorPageTile:checked {
                background-color: rgba(37, 99, 235, 0.70);
                border: 2px solid rgba(147, 197, 253, 0.86);
                color: #eff6ff;
            }

            QComboBox#monitorPageSelect {
                background-color: rgba(15, 23, 42, 0.94);
                border: 1px solid rgba(71, 85, 105, 0.88);
                border-radius: 5px;
                color: #e5e7eb;
                min-height: 32px;
                padding: 3px 8px;
            }

            QComboBox#monitorPageSelect:disabled {
                border-color: rgba(71, 85, 105, 0.70);
                color: #94a3b8;
            }

            QPushButton#displayModeButton {
                min-height: 58px;
                text-align: center;
                font-size: 14px;
            }

            QPushButton#displayModeButton:checked {
                background-color: rgba(37, 99, 235, 0.78);
                border: 2px solid rgba(96, 165, 250, 0.82);
                color: #eff6ff;
            }

            QPushButton#applySettingsButton {
                min-height: 48px;
                background-color: rgba(37, 99, 235, 0.86);
                border: 2px solid rgba(96, 165, 250, 0.82);
                color: #eff6ff;
                font-size: 15px;
                font-weight: 700;
                text-align: center;
            }

            QPushButton#applySettingsButton:hover {
                background-color: rgba(29, 78, 216, 0.94);
                border-color: #93c5fd;
            }

            QPushButton#homeExitButton {
                background-color: rgba(72, 12, 22, 0.88);
                border: 1px solid rgba(255, 122, 145, 0.46);
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
                background-color: rgba(51, 65, 85, 0.92);
                border-color: rgba(96, 165, 250, 0.72);
                color: #ffffff;
            }

            QPushButton[motionHover="true"] {
                background-color: rgba(51, 65, 85, 0.92);
                border: 1px solid rgba(96, 165, 250, 0.72);
                color: #ffffff;
            }

            QPushButton:pressed {
                background-color: rgba(37, 99, 235, 0.40);
                border-color: rgba(96, 165, 250, 0.82);
                color: #ffffff;
            }

            QPushButton[motionPressed="true"] {
                background-color: rgba(37, 99, 235, 0.46);
                border: 1px solid rgba(96, 165, 250, 0.88);
                color: #ffffff;
            }

            QSplitter::handle {
                background-color: rgba(51, 65, 85, 0.70);
            }

            QScrollBar:vertical,
            QScrollBar:horizontal {
                background-color: rgba(15, 23, 42, 0.96);
                border: 1px solid rgba(51, 65, 85, 0.86);
                margin: 0;
            }

            QScrollBar::handle:vertical,
            QScrollBar::handle:horizontal {
                background-color: rgba(71, 85, 105, 0.82);
                border-radius: 4px;
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
                color: #cbd5e1;
                font-size: 16px;
            }

            QLabel#dialogHeader {
                color: #e5e7eb;
                font-family: "__APP_FONT__", Segoe UI, Arial, sans-serif;
                font-size: 24px;
                font-weight: 700;
            }

            QLabel#dialogBody,
            QLabel#dialogPlaceholder {
                color: #cbd5e1;
                font-size: 15px;
            }

            QLabel#dialogPlaceholder {
                background-color: rgba(15, 23, 42, 0.92);
                border: 1px solid rgba(51, 65, 85, 0.86);
                border-radius: 8px;
            }

            QLabel#metricCard {
                background-color: rgba(30, 41, 59, 0.70);
                border: 1px solid rgba(51, 65, 85, 0.86);
                border-radius: 8px;
                color: #e5e7eb;
                font-size: 15px;
                font-weight: 600;
                min-height: 74px;
                padding: 10px;
            }

            QLabel#chartPlaceholder {
                background-color: rgba(15, 23, 42, 0.84);
                border: 1px solid rgba(51, 65, 85, 0.86);
                border-radius: 8px;
                color: #cbd5e1;
                font-size: 16px;
                min-height: 170px;
            }

            QLineEdit,
            QDoubleSpinBox,
            QSpinBox,
            QDateEdit,
            QComboBox,
            QListWidget,
            QTableWidget {
                background-color: rgba(15, 23, 42, 0.90);
                border: 1px solid rgba(71, 85, 105, 0.88);
                border-radius: 7px;
                color: #e5e7eb;
                min-height: 28px;
                selection-background-color: rgba(37, 99, 235, 0.46);
                selection-color: #ffffff;
            }

            QLineEdit:focus,
            QDoubleSpinBox:focus,
            QSpinBox:focus,
            QDateEdit:focus,
            QComboBox:focus {
                background-color: rgba(17, 24, 39, 0.96);
                border: 1px solid rgba(96, 165, 250, 0.72);
                color: #ffffff;
            }

            QComboBox QAbstractItemView {
                background-color: #0f172a;
                border: 1px solid rgba(96, 165, 250, 0.72);
                color: #e5e7eb;
                outline: 0;
                padding: 3px;
                selection-background-color: rgba(37, 99, 235, 0.62);
                selection-color: #ffffff;
            }

            QComboBox QAbstractItemView::item {
                min-height: 24px;
                padding: 4px 8px;
            }

            QListWidget {
                alternate-background-color: rgba(30, 41, 59, 0.42);
            }

            QListWidget::item {
                border-radius: 5px;
                min-height: 25px;
                padding: 4px 8px;
            }

            QListWidget::item:selected {
                background-color: rgba(37, 99, 235, 0.46);
                color: #ffffff;
            }

            QFrame#historyToolbar {
                background-color: rgba(15, 23, 42, 0.82);
                border: 1px solid rgba(51, 65, 85, 0.86);
                border-radius: 8px;
            }

            QFrame#historySegment,
            QFrame#historyToolbarGroup,
            QFrame#historyStatusCard {
                background-color: rgba(17, 24, 39, 0.78);
                border: 1px solid rgba(51, 65, 85, 0.78);
                border-radius: 7px;
            }

            QFrame#historyToolbarActions {
                background-color: transparent;
                border: none;
            }

            QLabel#historyToolbarLabel {
                background-color: transparent;
                border: none;
                color: #94a3b8;
                font-size: 12px;
                font-weight: 700;
                min-height: 20px;
                padding: 0 2px;
            }

            QLabel#historyPathPill {
                background-color: transparent;
                border: none;
                color: #dbeafe;
                font-size: 13px;
                min-height: 26px;
                min-width: 140px;
                padding: 0;
            }

            QLineEdit#historyExportName {
                min-width: 160px;
            }

            QLabel#historyStatusCaption {
                color: #64748b;
                font-size: 10px;
                font-weight: 800;
                padding: 0;
            }

            QLabel#historyStatusValue {
                color: #dbeafe;
                font-size: 13px;
                font-weight: 600;
                min-width: 150px;
                padding: 0;
            }

            QPushButton#historyTabButton {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 5px;
                color: #94a3b8;
                font-weight: 600;
                min-height: 28px;
                min-width: 86px;
                padding: 5px 14px;
                text-align: center;
            }

            QPushButton#historyTabButton:checked {
                background-color: rgba(30, 41, 59, 0.92);
                border-color: rgba(96, 165, 250, 0.70);
                color: #e5e7eb;
            }

            QPushButton#historyTabButton:hover {
                color: #ffffff;
            }

            QFrame#historySummaryHeader {
                background-color: rgba(15, 23, 42, 0.84);
                border: 1px solid rgba(51, 65, 85, 0.84);
                border-radius: 8px;
            }

            QLabel#historySummaryTitle {
                color: #e5e7eb;
                font-size: 16px;
                font-weight: 700;
            }

            QLabel#historySummaryMeta {
                color: #94a3b8;
                font-size: 12px;
                font-weight: 600;
            }

            QTableWidget#historySummaryTable {
                background-color: rgba(15, 23, 42, 0.82);
                border: 1px solid rgba(51, 65, 85, 0.86);
                border-radius: 8px;
                padding: 4px;
            }

            QTableWidget {
                gridline-color: rgba(51, 65, 85, 0.72);
                alternate-background-color: rgba(30, 41, 59, 0.54);
            }

            QHeaderView::section {
                background-color: rgba(17, 24, 39, 0.94);
                border: 1px solid rgba(51, 65, 85, 0.86);
                color: #e5e7eb;
                font-weight: 600;
                padding: 5px;
            }

            QCheckBox#toggleRow {
                color: #e5e7eb;
                font-size: 16px;
                min-height: 36px;
            }

            QFrame#pidPanel QCheckBox#toggleRow {
                background-color: rgba(17, 24, 39, 0.72);
                border: 1px solid rgba(51, 65, 85, 0.86);
                border-radius: 6px;
                color: #cbd5e1;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 13px;
                min-height: 28px;
                padding: 3px 9px;
            }

            QFrame#pidPanel QCheckBox#toggleRow:hover {
                border-color: rgba(96, 165, 250, 0.72);
                color: #ffffff;
            }

            QFrame#pidPanel QCheckBox#toggleRow:checked {
                background-color: rgba(37, 99, 235, 0.50);
                border-color: rgba(96, 165, 250, 0.82);
                color: #ffffff;
            }

            QFrame#pidPanel QCheckBox#toggleRow::indicator {
                background-color: rgba(15, 23, 42, 0.96);
                border: 1px solid rgba(100, 116, 139, 0.88);
                border-radius: 7px;
                height: 14px;
                image: none;
                width: 14px;
            }

            QFrame#pidPanel QCheckBox#toggleRow::indicator:checked {
                background-color: #3b82f6;
                border-color: #bfdbfe;
                image: none;
            }

            QProgressBar {
                background-color: rgba(15, 23, 42, 0.90);
                border: 1px solid rgba(71, 85, 105, 0.88);
                border-radius: 6px;
                color: #e5e7eb;
                min-height: 24px;
                text-align: center;
            }

            QProgressBar::chunk {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #1d4ed8,
                    stop: 0.55 #2563eb,
                    stop: 1 #60a5fa
                );
                border-radius: 5px;
            }

            QWidget#fieldController {
                background: transparent;
            }

            QLabel#scalingSummary {
                background-color: rgba(17, 24, 39, 0.78);
                border: 1px solid rgba(71, 85, 105, 0.82);
                border-radius: 6px;
                color: #dbeafe;
                font-size: 14px;
                font-weight: 700;
                min-height: 48px;
                padding: 7px 12px;
            }

            QLabel#scalingSummary[warning="true"] {
                background-color: rgba(120, 53, 15, 0.42);
                border-color: rgba(251, 191, 36, 0.72);
                color: #fde68a;
            }

            QFrame#controllerTargetPanel {
                background-color: rgba(15, 23, 42, 0.94);
                border: 1px solid rgba(51, 65, 85, 0.90);
                border-radius: 8px;
            }

            QLabel#controllerSectionHeading {
                color: #bfdbfe;
                font-size: 13px;
                font-weight: 700;
                letter-spacing: 1px;
            }

            QLabel#controllerStatus {
                color: #e5e7eb;
                font-size: 13px;
                font-weight: 600;
                padding: 2px 0;
            }

            QFrame#controllerStatusBlock {
                background-color: rgba(17, 24, 39, 0.86);
                border: 1px solid rgba(51, 65, 85, 0.88);
                border-radius: 6px;
            }

            QLabel#controllerStatusLabel {
                color: #7f9bbd;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1px;
            }

            QLabel#controllerStatusValue {
                color: #e5e7eb;
                font-size: 13px;
                font-weight: 700;
                min-height: 20px;
            }

            QLabel#controllerStatusValue[warning="true"] {
                color: #fbbf24;
            }

            QLabel#controllerEmptyState {
                background-color: rgba(30, 41, 59, 0.54);
                border: 1px dashed rgba(71, 85, 105, 0.90);
                border-radius: 5px;
                color: #94a3b8;
                font-size: 12px;
                min-height: 30px;
                padding: 5px 10px;
            }

            QPushButton#controllerPageTile {
                background-color: rgba(30, 41, 59, 0.72);
                border: 1px solid rgba(71, 85, 105, 0.84);
                border-radius: 8px;
                color: #cbd5e1;
                font-size: 12px;
                font-weight: 600;
                padding: 18px 20px;
                text-align: left;
            }

            QPushButton#controllerPageTile:hover {
                background-color: rgba(51, 65, 85, 0.90);
                border-color: rgba(96, 165, 250, 0.72);
                color: #ffffff;
            }

            QPushButton#controllerPageTile:checked {
                background-color: rgba(37, 99, 235, 0.38);
                border: 2px solid rgba(96, 165, 250, 0.86);
                color: #eff6ff;
            }

            QFrame#fieldControlTabs {
                background-color: transparent;
                border: none;
                border-bottom: 1px solid rgba(71, 85, 105, 0.78);
            }

            QPushButton#fieldControlTab {
                background-color: rgba(15, 23, 42, 0.64);
                border: 1px solid rgba(71, 85, 105, 0.70);
                border-bottom-color: rgba(71, 85, 105, 0.78);
                border-top-left-radius: 7px;
                border-top-right-radius: 7px;
                border-bottom-left-radius: 0;
                border-bottom-right-radius: 0;
                color: #cbd5e1;
                font-size: 12px;
                font-weight: 700;
                margin-bottom: 0;
                margin-top: 6px;
                min-height: 28px;
                min-width: 126px;
                padding: 3px 10px;
                text-align: center;
            }

            QPushButton#fieldControlTab:hover {
                background-color: rgba(30, 41, 59, 0.92);
                border-color: rgba(96, 165, 250, 0.70);
                color: #ffffff;
            }

            QPushButton#fieldControlTab:checked {
                background-color: rgba(17, 24, 39, 0.96);
                border-color: rgba(147, 197, 253, 0.86);
                border-bottom-color: rgba(17, 24, 39, 0.96);
                color: #eff6ff;
                margin-top: 2px;
                min-height: 32px;
            }

            QWidget#fieldControlStack,
            QWidget#fieldMonitorControl {
                background: transparent;
            }

            QLabel#fieldMonitorTitle {
                color: #e5e7eb;
                font-family: "__APP_FONT__", Segoe UI, Arial, sans-serif;
                font-size: 18px;
                font-weight: 700;
                padding: 4px 2px 2px 2px;
            }

            QLabel#fieldInstruction {
                background-color: rgba(17, 24, 39, 0.82);
                border: 1px solid rgba(51, 65, 85, 0.86);
                border-radius: 8px;
                color: #e5e7eb;
                font-size: 14px;
                font-weight: 600;
                min-height: 44px;
                padding: 8px 12px;
            }

            QLabel#fieldHeader {
                color: #e5e7eb;
                font-family: "__APP_FONT__", Segoe UI, Arial, sans-serif;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 0;
            }

            QPushButton#fieldBulk {
                background-color: rgba(30, 41, 59, 0.76);
                border: 1px solid rgba(71, 85, 105, 0.84);
                color: #e5e7eb;
                min-height: 26px;
                padding: 3px 8px;
                text-align: center;
            }

            QPushButton#fieldLockButton {
                background-color: rgba(96, 20, 31, 0.84);
                border: 1px solid rgba(255, 122, 145, 0.46);
                border-radius: 6px;
                color: #ffe4e4;
                font-size: 12px;
                font-weight: 700;
                min-height: 30px;
                min-width: 124px;
                padding: 4px 10px;
                text-align: center;
            }

            QPushButton#fieldLockButton:checked {
                background-color: rgba(6, 78, 59, 0.72);
                border-color: rgba(45, 212, 191, 0.52);
                color: #a7f3d0;
            }

            QFrame#fieldBackendStatus {
                background-color: rgba(17, 24, 39, 0.90);
                border: 1px solid rgba(51, 65, 85, 0.86);
                border-radius: 10px;
            }

            QLabel#fieldStatusDot {
                background-color: #ef4444;
                border: 1px solid rgba(248, 250, 252, 0.48);
                border-radius: 9px;
            }

            QLabel#fieldStatusDot[connected="true"] {
                background-color: #22c55e;
                border: 1px solid rgba(187, 247, 208, 0.80);
            }

            QLabel#fieldStatusText {
                color: #e5e7eb;
                font-size: 12px;
                font-weight: 700;
            }

            QFrame#magneticPlotFrame {
                background-color: #111b2e;
                border: 1px solid rgba(96, 125, 166, 0.58);
                border-radius: 6px;
            }

            QFrame#magneticPlotFrame:hover {
                border-color: rgba(147, 197, 253, 0.74);
            }

            QLabel#pidStatusCard {
                background-color: rgba(15, 23, 42, 0.86);
                border: 1px solid rgba(51, 65, 85, 0.86);
                border-radius: 6px;
                color: #cbd5e1;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 11px;
                font-weight: 600;
                padding: 6px 10px;
            }

            QFrame#pidControllerState {
                background-color: rgba(17, 24, 39, 0.92);
                border: 1px solid rgba(71, 85, 105, 0.84);
                border-radius: 6px;
            }

            QLabel#pidControllerMetric {
                background-color: rgba(15, 23, 42, 0.86);
                border: 1px solid rgba(51, 65, 85, 0.86);
                border-radius: 4px;
                color: #bfdbfe;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 11px;
                font-weight: 600;
                padding: 3px 8px;
            }

            QWidget#pidVisualizationViewport {
                background-color: rgba(15, 23, 42, 0.96);
                border: 1px solid rgba(51, 65, 85, 0.86);
                border-radius: 9px;
            }

            QFrame#fieldRow {
                background-color: rgba(17, 24, 39, 0.78);
                border: 1px solid rgba(51, 65, 85, 0.86);
                border-radius: 8px;
            }

            QFrame#fieldRow[selected="true"] {
                background-color: rgba(37, 99, 235, 0.22);
                border: 2px solid rgba(96, 165, 250, 0.72);
            }

            QLabel#fieldName {
                color: #e5e7eb;
                font-size: 13px;
                font-weight: 700;
            }

            QLabel#fieldValue,
            QLabel#fieldActualValue {
                background-color: rgba(15, 23, 42, 0.90);
                border: 1px solid rgba(71, 85, 105, 0.88);
                border-radius: 4px;
                color: #bfdbfe;
                font-family: "__APP_FONT__", Consolas, monospace;
                font-size: 14px;
                font-weight: 600;
                min-width: 74px;
                padding: 4px;
            }

            QLabel#fieldActualValue {
                background-color: rgba(6, 78, 59, 0.16);
                border-color: rgba(45, 212, 191, 0.34);
                color: #a7f3d0;
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
                background-color: rgba(17, 24, 39, 0.78);
                border: 1px solid rgba(51, 65, 85, 0.86);
                border-radius: 10px;
                color: #e5e7eb;
                font-weight: 700;
                min-height: 58px;
                padding: 8px;
            }

            QLabel#fieldEditorTitle {
                color: #bfdbfe;
                font-family: "__APP_FONT__", Segoe UI, Arial, sans-serif;
                font-size: 15px;
                font-weight: 700;
                min-width: 120px;
            }

            QDoubleSpinBox#fieldTargetInput {
                background-color: rgba(15, 23, 42, 0.96);
                border: 1px solid rgba(71, 85, 105, 0.88);
                border-radius: 5px;
                color: #bfdbfe;
                font-family: Consolas, "Cascadia Mono", monospace;
                font-size: 18px;
                font-weight: 700;
                min-height: 40px;
                min-width: 260px;
                padding: 4px 10px;
            }

            QFrame#fieldDigitAdjuster {
                background-color: rgba(15, 23, 42, 0.90);
                border: 1px solid rgba(51, 65, 85, 0.86);
                border-radius: 8px;
                padding: 0;
            }

            QLabel#fieldDigit {
                background-color: rgba(15, 23, 42, 0.96);
                border: 1px solid rgba(71, 85, 105, 0.88);
                border-radius: 4px;
                color: #bfdbfe;
                font-family: Consolas, "Cascadia Mono", monospace;
                font-size: 20px;
                font-weight: 700;
                max-height: 36px;
                min-height: 36px;
                min-width: 42px;
                padding: 1px 4px;
            }

            QLabel#fieldDigit[selected="true"] {
                background-color: rgba(37, 99, 235, 0.70);
                border: 2px solid rgba(147, 197, 253, 0.95);
                color: #ffffff;
            }

            QLabel#fieldDigitDecimal {
                color: #cbd5e1;
                font-family: Consolas, "Cascadia Mono", monospace;
                font-size: 20px;
                font-weight: 700;
                max-height: 34px;
                min-height: 34px;
                min-width: 8px;
            }

            QPushButton#fieldDigitArrow {
                background-color: rgba(30, 41, 59, 0.86);
                border: 1px solid rgba(71, 85, 105, 0.84);
                border-radius: 4px;
                color: #bfdbfe;
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
                background-color: rgba(15, 23, 42, 0.96);
                border: 1px solid rgba(71, 85, 105, 0.88);
                border-radius: 4px;
                height: 10px;
            }

            QSlider#fieldPowerSlider::sub-page:horizontal {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #1d4ed8,
                    stop: 0.65 #2563eb,
                    stop: 1 #60a5fa
                );
                border-radius: 4px;
            }

            QSlider#fieldPowerSlider::handle:horizontal {
                background-color: #93c5fd;
                border: 1px solid #dbeafe;
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
                background-color: rgba(17, 24, 39, 0.78);
                border: 1px solid rgba(51, 65, 85, 0.86);
                border-radius: 10px;
            }

            QLabel#pidTitle {
                color: #e5e7eb;
                font-family: "__APP_FONT__", Segoe UI, Arial, sans-serif;
                font-size: 15px;
                font-weight: 700;
            }

            QFrame#pidControlTitlePanel {
                background-color: rgba(30, 41, 59, 0.72);
                border: none;
                border-left: 3px solid #3b82f6;
                border-radius: 3px;
            }

            QLabel#pidControlTitle,
            QLabel#pidControlSubtitle {
                background: transparent;
                border: none;
                font-family: "Segoe UI", Arial, sans-serif;
            }

            QLabel#pidControlTitle {
                color: #e5e7eb;
                font-size: 17px;
                font-weight: 700;
                letter-spacing: 1px;
            }

            QLabel#pidControlSubtitle {
                color: #94a3b8;
                font-size: 9px;
                font-weight: 600;
                letter-spacing: 1px;
            }

            QLabel#pidStatus {
                color: #bfdbfe;
                font-family: "__APP_FONT__", Consolas, monospace;
                font-size: 12px;
                font-weight: 700;
            }

            QLabel#pidFieldLabel {
                color: #e5e7eb;
                font-size: 12px;
                font-weight: 700;
            }

            QComboBox#pidChannelSelect,
            QComboBox#pidTunerChannel,
            QComboBox#pidTunerProfile,
            QComboBox#pidTunerSafetyProfile,
            QSpinBox#pidSpin,
            QDoubleSpinBox#pidSpin {
                background-color: rgba(15, 23, 42, 0.96);
                border: 1px solid rgba(71, 85, 105, 0.88);
                border-radius: 5px;
                color: #e5e7eb;
                min-height: 28px;
                padding: 3px 8px;
            }

            QLabel#pidTunerSubtitle {
                color: #94a3b8;
                font-size: 12px;
            }

            QFrame#pidCandidatePanel {
                background-color: rgba(15, 23, 42, 0.90);
                border: 1px solid rgba(51, 65, 85, 0.86);
                border-radius: 7px;
            }

            QFrame#pidBoundsPanel {
                background-color: rgba(15, 23, 42, 0.72);
                border: 1px solid rgba(51, 65, 85, 0.78);
                border-radius: 7px;
            }

            QFrame#pidBoundCard {
                background-color: rgba(17, 24, 39, 0.88);
                border: 1px solid rgba(51, 65, 85, 0.78);
                border-radius: 5px;
            }

            QLabel#pidSectionTitle,
            QLabel#pidBoundTitle,
            QLabel#pidBoundSummary,
            QLabel#pidBoundLabel {
                border: none;
                color: #e5e7eb;
                font-family: "Segoe UI", Arial, sans-serif;
            }

            QLabel#pidSectionTitle,
            QLabel#pidBoundTitle {
                font-size: 12px;
                font-weight: 700;
            }

            QLabel#pidBoundTitle {
                color: #bfdbfe;
                font-size: 17px;
            }

            QLabel#pidBoundSummary {
                color: #ffffff;
                font-size: 14px;
                font-weight: 600;
                padding: 4px 2px;
            }

            QLabel#pidBoundLabel {
                color: #94a3b8;
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
                background-color: rgba(15, 23, 42, 0.96);
                border: 1px solid rgba(71, 85, 105, 0.88);
                border-radius: 5px;
                color: #e5e7eb;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 12px;
                font-weight: 600;
                min-height: 26px;
                padding: 6px 10px;
            }

            QLabel#pidCandidateValue,
            QLabel#pidStatusValue {
                background-color: rgba(15, 23, 42, 0.96);
                border: 1px solid rgba(71, 85, 105, 0.88);
                border-radius: 5px;
                color: #e5e7eb;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 13px;
                font-weight: 600;
                padding: 5px 9px;
            }

            QLabel#pidStatusValue {
                background-color: rgba(17, 24, 39, 0.96);
                border-color: rgba(51, 65, 85, 0.86);
                color: #cbd5e1;
                font-size: 12px;
            }

            QFrame#pidTunerViewport {
                background-color: rgba(15, 23, 42, 0.94);
                border: 1px solid rgba(51, 65, 85, 0.86);
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
                background-color: rgba(37, 99, 235, 0.86);
                border-color: rgba(96, 165, 250, 0.82);
                color: #eff6ff;
            }

            QPushButton#pidEnable {
                background-color: rgba(30, 41, 59, 0.82);
                border: 1px solid rgba(71, 85, 105, 0.88);
                color: #e5e7eb;
                min-height: 28px;
                text-align: center;
            }

            QPushButton#pidEnable:checked {
                background-color: rgba(37, 99, 235, 0.82);
                border: 1px solid rgba(147, 197, 253, 0.82);
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
                border: 1px solid rgba(255, 122, 145, 0.46);
                color: #ffe4e4;
                min-height: 28px;
                text-align: center;
            }
            """.replace("__APP_FONT__", app_font)
        self.setStyleSheet(stylesheet)
        for window in self._monitor_windows.values():
            window.setStyleSheet(stylesheet)
            current_page = window.centralWidget()
            if current_page is not None:
                current_page.setStyleSheet(stylesheet)


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
        "python main.py -simulation -smoke2, "
        "python main.py -simulation -cyclotron, or python main.py -ZMQ"
    )
