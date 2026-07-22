from __future__ import annotations

import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path("data") / "crocker_pipeline.sqlite3"


def connect_database(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    initialize_schema(connection)
    return connection


def initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at REAL NOT NULL,
            ended_at REAL,
            mode TEXT NOT NULL,
            source TEXT NOT NULL,
            operator TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            timestamp REAL NOT NULL,
            logged_at REAL NOT NULL,
            channel TEXT NOT NULL,
            raw_value REAL,
            engineering_value REAL,
            units TEXT,
            source TEXT NOT NULL,
            quality TEXT NOT NULL DEFAULT 'ok',
            FOREIGN KEY (run_id) REFERENCES runs(id)
        );

        CREATE INDEX IF NOT EXISTS idx_readings_run_channel_time
            ON readings (run_id, channel, timestamp);

        CREATE TABLE IF NOT EXISTS processed_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            timestamp REAL NOT NULL,
            metric_name TEXT NOT NULL,
            value REAL NOT NULL,
            units TEXT,
            window_start REAL,
            window_end REAL,
            processor TEXT NOT NULL,
            source_reading_id INTEGER,
            FOREIGN KEY (run_id) REFERENCES runs(id),
            FOREIGN KEY (source_reading_id) REFERENCES readings(id)
        );

        CREATE INDEX IF NOT EXISTS idx_processed_metrics_run_name_time
            ON processed_metrics (run_id, metric_name, timestamp);

        CREATE TABLE IF NOT EXISTS alarm_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            timestamp REAL NOT NULL,
            alarm_name TEXT NOT NULL,
            channel TEXT,
            state TEXT NOT NULL,
            measured_value REAL,
            threshold_value REAL,
            message TEXT,
            FOREIGN KEY (run_id) REFERENCES runs(id)
        );

        CREATE TABLE IF NOT EXISTS processing_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            created_at REAL NOT NULL,
            started_at REAL,
            finished_at REAL,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL,
            details TEXT,
            FOREIGN KEY (run_id) REFERENCES runs(id)
        );

        CREATE TABLE IF NOT EXISTS operator_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            timestamp REAL NOT NULL,
            author TEXT,
            note TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(id)
        );
        """
    )
    connection.commit()


def start_run(
    connection: sqlite3.Connection,
    *,
    started_at: float,
    mode: str,
    source: str,
    operator: str | None = None,
    notes: str | None = None,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO runs (started_at, mode, source, operator, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (started_at, mode, source, operator, notes),
    )
    connection.commit()
    return int(cursor.lastrowid)


def finish_run(connection: sqlite3.Connection, run_id: int, ended_at: float) -> None:
    connection.execute(
        "UPDATE runs SET ended_at = ? WHERE id = ?",
        (ended_at, run_id),
    )
    connection.commit()
