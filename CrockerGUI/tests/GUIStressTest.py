"""CPU/offscreen monitoring stress test. No hardware, sockets, or application DBs.

Run: py -3.13 CrockerGUI/tests/GUIStressTest.py --seconds 10 --output <directory>
Each of three phases runs for --seconds. Measures actual Qt widget rendering,
not native OpenGL or desktop compositing. Results are machine/load dependent.
"""
import argparse
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
import traceback

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QTimer, qInstallMessageHandler
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from python.app.Monitoring.LiveTelemetryPage import LiveTelemetryPage
from python.app.Monitoring.TelemetryFields import MONITOR_FIELDS
from python.app.theme import load_stylesheet, load_app_font


def distribution(values):
    values = sorted(values)
    return dict(count=len(values), median_ms=statistics.median(values) if values else None,
                p95_ms=values[min(len(values)-1, math.ceil(len(values)*.95)-1)] if values else None,
                max_ms=max(values) if values else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=10)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds <= 0:
        parser.error('--seconds must be positive and finite')
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    # Offscreen Qt does not discover Windows fonts automatically.
    system_font = Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts'/'segoeui.ttf'
    if system_font.exists():
        QFontDatabase.addApplicationFont(str(system_font))
        app.setFont(QFont('Segoe UI', 10))
    app.setStyleSheet(load_stylesheet(load_app_font()))
    errors, warnings = [], {}
    sys.excepthook = lambda *exc: errors.append(''.join(traceback.format_exception(*exc)))
    def qt_message(kind, context, message):
        key = f'{kind}: {message}'
        warnings[key] = warnings.get(key, 0) + 1
    qInstallMessageHandler(qt_message)
    snapshot = {}
    sequence = 0
    pages = []
    def publish():
        nonlocal sequence
        sequence += 1
        v = math.sin(sequence * .05)
        snapshot.update(timestamp=time.time(), sequence_number=sequence,
                        connection='Connected', simulated=True,
                        source=[v+i for i in range(6)], extraction=[v+i for i in range(6)],
                        extraction_angles=[v+i for i in range(6)], transport=[v+i for i in range(10)],
                        vacuum=[v+i for i in range(5)], rf_power_kv=25+v,
                        beam_current=.1, beam_range_idx=2,
                        beam={'quality': 'ok', 'display_ua': .1})
        for page in pages:
            page.refresh()

    report = {'scope': 'Four real monitoring pages; synthetic telemetry; offscreen CPU rendering',
              'python': sys.version, 'phases': [], 'errors': errors}
    try:
        for title in MONITOR_FIELDS:
            page = LiveTelemetryPage(title, lambda: None)
            page.timer.stop()
            page.set_snapshot_source(lambda: snapshot)
            page.resize(1280, 820)
            page.show()
            pages.append(page)
        app.processEvents()
        print('Filling every history beyond its 1200-sample capacity...', flush=True)
        for _ in range(1400):
            publish()
        for page in pages:
            assert all(len(h) == 1200 for h in page.history.values()), 'History cap failed'
            page.toggle_pause()
        identities = [page.last_identity for page in pages]
        publish()
        assert identities == [page.last_identity for page in pages], 'Pause changed displayed data'
        for page in pages:
            page.toggle_pause()
        assert all(page.last_identity[0] == sequence for page in pages), 'Resume failed'
        app.processEvents()
        for hz in (4, 20, 60):
            durations, refresh_times, heartbeat_lateness = [], [], []
            frames = 0
            started_cpu = time.process_time()
            started = time.perf_counter()
            previous = started
            def heartbeat():
                nonlocal previous
                now = time.perf_counter()
                heartbeat_lateness.append(max(0, (now-previous)*1000-10))
                previous = now
            def frame():
                nonlocal frames
                before = time.perf_counter()
                publish()
                refresh_times.append((time.perf_counter()-before)*1000)
                for index, page in enumerate(pages):
                    if frames % 10 == 0:
                        page.resize(*((800, 600) if frames % 20 == 0 else (1280, 820)))
                        page.table.selectRow((frames//10+index) % len(page.channels))
                    # Force real raster painting, rather than just queueing updates.
                    assert not page.grab().isNull(), 'Empty rendered widget'
                durations.append((time.perf_counter()-before)*1000)
                frames += 1
            beat, load, finish = QTimer(), QTimer(), QTimer()
            beat.timeout.connect(heartbeat)
            load.timeout.connect(frame)
            finish.setSingleShot(True)
            finish.timeout.connect(app.quit)
            beat.start(10)
            load.start(round(1000/hz))
            finish.start(round(args.seconds*1000))
            app.exec()
            beat.stop()
            load.stop()
            finish.stop()
            elapsed = time.perf_counter()-started
            result = dict(target_hz=hz, actual_hz=frames/elapsed, frames=frames,
                          wall_seconds=elapsed, process_cpu_seconds=time.process_time()-started_cpu,
                          frame=distribution(durations), refresh=distribution(refresh_times),
                          heartbeat_lateness=distribution(heartbeat_lateness))
            report['phases'].append(result)
            print(json.dumps(result), flush=True)
            assert frames and heartbeat_lateness, 'No event-loop progress'
            assert all(len(h) <= 1200 for p in pages for h in p.history.values())
        assert pages[0].grab().save(str(args.output/'monitoring.png'))
    except Exception:
        errors.append(traceback.format_exc())
    finally:
        for page in pages:
            page.timer.stop()
            page.close()
            page.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        report['qt_messages'] = warnings
        report['passed'] = not errors
        (args.output/'stress.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(f'Report: {args.output.resolve()} | passed={report["passed"]}', flush=True)
        qInstallMessageHandler(None)
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
