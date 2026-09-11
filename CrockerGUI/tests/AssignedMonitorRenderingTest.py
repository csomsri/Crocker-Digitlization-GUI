"""Check native chart rendering across top-level windows (requires OpenGL 4.6).

Run directly with Python; no backend or hardware connection is started.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import zmq  # Import before PySide's import hook, as in main.py.
from PySide6.QtGui import QOpenGLContext
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from python.app.MainWindow import run_app
from python.app.Monitoring.MagneticFieldMonitoringPage import NativeMagneticBarPlot


def main():
    windows = []

    def make_chart(*args):
        chart = NativeMagneticBarPlot("Assigned display text", (0, 1, 2, 3))
        chart.resize(480, 360)
        windows.append(chart)
        return chart

    def check_windows(*args):
        first = windows[0]
        QTest.qWait(150)
        assert first._ready, "Native OpenGL chart failed to initialize"
        reference = first.grabFramebuffer()
        assert not reference.isNull()
        # Repeat assignment after closing the previous auxiliary window.
        for _ in range(2):
            second = make_chart()
            second.show()
            QTest.qWait(150)
            assert second._ready, "Assigned chart failed to initialize"
            assert QOpenGLContext.areSharing(first.context(), second.context()), (
                "Assigned windows must share the native font resources"
            )
            actual = second.grabFramebuffer()
            assert actual == reference, "Text/chart pixels differ on the assigned window"
            second.close()
            second.deleteLater()
            QTest.qWait(50)
            windows.remove(second)
        print("Assigned-window context sharing and matching chart pixels passed")
        return 0

    try:
        with patch("python.app.MainWindow.MainWindow", side_effect=make_chart), \
                patch.object(QApplication, "exec", check_windows):
            assert run_app("simulation", simulation_mode="smoke") == 0
    finally:
        for window in windows:
            window.close()


if __name__ == "__main__":
    main()
