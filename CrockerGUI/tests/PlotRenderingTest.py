"""Headless chart checks; --native also verifies real OpenGL framebuffer rendering."""
import os
from pathlib import Path
import sys
import time
import math
from types import SimpleNamespace

native = '--native' in sys.argv
if not native:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt, QPointF
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from python.app.theme import load_stylesheet
app.setStyleSheet(load_stylesheet('Segoe UI'))
from python.app.Automation.HardwareProfileDialog import HardwareProfileDialog
from python.app.Automation.BeamResponsePlot import BeamResponsePlot
from python.app.Automation.GainSurfaceWidget import GainSurfaceWidget
from python.app.Automation.SurrogatePlotWidget import SurrogatePlotWidget
from python.app.widgets.MagneticFieldWidgets import CHANNEL_NAMES, make_time_domain_plot
from python.app.Automation.PidControlPage import PidControlPage

output = Path(sys.argv[sys.argv.index('--output')+1]) if '--output' in sys.argv else None
widgets = []
page = PidControlPage(lambda: None, 'simulation')
page.timer.stop()
page.resize(1280, 820)
page.last_safety_message = "No hardware profile for TC1. Open Edit Hardware Profile and configure/review this coil's limits. Existing profiles: TC10."
page._refresh_status()
widgets.append(('pid-status', page, [page.time_plot.beam, page.time_plot.coil]))
profile = HardwareProfileDialog(None, CHANNEL_NAMES)
profile.resize(720, 740)
widgets.append(('profile', profile, []))
beam = BeamResponsePlot()
beam.resize(1100, 370)
beam.set_samples([(i*.1, 1+.05*math.sin(i*.1), 1., 50+.1*math.sin(i*.07), 50.) for i in range(240)])
widgets.append(('beam', beam, [beam.beam, beam.coil]))
cloud = GainSurfaceWidget()
cloud.resize(720, 540)
cloud.set_grid(dict(ready=True, parameter_names=['kp','ki','kd'],
                    points=[[i/10,j/10,k/10] for i in range(5) for j in range(5) for k in range(5)],
                    mean=[i+j+k for i in range(5) for j in range(5) for k in range(5)],
                    trials=[[.1,.2,.3]], best=[.1,.2,.3]))
widgets.append(('gains', cloud, [cloud.canvas]))
surrogate = SurrogatePlotWidget()
surrogate.resize(800, 400)
widgets.append(('surrogate', surrogate, [surrogate]))
field = make_time_domain_plot()
field.resize(900,170)
field.set_samples([(i*.1, 50+math.sin(i*.1), 50., math.sin(i*.1)) for i in range(200)])
widgets.append(('field', field, [field] if native else []))

for name, widget, surfaces in widgets:
    widget.setAttribute(Qt.WA_DontShowOnScreen, True)
    widget.show()
    for _ in range(25):
        app.processEvents()
        time.sleep(.01)
    if native:
        for surface in surfaces:
            assert surface.isValid(), f'{name}: no valid OpenGL context'
            assert not surface.grabFramebuffer().isNull(), f'{name}: empty framebuffer'
        if name == 'field':
            assert field._ready, getattr(field, '_initialization_error', 'Native chart not initialized')
    if output:
        image = widget.grab()
        assert image.save(str(output / f'{name}.png'))
    print(f'{name}: rendered' + (' with OpenGL' if surfaces and native else ''))

rect, ticks, _, _ = beam.beam._geometry()
event = SimpleNamespace(position=lambda: rect.center(), angleDelta=lambda: QPointF(0,120),
                        accept=lambda:None, ignore=lambda:None)
beam.beam.wheelEvent(event)
assert beam.beam._x_range[1]-beam.beam._x_range[0] < ticks[-1]-ticks[0]
beam.beam.mouseDoubleClickEvent(None)
assert beam.beam._x_range is None
beam.resize(600,600)
for _ in range(12): app.processEvents()
assert beam.beam.geometry().bottom() < beam.coil.geometry().top()
for _, widget, _ in widgets:
    widget.close()
page.stop_backend()
print('Chart layout, zoom, and reset passed')
