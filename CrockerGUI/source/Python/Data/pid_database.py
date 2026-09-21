"""Database B: sessions are created only by successful PID starts."""
import json
import math
import time
from dataclasses import asdict, is_dataclass
from uuid import uuid4

from source.Python.Data.async_writer import AsyncSQLiteWriter, Statement, insert


def plain(value):
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def json_text(value):
    return json.dumps(plain(value), allow_nan=False, default=str)


def initialize(connection):
    connection.executescript('''
        CREATE TABLE IF NOT EXISTS pid_sessions (
            id TEXT PRIMARY KEY, a_session_id TEXT, started_at REAL NOT NULL,
            ended_at REAL, page TEXT, engine TEXT, feedback_source TEXT,
            environment TEXT, configuration TEXT);
        CREATE TABLE IF NOT EXISTS pid_samples (
            id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, trial_id TEXT,
            timestamp REAL, snapshot_id TEXT, telemetry_timestamp REAL,
            beam_timestamp REAL, beam_quality TEXT, calibration_revision INTEGER,
            tc_channel INTEGER, tc_actual_a REAL, tc_command_a REAL,
            beam_na REAL, beam_target_na REAL, feedback REAL, target REAL,
            error REAL, feedback_unit TEXT, kp REAL, ki REAL, kd REAL,
            controller_output REAL, controller_state TEXT, search_mode TEXT,
            environment TEXT, enabled INTEGER, armed INTEGER, status TEXT,
            controller_iteration INTEGER, controller_elapsed REAL,
            sample_kind TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_pid_samples_session_time ON pid_samples(session_id,timestamp);
        CREATE TABLE IF NOT EXISTS pid_trials (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, timestamp REAL,
            source TEXT, result TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS pid_events (
            id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, timestamp REAL,
            event TEXT NOT NULL, details TEXT);
        CREATE INDEX IF NOT EXISTS idx_pid_events_session_time ON pid_events(session_id,timestamp);
    ''')


class PIDDatabase:
    def __init__(self, path):
        self.writer = AsyncSQLiteWriter(path, initialize, name='database-B-writer')

    def start(self, *, a_session_id=None, **config):
        session_id = uuid4().hex
        values = dict(id=session_id, a_session_id=a_session_id, started_at=time.time(), **config)
        values['configuration'] = json_text(values.get('configuration', {}))
        if not self.writer.submit([insert('pid_sessions', values),
                                   self.event_statement(session_id, 'start', {})], critical=True):
            return None
        return session_id

    def event_statement(self, session, event, details):
        return insert('pid_events', dict(session_id=session, timestamp=time.time(),
                                        event=event, details=json_text(details)))

    def event(self, session, event, details):
        return self.writer.submit([self.event_statement(session, event, details)], critical=True)

    def sample(self, session, **values):
        return self.writer.submit([insert('pid_samples', plain(dict(session_id=session, **values)))])

    def trial(self, session, trial_id, source, result):
        return self.writer.submit([insert('pid_trials', dict(id=trial_id, session_id=session,
            timestamp=time.time(), source=source, result=json_text(result)))], critical=True)

    def stop(self, session, reason):
        return self.writer.submit([self.event_statement(session, 'stop', dict(reason=reason)),
            Statement('UPDATE pid_sessions SET ended_at=? WHERE id=?', ((time.time(), session),))], critical=True)
