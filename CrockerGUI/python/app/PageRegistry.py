"""Page builders and navigation categories shared by all application windows."""

from python.app.Automation.AutomationPage import AutomationPage
from python.app.Automation.PidControlPage import PidControlPage
from python.app.Automation.PythonPIDPage import PythonPIDPage
from python.app.Controls.AlarmPage import AlarmPage
from python.app.Controls.BeamRangePage import BeamRangePage
from python.app.Controls.FieldCtrlPage import FieldCtrlPage
from python.app.Controls.ManualControlsPage import ManualControlsPage
from python.app.Controls.SnapshotPage import SnapshotPage
from python.app.Configuration.ConfigurationPage import ConfigurationPage
from python.app.Configuration.RecallPage import RecallPage
from python.app.Configuration.ScalingPage import ScalingPage
from python.app.Configuration.SettingsPage import SettingsPage
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
    "PythonPID": ("Automation", PythonPIDPage),
}

