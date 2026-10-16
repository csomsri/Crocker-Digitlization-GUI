"""Readable date migration, adjacency, insert/update and null regressions."""
from datetime import datetime
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source.Python.Data.pid_database import initialize
from source.Python.Data.pipeline_schema import initialize_schema


class ReadableTimestampTest(unittest.TestCase):
    def test_existing_pid_data_and_future_inserts_updates(self):
        with sqlite3.connect(':memory:') as c:
            c.execute('CREATE TABLE pid_events (id INTEGER PRIMARY KEY, session_id TEXT, timestamp REAL, event TEXT, details TEXT)')
            stamp = 1791675497.27222
            c.execute("INSERT INTO pid_events VALUES (1,'test',?,'stop','{}')", (stamp,))
            initialize(c)
            expected = datetime.fromtimestamp(stamp).strftime('%m/%d/%Y %I:%M:%S %p').replace(' 0', ' ')
            self.assertEqual(c.execute('SELECT timestamp,timestamp_local FROM pid_events').fetchone(), (stamp, expected))
            names = [r[0] for r in c.execute('SELECT * FROM pid_events_readable').description]
            self.assertEqual(names[names.index('timestamp') + 1], 'timestamp_local')
            c.execute("INSERT INTO pid_events(session_id,timestamp,event) VALUES ('test',?,'start')", (stamp,))
            self.assertEqual(c.execute('SELECT timestamp_local FROM pid_events WHERE id=2').fetchone()[0], expected)
            c.execute('UPDATE pid_events SET timestamp=NULL WHERE id=2')
            self.assertIsNone(c.execute('SELECT timestamp_local FROM pid_events WHERE id=2').fetchone()[0])
            initialize(c)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM pid_events').fetchone()[0], 2)

    def test_telemetry_and_session_end_dates(self):
        with sqlite3.connect(':memory:') as c:
            initialize_schema(c)
            c.execute("INSERT INTO runs(started_at,mode,source) VALUES (1792032605,'test','simulation')")
            self.assertIsNotNone(c.execute('SELECT started_at_local FROM runs').fetchone()[0])
            self.assertIsNone(c.execute('SELECT ended_at_local FROM runs').fetchone()[0])
            c.execute('UPDATE runs SET ended_at=1792032606')
            self.assertIsNotNone(c.execute('SELECT ended_at_local FROM runs').fetchone()[0])


if __name__ == '__main__':
    unittest.main()
