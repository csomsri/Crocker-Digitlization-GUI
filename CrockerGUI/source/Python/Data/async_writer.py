"""Bounded, ordered SQLite mailbox. Only its worker ever opens the database."""
from __future__ import annotations

import sqlite3
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, Thread


@dataclass(frozen=True)
class Statement:
    sql: str
    rows: tuple[tuple, ...]


class AsyncSQLiteWriter:
    def __init__(self, path, initialize, *, name, capacity=4096, reserve=128):
        self.path = Path(path)
        self.initialize = initialize
        self.name = name
        self.capacity, self.reserve = capacity, min(reserve, capacity // 2)
        self._queue = deque()
        self._lock = Lock()
        self._wake = Event()
        self._thread = None
        self._closing = False
        self._deadline = None
        self.done = Event()
        self.error = ''
        self.rejected = 0
        self.written = 0
        self.pending = 0
        self.last_commit = None
        self._gap_reported = 0

    def submit(self, statements, *, critical=False):
        # Copy rows to immutable tuples before handing them to the worker.
        message = tuple(Statement(s.sql, tuple(tuple(r) for r in s.rows)) for s in statements)
        with self._lock:
            limit = self.capacity if critical else self.capacity - self.reserve
            if self._closing or len(self._queue) >= limit:
                self.rejected += 1
                return False
            self._queue.append(message)
            if self._thread is None:
                self._thread = Thread(target=self._run, name=self.name, daemon=True)
                self._thread.start()
        self._wake.set()
        return True

    def status(self):
        with self._lock:
            return dict(started=self._thread is not None, queue_depth=len(self._queue),
                        in_flight=self.pending, rejected=self.rejected, written=self.written,
                        last_commit=self.last_commit, error=self.error,
                        closing=self._closing, drained=self.done.is_set())

    def close(self, timeout=10.0):
        """Request a drain; never joins or touches the filesystem on the caller."""
        with self._lock:
            self._closing = True
            self._deadline = time.monotonic() + timeout
            if self._thread is None:
                self.done.set()
        self._wake.set()

    def _run(self):
        connection = None
        batch = []
        try:
            while True:
                with self._lock:
                    if not batch:
                        batch = [self._queue.popleft() for _ in range(min(100, len(self._queue)))]
                    self.pending = len(batch)
                    closing, deadline = self._closing, self._deadline
                if closing and not batch:
                    break
                if closing and time.monotonic() >= deadline:
                    self.error = 'Shutdown deadline exceeded; uncommitted records remain'
                    break
                if batch and not closing:
                    flush_at = time.monotonic()+0.1
                    while len(batch) < 100 and not self._closing:
                        remaining = flush_at-time.monotonic()
                        if remaining <= 0:
                            break
                        self._wake.wait(remaining)
                        self._wake.clear()
                        with self._lock:
                            batch.extend(self._queue.popleft()
                                         for _ in range(min(100-len(batch), len(self._queue))))
                            self.pending = len(batch)
                try:
                    if connection is None:
                        self.path.parent.mkdir(parents=True, exist_ok=True)
                        connection = sqlite3.connect(self.path, timeout=0.1)
                        connection.execute('PRAGMA busy_timeout=100')
                        connection.execute('PRAGMA journal_mode=WAL')
                        self.initialize(connection)
                        connection.execute('CREATE TABLE IF NOT EXISTS recording_gaps '
                                           '(timestamp REAL, rejected_messages INTEGER, writer TEXT)')
                        connection.commit()
                    if batch:
                        with connection:
                            for message in batch:
                                for statement in message:
                                    connection.executemany(statement.sql, statement.rows)
                            rejected = self.rejected
                            if rejected > self._gap_reported:
                                connection.execute('INSERT INTO recording_gaps VALUES (?,?,?)',
                                                   (time.time(), rejected-self._gap_reported, self.name))
                        self._gap_reported = rejected
                        self.written += len(batch)
                        self.last_commit = time.time()
                        self.error = ''
                        batch = []
                        self.pending = 0
                except (sqlite3.Error, OSError) as exc:
                    self.error = str(exc)
                    if connection is not None:
                        connection.close()
                        connection = None
                    # Keep the failed batch, preserving order across retry.
                    self._wake.wait(0.1)
                    self._wake.clear()
                    continue
                self._wake.wait(0.1)
                self._wake.clear()
        finally:
            if connection is not None:
                connection.close()
            self.done.set()


def insert(table, values):
    columns = tuple(values)
    return Statement(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                     (tuple(values[c] for c in columns),))
