"""Bounded background read jobs, with results delivered by the Qt event loop."""
import sqlite3
from contextlib import closing
from pathlib import Path
from PySide6.QtCore import QObject, QTimer
from source.Python.Data.file_writer import FileWriter

reader = FileWriter('database-history-reader', 32)


def read_queries(path, queries):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=.1)) as c:
        c.row_factory = sqlite3.Row
        return [[dict(row) for row in c.execute(sql, args)] for sql, args in queries]


class ReadJobs(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.pending = {}
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)

    def submit(self, key, path, queries, success, failure):
        self.call(key, read_queries, (path, queries), success, failure)

    def call(self, key, function, args, success, failure, worker=reader):
        previous = self.pending.pop(key, None)
        if previous:
            previous[0].cancel()
        self.pending[key] = (worker.submit(function, *args), success, failure)
        self.timer.start(50)

    def poll(self):
        for key, (future, success, failure) in list(self.pending.items()):
            if not future.done():
                continue
            del self.pending[key]
            try:
                result = future.result()
            except Exception as exc:
                failure(str(exc))
            else:
                success(result)
        if not self.pending:
            self.timer.stop()
