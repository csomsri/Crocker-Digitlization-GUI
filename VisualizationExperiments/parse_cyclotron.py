"""Read historical cyclotron SQLite telemetry without modifying the database."""
from __future__ import annotations

import argparse
from contextlib import closing
import csv
import bisect
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import sys

DEFAULT_DB = Path(__file__).resolve().parents[1] / 'CrockerGUI/data/DataFORViz/cyclotron_data/cyclotron_data.db'
DEFAULT_COILS = tuple('ch11' if i == 8 else f'ch{i}' for i in range(1, 11))
LEGACY_COILS = tuple(f'ch{i}' for i in range(1, 11))
FACTORS = {'nA': 1., 'uA': 1000., 'mA': 1e6, 'A': 1e9}


def beam_converter(calibration):
    """Accept legacy nA curves or current uA curves, without extrapolation."""
    data = json.loads(Path(calibration).read_text(encoding='utf-8-sig'))
    curves = []
    for entry in data['ranges']:
        legacy = 'curve' in entry
        points = entry.get('curve' if legacy else 'points', [])
        if entry.get('mode', 'curve') != 'curve' or len(points) < 2:
            raise ValueError('Beam calibration requires curves with at least two points')
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) * (1 if legacy else 1000) for p in points]
        if not all(math.isfinite(v) for v in xs + ys) or any(b <= a for a, b in zip(xs, xs[1:])):
            raise ValueError('Beam calibration curve must have finite, strictly increasing inputs')
        curves.append((xs, ys))

    def convert(raw, index):
        if raw is None or index is None:
            return None
        try:
            raw, index_float = float(raw), float(index)
            index = int(index_float)
            if not math.isfinite(raw) or index_float != index or not 0 <= index < len(curves):
                return None
            xs, ys = curves[index]
            if not xs[0] <= raw <= xs[-1]:
                return None
            i = min(max(bisect.bisect_right(xs, raw) - 1, 0), len(xs) - 2)
            return ys[i] + (raw - xs[i]) * (ys[i+1] - ys[i]) / (xs[i+1] - xs[i])
        except (ValueError, TypeError, OverflowError):
            return None
    return convert


def read_cyclotron(path=DEFAULT_DB, *, max_points=5000, coil_columns=DEFAULT_COILS,
                   beam_unit=None, beam_calibration=None, beam_only=False, min_beam_na=None,
                   max_beam_na=None, beam_range_index=None):
    """Yield time-ordered records, keeping original fields and adding viz aliases.

    max_points=0 retains every row. Otherwise select evenly spaced row positions
    (including both endpoints), not averages. Physical TC8 uses recorded ch11;
    other coils use ch1..ch7, ch9, ch10. Custom mappings remain supported.
    """
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f'Database does not exist: {path}')
    if max_points < 0:
        raise ValueError('max_points must be nonnegative')
    if len(coil_columns) != 10 or len(set(coil_columns)) != 10:
        raise ValueError('Supply ten distinct coil columns in TC1 through TC10 order')
    if beam_unit is not None and beam_unit not in FACTORS:
        raise ValueError('Unknown beam unit')
    if beam_unit and beam_calibration:
        raise ValueError('Choose either --beam-unit or --beam-calibration')
    if (beam_only or min_beam_na is not None or max_beam_na is not None) and not (beam_unit or beam_calibration):
        raise ValueError('Beam filtering needs --beam-calibration or confirmed --beam-unit')
    if min_beam_na is not None and not math.isfinite(min_beam_na):
        raise ValueError('Minimum beam must be finite')
    if max_beam_na is not None and not math.isfinite(max_beam_na):
        raise ValueError('Maximum beam must be finite')
    if min_beam_na is not None and max_beam_na is not None and min_beam_na >= max_beam_na:
        raise ValueError('Minimum beam must be less than maximum beam')
    if beam_range_index is not None and (beam_range_index < 0 or int(beam_range_index) != beam_range_index):
        raise ValueError('Beam range index must be a nonnegative integer')
    convert = beam_converter(beam_calibration) if beam_calibration else lambda raw, index: (
        float(raw) * FACTORS[beam_unit] if beam_unit and raw is not None and math.isfinite(float(raw)) else None)
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            columns = {r['name'] for r in conn.execute('PRAGMA table_info(channel_data)')}
            missing = set(coil_columns) | {'timestamp', 'ts_mode', 'main_magnet', 'beam_current'}
            if beam_calibration or beam_range_index is not None:
                missing.add('beam_range_idx')
            missing -= columns
            if missing:
                raise ValueError('Missing channel_data columns: ' + ', '.join(sorted(missing)))
            conn.create_function('beam_na', 2, convert, deterministic=True)
            range_expr = 'beam_range_idx' if 'beam_range_idx' in columns else 'NULL'
            beam_expr = f'beam_na(beam_current, {range_expr})'
            conditions, parameters = [], []
            if min_beam_na is not None:
                conditions.append(f'{beam_expr} > ?')
                parameters.append(min_beam_na)
            if max_beam_na is not None:
                conditions.append(f'{beam_expr} <= ?')
                parameters.append(max_beam_na)
            if beam_only:
                conditions.append(f'{beam_expr} IS NOT NULL')
            if beam_range_index is not None:
                conditions.append('beam_range_idx = ?')
                parameters.append(beam_range_index)
            where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
            count = conn.execute('SELECT count(*) FROM channel_data' + where, parameters).fetchone()[0]
            if not count:
                raise ValueError('No channel_data rows match the beam filter')
            print(f'{count} eligible database rows before sampling.', flush=True)
            size = min(count, max_points) if max_points else count
            positions = (None if size == count else
                         {round(i * (count - 1) / (size - 1)) for i in range(size)}
                         if size > 1 else {0})
            query = 'SELECT rowid AS source_row, * FROM channel_data' + where + ' ORDER BY timestamp, rowid'
            epoch = datetime(1904, 1, 1, tzinfo=timezone.utc)
            for index, row in enumerate(conn.execute(query, parameters)):
                if positions is not None and index not in positions:
                    continue
                record = dict(row)
                if record['ts_mode'] != 'labview_s':
                    raise ValueError(f'Unsupported timestamp mode: {record["ts_mode"]!r}')
                record['timestamp_utc'] = (epoch + timedelta(seconds=record['timestamp'])).isoformat()
                record['source_database'] = str(path)
                record['coil_mapping'] = ','.join(coil_columns)
                record['coil_mapping_mode'] = 'default' if tuple(coil_columns) == DEFAULT_COILS else 'custom'
                record['coil_units'] = 'recorded units; calibration unverified'
                record.update({f'Trim Coil {i}': record[col] for i, col in enumerate(coil_columns, 1)})
                record['Main Magnet'] = record['main_magnet']
                record['output_beam_nA'] = convert(record['beam_current'], record.get('beam_range_idx'))
                record['output_beam_status'] = 'measured' if record['output_beam_nA'] is not None else 'missing'
                record['output_beam_source_column'] = 'beam_current' if beam_unit or beam_calibration else 'units unverified'
                record['beam_calibration_file'] = str(Path(beam_calibration).resolve()) if beam_calibration else ''
                labels = []
                if min_beam_na is not None:
                    labels.append(f'beam > {min_beam_na:g} nA')
                if max_beam_na is not None:
                    labels.append(f'beam <= {max_beam_na:g} nA')
                if beam_range_index is not None:
                    labels.append(f'hardware range index {beam_range_index}')
                record['beam_filter'] = '; '.join(labels) or ('finite calibrated measurement' if beam_only else 'none')
                yield record
    except sqlite3.Error as exc:
        raise ValueError(f'Cannot read cyclotron database: {exc}') from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=DEFAULT_DB)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent / 'outputs/cyclotron/parsed.csv')
    parser.add_argument('--max-points', type=int, default=5000, help='Evenly spaced time-ordered rows; 0 exports all')
    parser.add_argument('--coil-columns', nargs=10, default=DEFAULT_COILS, help='Database channels in TC1..TC10 order')
    parser.add_argument('--beam-unit', choices=FACTORS, help='Confirmed unit of stored beam_current; no calibration is applied')
    parser.add_argument('--beam-calibration', type=Path, help='Range-dependent beam calibration JSON (raw detector to nA)')
    parser.add_argument('--beam-only', action='store_true', help='Keep finite beam measurements; filter before sampling')
    parser.add_argument('--min-beam-na', type=float, help='Keep beam strictly above this threshold in nA; does not establish beam-on quality')
    parser.add_argument('--max-beam-na', type=float, help='Keep beam at or below this upper bound in nA')
    parser.add_argument('--beam-range-index', type=int, help='Keep only this zero-based hardware detector range index')
    args = parser.parse_args(argv)
    try:
        if args.output.resolve() == args.data.resolve():
            raise ValueError('Output must differ from source database')
        rows = read_cyclotron(args.data, max_points=args.max_points,
                             coil_columns=args.coil_columns, beam_unit=args.beam_unit,
                             beam_calibration=args.beam_calibration, beam_only=args.beam_only,
                             min_beam_na=args.min_beam_na, max_beam_na=args.max_beam_na,
                             beam_range_index=args.beam_range_index)
        first = next(rows)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(first))
            writer.writeheader()
            writer.writerow(first)
            count = 1
            for row in rows:
                writer.writerow(row)
                count += 1
        print(f'Parsed {count} rows to {args.output.resolve()}')
        print('Coils use recorded values; mapping: ' + ', '.join(args.coil_columns))
        if not args.beam_unit and not args.beam_calibration:
            print('Beam units unverified: raw beam_current retained; visualization colors remain gray.')
        return 0
    except (ValueError, OSError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
