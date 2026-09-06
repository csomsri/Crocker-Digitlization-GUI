from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QStackedWidget,
    QWidget,
)
from PySide6.QtCore import QMargins, QRect, QSettings, Qt, QTimer
from PySide6.QtGui import QFont
from python.app.theme import load_app_font, load_stylesheet
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
from python.app.Display.WindowMode import set_decorated, set_screen_filling
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
from source.Python.Services.InterlockService import InterlockService
from source.Python.Services.SignalMapService import SignalMapService


from python.app.PageRegistry import PAGE_BUILDERS, DETAIL_BUILDERS, WINDOW_RESOLUTIONS


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
        self.signal_map = SignalMapService(self._crocker_root / "config" / "signal_map.json")
        self.interlocks = InterlockService(self._crocker_root / "config" / "interlock_config.json")
        self._settings = QSettings("Crocker Nuclear Lab", "Digitalization")
        self._manual_max_change = max(
            0.01,
            float(self._settings.value("controls/manual_max_change_a", 10.0)),
        )
        self._confirm_large_manual_changes = self._settings.value(
            "controls/confirm_large_manual_changes", True, type=bool
        )
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
                page_kwargs = {
                    "backend_mode": field_backend_mode,
                    "zmq_endpoint": self.zmq_endpoint,
                }
                if title == "PID Control":
                    field_page = self.pages.get("Field Ctrl")
                    if isinstance(field_page, FieldCtrlPage):
                        page_kwargs["shared_backend"] = field_page.backend
                    page_kwargs["tuning_enabled"] = self.simulation_mode is not None
                    page_kwargs["manage_backend"] = False
                else:
                    page_kwargs["manual_max_change"] = self._manual_max_change
                    page_kwargs["confirm_large_changes"] = (
                        self._confirm_large_manual_changes and self.simulation_mode is None
                    )
                detail_page = page_builder(
                    lambda checked=False, category=parent_category:
                        self.show_category(category),
                    **page_kwargs,
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
                    manual_max_change=self._manual_max_change,
                    confirm_large_manual_changes=self._confirm_large_manual_changes,
                    apply_manual_control_safety=self.apply_manual_control_safety,
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
                    save_config=self.save_alarm_config,
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
        self._controller_monitors = set(screen_ids)
        self._controller_layout = layout if layout in {"Auto", "Compact", "Full"} else "Auto"
        self._settings.setValue("display/controller_monitors", list(self._controller_monitors))
        self._settings.setValue("display/controller_layout", self._controller_layout)
        self._settings.sync()

    def apply_manual_control_safety(self, maximum_change: float, require_confirmation: bool) -> None:
        self._manual_max_change = max(0.01, float(maximum_change))
        self._confirm_large_manual_changes = bool(require_confirmation)
        self._settings.setValue("controls/manual_max_change_a", self._manual_max_change)
        self._settings.setValue(
            "controls/confirm_large_manual_changes",
            self._confirm_large_manual_changes,
        )
        self._settings.sync()
        field_page = self.pages.get("Field Ctrl")
        if isinstance(field_page, FieldCtrlPage):
            field_page.set_manual_safety_settings(
                self._manual_max_change,
                self._confirm_large_manual_changes and self.simulation_mode is None,
            )

    def show_monitoring_page(self, screen_id: str, page_name: str) -> bool:
        if screen_id not in self._controller_monitors:
            return False
        if page_name not in self._monitoring_page_names():
            return False
        screens = {screen_key(screen): screen for screen in QApplication.screens()[:4]}
        screen = screens.get(screen_id)
        if screen is None:
            return False
        if screen is self.screen():
            page = self.pages.get(page_name)
            if page is None:
                return False
            self.stack.setCurrentWidget(page)
            self._refresh_settings_monitors()
            return True
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
                page_kwargs = {
                    "backend_mode": field_backend_mode,
                    "zmq_endpoint": self.zmq_endpoint,
                }
                if page_name == "PID Control":
                    field_page = self.pages.get("Field Ctrl")
                    if isinstance(field_page, FieldCtrlPage):
                        page_kwargs["shared_backend"] = field_page.backend
                    page_kwargs["tuning_enabled"] = self.simulation_mode is not None
                    page_kwargs["manage_backend"] = False
                else:
                    page_kwargs["manual_max_change"] = self._manual_max_change
                    page_kwargs["confirm_large_changes"] = (
                        self._confirm_large_manual_changes and self.simulation_mode is None
                    )
                return builder(
                    go_back,
                    **page_kwargs,
                )
            if page_name == "Database History":
                return builder(
                    go_back,
                    db_path=self.db_path,
                    back_label="Back to Settings",
                )
            if page_name == "Display Controller":
                return builder(
                    go_back,
                    monitoring_pages=self._monitoring_page_names(),
                    monitor_entries=self._monitor_entries,
                    show_on_monitor=self.show_monitoring_page,
                    controller_layout=lambda: self._controller_layout,
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
                    save_config=self.save_alarm_config,
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
                    manual_max_change=self._manual_max_change,
                    confirm_large_manual_changes=self._confirm_large_manual_changes,
                    apply_manual_control_safety=self.apply_manual_control_safety,
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

        def finish_transition() -> None:
            if transition != self._display_transition:
                return
            if mode == "Windowed":
                set_decorated(self)
                self._apply_windowed_resolution()
            else:
                set_screen_filling(self, self.screen() or QApplication.primaryScreen())
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
        self.signal_map.enrich_snapshot(snapshot)
        beam_state = self.beam_calibration.update(snapshot).to_dict()
        alarms = [alarm.to_dict() for alarm in self.alarm_service.update(snapshot, beam_state)]
        interlock_alarms = self.interlocks.evaluate(snapshot)
        snapshot["beam"] = beam_state
        snapshot["active_alarms"] = alarms + interlock_alarms
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

    def save_alarm_config(self, updates: dict) -> dict:
        return self.alarm_service.save_config(updates)

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
        app_font = load_app_font()
        app = QApplication.instance()
        if app is not None:
            app.setProperty("appFontFamily", app_font)
            app.setFont(QFont("Segoe UI", 10))
        stylesheet = load_stylesheet(app_font)
        self.setStyleSheet(stylesheet)
        for window in self._monitor_windows.values():
            window.sync_theme()


def run_app(
    backend_mode: str,
    zmq_endpoint: str = "tcp://0.0.0.0:5555",
    simulation_mode: str | None = None,
    enable_data_pipeline: bool = False,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    app = QApplication([])
    # Use Qt's own popup implementation consistently across Windows displays.
    # The native Windows style can open a menu without committing mouse clicks
    # in a screen-filling window. The existing stylesheet supplies our theme.
    app.setStyle("Fusion")
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
