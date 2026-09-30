"""Exercise Qt ownership callbacks with hidden native graphics widgets."""
import math
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from python.app.widgets.MagneticFieldWidgets import NativeSpeedometer, TimeDomainPlot
from python.app.Monitoring.MagneticFieldMonitoringPage import NativeMagneticBarPlot, NativeMagneticLinePlot


def main():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.setAttribute(Qt.WA_DontShowOnScreen)
    layout = QVBoxLayout(host)
    widgets = [NativeSpeedometer(), TimeDomainPlot(),
               NativeMagneticBarPlot("Current µA", (0, 1)), NativeMagneticLinePlot("Coils", (0, 1))]
    widgets[0].set_values(50, 49.9, "TC1")
    widgets[1].set_samples([(i * .1, 50 + math.sin(i * .1), 50, math.sin(i * .1)) for i in range(100)])
    for widget in widgets:
        layout.addWidget(widget)
    host.resize(1000, 1100)

    def paint():
        for _ in range(12):
            app.processEvents()
            time.sleep(.01)
        for widget in widgets:
            assert widget._ready, getattr(widget, '_initialization_error', 'Native initialization failed')
            assert not widget.grabFramebuffer().isNull()

    host.show()
    paint()
    for widget in widgets:
        widget.release_native_resources()
        widget.update()
    paint()
    host.close()
    host.show()
    paint()
    # Destroy the actual Qt children: aboutToBeDestroyed must release the
    # resources in the correct widget context, including a shared Qt group.
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
    print("Qt native widget paint, cleanup, reopen and destruction passed")


if __name__ == '__main__':
    main()
