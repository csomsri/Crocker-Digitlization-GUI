"""Contract checks for telemetry sampling, provenance and visualization units."""
import sqlite3
import json
from contextlib import closing
from pathlib import Path
import tempfile
import unittest

from parse_cyclotron import read_cyclotron, beam_converter, LEGACY_COILS


class ParserTest(unittest.TestCase):
    def test_calibration_and_filter_before_sampling(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'cal.json'
            config.write_text(json.dumps({'ranges': [{'curve': [[0, 0], [1, 10]]}]}))
            convert = beam_converter(config)
            self.assertEqual(convert(.5, 0), 5)
            self.assertIsNone(convert(2, 0))
            self.assertIsNone(convert(.5, 2))
            path = Path(folder) / 'beam.db'
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute('CREATE TABLE channel_data (timestamp REAL, ts_mode TEXT, '
                             'main_magnet REAL, beam_current REAL, beam_range_idx INTEGER, ' +
                             ', '.join(f'ch{i} REAL' for i in range(1, 12)) + ')')
                for stamp, raw in enumerate([-1, 0, .1, .5, .8, 1, 2]):
                    conn.execute('INSERT INTO channel_data VALUES (' + ','.join('?' * 16) + ')',
                                 [stamp, 'labview_s', 12, raw, 0, *range(1, 12)])
            rows = list(read_cyclotron(path, beam_calibration=config, beam_only=True,
                                       min_beam_na=0, max_points=2))
            self.assertEqual([r['source_row'] for r in rows], [3, 6])
            self.assertEqual([r['output_beam_nA'] for r in rows], [1, 10])
            self.assertEqual(rows[0]['beam_current'], .1)
            band = list(read_cyclotron(path, beam_calibration=config, min_beam_na=1,
                                       max_beam_na=8, beam_range_index=0, max_points=0))
            self.assertEqual([r['output_beam_nA'] for r in band], [5, 8])
            with self.assertRaisesRegex(ValueError, 'Minimum beam'):
                list(read_cyclotron(path, beam_calibration=config, min_beam_na=8, max_beam_na=3))
            with self.assertRaisesRegex(ValueError, 'No channel_data'):
                list(read_cyclotron(path, beam_calibration=config, beam_range_index=1))
            with self.assertRaisesRegex(ValueError, 'No channel_data'):
                list(read_cyclotron(path, beam_calibration=config, min_beam_na=100))
            config.write_text(json.dumps({'ranges': [{'points': [[0, 0], [1, .01]]}]}))
            self.assertEqual(beam_converter(config)(.5, 0), 5)

    def test_time_order_sampling_mapping_and_units(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.db'
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute('CREATE TABLE channel_data (timestamp REAL, ts_mode TEXT, '
                             'main_magnet REAL, beam_current REAL, ' +
                             ', '.join(f'ch{i} REAL' for i in range(1, 12)) + ')')
                for stamp in (4, 1, 3, 0, 2):
                    conn.execute('INSERT INTO channel_data VALUES (' + ','.join('?' * 15) + ')',
                                 [stamp, 'labview_s', 12, -.5, *range(1, 12)])
            rows = list(read_cyclotron(path, max_points=3, beam_unit='uA'))
            self.assertEqual([r['timestamp'] for r in rows], [0, 2, 4])
            self.assertEqual([r['source_row'] for r in rows], [4, 5, 1])
            self.assertEqual(rows[0]['timestamp_utc'], '1904-01-01T00:00:00+00:00')
            self.assertEqual(rows[0]['output_beam_nA'], -500)
            self.assertEqual(rows[0]['Trim Coil 10'], 10)
            self.assertEqual(rows[0]['Trim Coil 8'], 11)
            self.assertEqual(rows[0]['ch8'], 8)
            self.assertEqual(list(read_cyclotron(path, coil_columns=LEGACY_COILS, max_points=1))[0]['Trim Coil 8'], 8)
            raw = list(read_cyclotron(path, max_points=0))
            self.assertEqual(len(raw), 5)
            self.assertIsNone(raw[0]['output_beam_nA'])
            self.assertEqual(raw[0]['beam_current'], -.5)
            with self.assertRaises(ValueError):
                list(read_cyclotron(path, coil_columns=['missing'] * 10))
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute("UPDATE channel_data SET ts_mode = 'unknown'")
            with self.assertRaisesRegex(ValueError, 'timestamp mode'):
                list(read_cyclotron(path))


if __name__ == '__main__':
    unittest.main()
