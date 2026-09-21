"""Ordered background file exports used by PID's legacy CSV/JSON views."""
import csv
import json
from itertools import islice
from concurrent.futures import Future
from pathlib import Path
from queue import Queue, Full, Empty
from threading import Thread, Event, Lock


class FileWriter:
    def __init__(self, name='PID-file-export', capacity=2048):
        self.queue = Queue(capacity)
        self.name = name
        self.thread = None
        self.lock = Lock()
        self.closing = Event()
        self.done = Event()
        self.error = ''
        self.rejected = 0

    def submit(self, fn, *args):
        future = Future()
        with self.lock:
            try:
                if self.closing.is_set():
                    raise Full
                self.queue.put_nowait((future, fn, args))
            except Full:
                self.rejected += 1
                future.set_exception(RuntimeError('File export queue unavailable'))
                return future
            if self.thread is None:
                self.thread = Thread(target=self._run, name=self.name, daemon=True)
                self.thread.start()
        return future

    def _run(self):
        while not self.closing.is_set() or not self.queue.empty():
            try:
                future, fn, args = self.queue.get(timeout=.1)
            except Empty:
                continue
            if not future.set_running_or_notify_cancel():
                self.queue.task_done()
                continue
            try:
                future.set_result(fn(*args))
            except Exception as exc:
                self.error = str(exc)
                future.set_exception(exc)
            finally:
                self.queue.task_done()
        self.done.set()

    def close(self):
        self.closing.set()
        if self.thread is None:
            self.done.set()


file_writer = FileWriter()


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def write_csv(path, rows, header=None, append=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not append or not path.exists() or path.stat().st_size == 0
    with path.open('a' if append else 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        if header and needs_header:
            writer.writerow(header)
        writer.writerows(rows)


def read_summaries(directory):
    rows = []
    for path in sorted(directory.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            rows.append((path, json.loads(path.read_text(encoding='utf-8'))))
        except (OSError, ValueError):
            continue
    return rows


def read_csv_range(path, offset, last):
    with path.open(newline='', encoding='utf-8') as handle:
        reader = csv.reader(handle)
        return next(reader), list(islice(reader, offset, min(last, offset+1001)))
