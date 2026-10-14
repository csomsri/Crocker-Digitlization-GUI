"""Capture every registered page and PID section using simulation only.

Run: python CrockerGUI/tests/PageVisualAudit.py --output <directory>
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication([])
    from python.app.MainWindow import MainWindow
    scratch = Path(tempfile.mkdtemp(prefix='crocker-visual-audit-'))
    settings = QSettings(str(scratch / 'settings.ini'), QSettings.IniFormat)
    with patch('python.app.MainWindow.QSettings', return_value=settings):
        window = MainWindow('simulation', 'tcp://127.0.0.1:59999',
                            db_path=scratch / 'telemetry.sqlite3')
    window.show()

    def settle():
        for _ in range(12):
            app.processEvents()
            time.sleep(.005)

    settle()
    window.resize(1440, 960)
    records = []

    def capture(name, section=''):
        settle()
        slug = re.sub(r'[^a-z0-9]+', '-', (name + '-' + section).lower()).strip('-')
        path = args.output / (slug + '.png')
        assert window.grab().save(str(path))
        page = window.pages[name]
        scroll = getattr(page, 'scroll_area', None)
        if scroll:
            assert scroll.horizontalScrollBar().maximum() == 0, f'{name}: horizontal overflow'
        records.append(dict(page=name, section=section, image=path.name,
                            horizontal_overflow=scroll.horizontalScrollBar().maximum() if scroll else 0,
                            vertical_scroll=scroll.verticalScrollBar().maximum() if scroll else 0))
        print(name, section, flush=True)

    try:
        for name, page in window.pages.items():
            window.go_to_page(name)
            if hasattr(page, 'scroll_area'):
                page.scroll_area.verticalScrollBar().setValue(0)
            nav = getattr(page, 'cruise_navigation', None)
            if nav:
                for index in range(nav.tabs.count()):
                    nav.tabs.setCurrentIndex(index)
                    if hasattr(page, 'scroll_area'):
                        page.scroll_area.verticalScrollBar().setValue(0)
                    capture(name, nav.tabs.tabText(index))
                nav.tabs.setCurrentIndex(0)
            elif hasattr(page, 'control_tab_buttons'):
                for button in page.control_tab_buttons:
                    button.click()
                    capture(name, button.text())
                page.control_tab_buttons[0].click()
            elif hasattr(getattr(page, 'workspace', None), 'control_tabs'):
                tabs = page.workspace.control_tabs
                for index in range(tabs.count()):
                    tabs.setCurrentIndex(index)
                    capture(name, tabs.tabText(index))
                tabs.setCurrentIndex(0)
            else:
                capture(name)
        window.go_to_page('PID Control')
        pid = window.pages['PID Control']
        pid.cruise_navigation.tabs.setCurrentIndex(pid.cruise_navigation.tuning_tab_index)
        window.workspace_shell.toggle_sidebar.setChecked(False)
        capture('PID Control', 'AI tuning - directory collapsed')
        main_page = window.stack.currentWidget()
        window.open_page_window('Monitoring')
        detached = window._page_windows['Monitoring']
        monitoring = window.pages['Monitoring']
        next(button for button in monitoring.category_cards
             if button.title == 'RF Power Monitoring').click()
        assert detached.centralWidget() is window.pages['RF Power Monitoring']
        assert window.stack.currentWidget() is main_page
        detached.resize(1280, 820)
        settle()
        assert detached.grab().save(str(args.output / 'detached-monitoring-rf.png'))
        records.append(dict(page='Monitoring (detached)', section='RF Power',
                            image='detached-monitoring-rf.png', horizontal_overflow=0,
                            vertical_scroll=0))
        (args.output / 'manifest.json').write_text(json.dumps(records, indent=2))
    finally:
        window.close()
        for _ in range(200):
            app.processEvents()
            time.sleep(.01)
            if window._recording_closed:
                break
        assert window._recording_closed, 'Simulation services did not shut down'
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 14) if os.name == 'nt' else ImageFont.load_default()
    sheet = Image.new('RGB', (1440, ((len(records)+3)//4)*265), '#111214')
    draw = ImageDraw.Draw(sheet)
    for index, record in enumerate(records):
        x, y = index % 4 * 360, index // 4 * 265
        draw.text((x+8,y+5), record['page']+' / '+record['section'], font=font, fill='#f3f3f4')
        img = Image.open(args.output / record['image']).convert('RGB')
        img.thumbnail((356,235))
        sheet.paste(img,(x+2,y+27))
    sheet.save(args.output / 'contact-sheet.png')
    print(f'Audited {len(records)} views across {len(window.pages)} pages', flush=True)


if __name__ == '__main__':
    main()
