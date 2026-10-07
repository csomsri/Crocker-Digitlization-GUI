"""App-wide floating diagnostics; does not schedule extra chart repaints."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import math
import shutil
import subprocess
from time import perf_counter, process_time
import weakref

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication, QDialog, QFormLayout, QLabel, QWidget


def query_gpus():
    executable = shutil.which('nvidia-smi')
    if not executable:
        return 'Unavailable (nvidia-smi not installed)'
    try:
        result = subprocess.run(
            [executable, '--query-gpu=index,utilization.gpu,memory.used,memory.total',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=2,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        if result.returncode:
            return 'Unavailable (GPU query failed)'
        rows = []
        for line in result.stdout.splitlines():
            index, usage, used, total = (part.strip() for part in line.split(','))
            rows.append(f'GPU {index}: {usage}% | VRAM {used}/{total} MiB')
        return '\n'.join(rows) or 'No NVIDIA GPUs detected'
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 'Unavailable (GPU query failed or timed out)'


class FPSMonitor(QObject):
    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self._charts = weakref.WeakKeyDictionary()
        self._selected_chart = None
        self._gui_batches = 0
        self._gui_paint_pending = False
        self._last_refresh = perf_counter()
        self._last_cpu = process_time()
        self._packet_sample = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._gpu_future = None
        self._stopped = False
        self.panel = QDialog(window, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.panel.setWindowTitle('Live performance — FPS')
        self.panel.setMinimumWidth(390)
        layout = QFormLayout(self.panel)
        self._labels = {}
        for title in ('GUI repaint FPS', 'Chart FPS', 'Frame interval', 'GPU / VRAM', 'Telemetry', 'Data age', 'CPU (process)', 'UI timer delay'):
            label = QLabel('Waiting…', self.panel)
            label.setWordWrap(True)
            layout.addRow(title, label)
            self._labels[title] = label
        self._labels['GUI repaint FPS'].setToolTip(
            'Paint-event batches per second across the main and assigned-monitor '
            'windows. Child-widget paints in the same event-loop batch count once. '
            'Excludes this panel. Idle GUI can report zero; this is not display refresh rate.'
        )
        note = QLabel(
            'GUI FPS counts repaint batches (idle can be zero). '
            'Chart FPS range is per visible OpenGL widget. Frame intervals measure '
            'presentation cadence, not GPU render time. GPU usage is device-wide; '
            'CUDA kernel timing is not instrumented. Close hides this panel; F10 reopens it.',
            self.panel,
        )
        note.setWordWrap(True)
        layout.addRow(note)
        self._shortcut = QShortcut(QKeySequence('F10'), window)
        self._shortcut.activated.connect(self._show_panel)
        QApplication.instance().aboutToQuit.connect(self.stop)
        QApplication.instance().installEventFilter(self)
        self._discover()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._show_panel()

    def _show_panel(self):
        self.panel.show()
        self.panel.raise_()

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        self._timer.stop()
        QApplication.instance().removeEventFilter(self)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress and watched in self._charts:
            self._selected_chart = weakref.ref(watched)

        if event.type() == QEvent.Paint and watched in self._charts:
            reference = weakref.ref(watched)
            self._frame_swapped(reference)

        if event.type() == QEvent.Paint and isinstance(watched, QWidget) and watched.isWindow():
            top = watched.window()
            monitored = top is self._window or any(
                top is window for window in
                getattr(self._window, '_monitor_windows', {}).values()
            )
            if monitored and not self._gui_paint_pending and not self._stopped:
                self._gui_paint_pending = True
                QTimer.singleShot(0, self._finish_gui_paint_batch)
        return False
    
    def _finish_gui_paint_batch(self):
        if not self._stopped:
            self._gui_batches += 1
        self._gui_paint_pending = False

    def _discover(self):
        for widget in QApplication.allWidgets():
            is_chart = isinstance(widget, QOpenGLWidget) or widget.objectName() == "magneticChart"
            if is_chart and widget not in self._charts:
                self._charts[widget] = {
                    'frames': 0, 'start': perf_counter(), 'last': None,
                    'intervals': deque(maxlen=4096),
                }
                widget.installEventFilter(self)
                if isinstance(widget, QOpenGLWidget):
                    reference = weakref.ref(widget)
                    widget.frameSwapped.connect(lambda ref=reference: self._frame_swapped(ref))
            
    def _frame_swapped(self, reference):
        sample = self._charts.get(reference())
        if sample is None:
            return
        now = perf_counter()
        sample['frames'] += 1
        if sample['last'] is not None:
            sample['intervals'].append((now - sample['last']) * 1000)
        sample['last'] = now

    def _refresh(self):
        now = perf_counter()
        elapsed = max(now - self._last_refresh, 1e-9)
        self._labels['GUI repaint FPS'].setText(f'{self._gui_batches / elapsed:.1f}')
        self._gui_batches = 0
        
        rates, intervals = [], []
        selected_widget = self._selected_chart() if self._selected_chart else None
        selected_fps = None

        for widget, sample in list(self._charts.items()):
            try:
                visible = widget.isVisible()
            except RuntimeError:
                del self._charts[widget]
                continue
            if visible:
                fps = sample['frames'] / max(now - sample['start'], 1e-9)
                rates.append(fps)
                intervals.extend(sample['intervals'])
                if widget is selected_widget:
                    selected_fps = fps
            else:
                sample['last'] = None
            sample['frames'] = 0
            sample['start'] = now
            sample['intervals'].clear()

        # Shows clicked chart FPS if selected, otherwise show overall range
        if selected_widget and selected_fps is not None:
            title = getattr(selected_widget, 'title', 'Selected Chart')
            self._labels['Chart FPS'].setText(f'{title}: {selected_fps:.1f} FPS')
        elif rates:
            self._labels['Chart FPS'].setText(f'{min(rates):.1f}–{max(rates):.1f} ({len(rates)} visible)')
        else:
            self._labels['Chart FPS'].setText('No visible charts')

        intervals.sort()
        self._labels['Frame interval'].setText(
            f'Avg {sum(intervals)/len(intervals):.1f} ms | '
            f'p95 {intervals[math.ceil(len(intervals)*0.95)-1]:.1f} ms'
            if intervals else 'Waiting for consecutive frames'
        )
        cpu = process_time()
        self._labels['CPU (process)'].setText(
            f'{max(0, cpu-self._last_cpu)/elapsed*100:.1f}% (100% = one core)'
        )
        self._labels['UI timer delay'].setText(f'{max(0, elapsed-1)*1000:.1f} ms')
        self._last_cpu, self._last_refresh = cpu, now
        self._refresh_telemetry(now)
        if self._gpu_future is not None and self._gpu_future.done():
            self._labels['GPU / VRAM'].setText(self._gpu_future.result())
            self._gpu_future = None
        if self._gpu_future is None and not self._stopped:
            self._gpu_future = self._executor.submit(query_gpus)
        self._discover()

    def _refresh_telemetry(self, now):
        page = getattr(self._window, 'pages', {}).get('Field Ctrl')
        backend = getattr(page, 'backend', None)
        try:
            if backend is None:
                raise ValueError('No backend')
            health = backend.Health()
            packets = int(health['received_packets'])
            age = float(health['packet_age_ms'])
            previous = self._packet_sample
            rate = None
            if previous is not None and previous[0] is backend and packets >= previous[1]:
                rate = (packets - previous[1]) / max(now - previous[2], 1e-9)
            self._packet_sample = (backend, packets, now)
            rate_text = f'{rate:.1f} packets/s' if rate is not None else 'Sampling rate…'
            self._labels['Telemetry'].setText(f'{rate_text} | {packets} received')
            self._labels['Data age'].setText(
                f"{age:.0f} ms | {health.get('connection', 'unknown')}"
                if packets and math.isfinite(age) and age >= 0 else 'No telemetry received'
            )
        except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
            self._packet_sample = None
            self._labels['Telemetry'].setText('Backend unavailable')
            self._labels['Data age'].setText('Unavailable')
