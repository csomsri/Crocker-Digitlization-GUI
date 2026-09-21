"""Database A mailbox, shared by telemetry, alarms and derived metrics."""
import sqlite3
import time
from threading import Event, Thread
from uuid import uuid4

from source.Python.Data.async_writer import AsyncSQLiteWriter, Statement
from source.Python.Data.data_logger import snapshot_to_readings
from source.Python.Data.pipeline_schema import initialize_schema


def snapshot_id(snapshot):
    # Native sequence can restart; the source timestamp disambiguates it.
    return f"{snapshot.get('timestamp', '')}:{snapshot.get('sequence_number', '')}"


def initialize(connection):
    initialize_schema(connection)
    for table, column in (('runs', 'session_id'), ('readings', 'snapshot_id')):
        columns = {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}
        if column not in columns:
            connection.execute(f'ALTER TABLE {table} ADD COLUMN {column} TEXT')
    connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id)')
    connection.execute('CREATE INDEX IF NOT EXISTS idx_readings_snapshot ON readings(snapshot_id)')
    connection.commit()


class TelemetryDatabase:
    def __init__(self, path, source):
        self.writer = AsyncSQLiteWriter(path, initialize, name='database-A-writer')
        self.source = source
        self.session_id = uuid4().hex
        self.started = False
        self._last_snapshot = None
        self._processor_stop = Event()
        self._processor = None

    def start(self):
        if not self.started:
            self.started = self.writer.submit([Statement(
                'INSERT INTO runs (started_at,mode,source,session_id) VALUES (?,?,?,?)',
                ((time.time(), 'transport', self.source, self.session_id),))], critical=True)
        return self.started

    def snapshot(self, snapshot):
        if not snapshot or not self.start():
            return
        identity = snapshot_id(snapshot)
        if identity == self._last_snapshot:
            return
        rows = tuple((self.session_id, r.timestamp, r.logged_at, r.channel, r.raw_value,
                      r.engineering_value, r.units, r.source, r.quality, identity)
                     for r in snapshot_to_readings(snapshot, source=self.source))
        if self.writer.submit([Statement('''INSERT INTO readings
            (run_id,timestamp,logged_at,channel,raw_value,engineering_value,units,source,quality,snapshot_id)
            VALUES ((SELECT id FROM runs WHERE session_id=?),?,?,?,?,?,?,?,?,?)''', rows)]):
            self._last_snapshot = identity

    def alarms(self, opened, cleared, timestamp):
        if not self.start():
            return False
        rows = tuple((self.session_id, a.timestamp if state == 'active' else timestamp,
                      a.code, a.channel, state, a.message)
                     for group, state in ((opened, 'active'), (cleared, 'cleared')) for a in group)
        return self.writer.submit([Statement('''INSERT INTO alarm_events
            (run_id,timestamp,alarm_name,channel,state,message)
            VALUES ((SELECT id FROM runs WHERE session_id=?),?,?,?,?,?)''', rows)], critical=True)

    def start_processor(self):
        if self._processor is None:
            self._processor = Thread(target=self._process, name='database-A-reader', daemon=True)
            self._processor.start()

    def _process(self):
        # Read-only connection; only the A writer commits the resulting averages.
        while not self._processor_stop.wait(1.0):
            connection = None
            try:
                connection = sqlite3.connect(self.writer.path.resolve().as_uri()+'?mode=ro',
                                             uri=True, timeout=0.1)
                now = time.time()
                rows = connection.execute('''SELECT r.run_id,r.channel,AVG(r.engineering_value),
                    MIN(r.units),MIN(r.timestamp),MAX(r.timestamp),MAX(r.id)
                    FROM readings r JOIN runs u ON u.id=r.run_id
                    WHERE r.timestamp>=? AND r.channel!='bitmask' AND r.quality='ok'
                    AND u.session_id=? GROUP BY r.run_id,r.channel''',
                    (now-5, self.session_id)).fetchall()
                if self._processor_stop.is_set():
                    return
                self.writer.submit([Statement('''INSERT INTO processed_metrics
                    (run_id,timestamp,metric_name,value,units,window_start,window_end,processor,source_reading_id)
                    VALUES (?,?,?,?,?,?,?,?,?)''', tuple((r[0], now, r[1]+'.rolling_average', r[2],
                    r[3], r[4], r[5], 'python-window-average', r[6]) for r in rows if r[2] is not None))])
            except sqlite3.Error:
                pass  # Startup or busy read: the next window retries; no control dependency.
            finally:
                if connection is not None:
                    connection.close()

    def stop(self):
        self._processor_stop.set()
        if self.started:
            self.writer.submit([Statement('UPDATE runs SET ended_at=? WHERE session_id=?',
                               ((time.time(), self.session_id),))], critical=True)
        self.writer.close()
