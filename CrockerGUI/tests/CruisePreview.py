"""Render the actual Qt workspace offscreen with illustrative data, without hardware."""
import os
import sys
import time
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase, QFont
from python.app.Automation.PidControlPage import PidControlPage

app = QApplication.instance() or QApplication([])
for name in ('segoeui.ttf', 'segoeuib.ttf'):
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
app.setFont(QFont('Segoe UI', 10))
app.setStyleSheet((ROOT/'python'/'app'/'theme'/'application.qss').read_text(encoding='utf-8').replace('__APP_FONT__', 'Segoe UI'))
page = PidControlPage(lambda: None, 'simulation', manage_backend=False)
page.timer.stop()
page.resize(1420, 1280)
page.setpoint_input.setValue(5)
page.channel_select.setCurrentIndex(9)
page.show()
app.processEvents()
rows = []
import math
for i in range(120):
    rows.append((i, 5-.7*math.exp(-i/18)*math.cos(i/5), 5, 420+3*math.sin(i/15), 420+3*math.sin((i-4)/15)))
page.time_plot.set_samples(rows)
page.cruise_workspace.status.setText('LAYOUT PREVIEW · Illustrative beam / coil traces · Hardware not connected')
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
app.processEvents()
page.grab().save(str(out/'beam-cruise-workspace.png'))
page.cruise_workspace.show_settings()
app.processEvents()
page.grab().save(str(out/'beam-cruise-settings.png'))
page.cruise_workspace.settings.close()
page.stop_backend()
print(out/'beam-cruise-workspace.png')
