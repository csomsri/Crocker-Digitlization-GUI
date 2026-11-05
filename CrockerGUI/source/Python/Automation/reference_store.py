"""Versioned measured references; runsheet extracts are deliberately not executable."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .reference_recovery import RecoveryReference


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    return float(value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


@dataclass(frozen=True)
class MeasuredReference:
    reference_id: str
    machine_configuration: dict
    targets_a: dict[str, float]
    readbacks_a: dict[str, float]
    diagnostic: str
    beam_nA: float
    beam_stddev_nA: float
    sample_count: int
    window_s: float
    captured_at: str
    operator: str

    def recovery_reference(self, channel_indices: dict[str, int]) -> RecoveryReference:
        if set(channel_indices) != set(self.targets_a):
            raise ValueError('Recovery channel mapping must match reference channels')
        indices = list(channel_indices.values())
        if any(type(i) is not int or i < 0 for i in indices) or len(set(indices)) != len(indices):
            raise ValueError('Recovery channel indices must be distinct nonnegative integers')
        return RecoveryReference(
            tuple((channel_indices[k], v) for k, v in self.targets_a.items()),
            tuple((channel_indices[k], v) for k, v in self.readbacks_a.items()),
            self.beam_nA, datetime.fromisoformat(self.captured_at).timestamp())


class ReferenceStore:
    def __init__(self, directory: str | Path | None = None):
        # .../CrockerGUI/source/Python/Automation/reference_store.py -> repository root
        self.directory = Path(directory) if directory is not None else Path(__file__).resolve().parents[4] / 'reference_values'

    @staticmethod
    def validate(data: dict, expected_configuration: dict | None = None) -> MeasuredReference:
        if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 1:
            raise ValueError('Unsupported measured-reference schema')
        if data.get('record_type') != 'measured_reference':
            raise ValueError('A measured_reference record is required, not a runsheet extract')
        for key in ('reference_id', 'captured_at', 'operator', 'source_dataset'):
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise ValueError(f'Missing {key}')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', data['reference_id']):
            raise ValueError('Invalid reference ID')
        timestamp = datetime.fromisoformat(data['captured_at'])
        if timestamp.tzinfo is None:
            raise ValueError('Reference capture time needs a timezone')
        configuration = data.get('machine_configuration')
        if not isinstance(configuration, dict) or not configuration:
            raise ValueError('Machine configuration is required')
        # Reject NaN in nested configuration as well as in numerical measurements.
        json.dumps(configuration, allow_nan=False)
        if expected_configuration is not None and configuration != expected_configuration:
            raise ValueError('Incompatible machine configuration')
        coils = data.get('coils')
        if not isinstance(coils, list) or not coils:
            raise ValueError('Named coil measurements are required')
        targets, actuals = {}, {}
        for coil in coils:
            name = coil.get('channel') if isinstance(coil, dict) else None
            if not isinstance(name, str) or not re.fullmatch(r'TC(?:[1-9]|1[0-2])', name) or name in targets:
                raise ValueError('Unknown or duplicate trim-coil channel')
            if coil.get('unit') != 'A':
                raise ValueError('Coil units must be A')
            targets[name] = finite(coil.get('target'), name)
            actuals[name] = finite(coil.get('readback'), name)
        beam = data.get('beam', {})
        if not isinstance(beam, dict) or beam.get('unit') != 'nA' or not isinstance(beam.get('diagnostic'), str) or not beam['diagnostic'].strip():
            raise ValueError('Named beam diagnostic in nA is required')
        mean = finite(beam.get('mean'), 'beam mean')
        stddev = finite(beam.get('stddev'), 'beam variability')
        window = finite(beam.get('window_s'), 'beam window')
        count = beam.get('sample_count')
        if mean <= 0 or stddev < 0 or window <= 0 or type(count) is not int or count < 2:
            raise ValueError('Reference requires positive beam/window and measured variability')
        return MeasuredReference(data['reference_id'], dict(configuration), targets, actuals,
                                 beam['diagnostic'], mean, stddev, count, window,
                                 data['captured_at'], data['operator'])

    def list_ids(self) -> list[str]:
        """List validated records only; documentation and extraction JSON are ignored."""
        ids = []
        for path in sorted(self.directory.glob('*.json')):
            try:
                reference = self.validate(json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=_unique_object))
            except (ValueError, TypeError, KeyError):
                continue
            if reference.reference_id != path.stem:
                continue
            ids.append(reference.reference_id)
        return ids

    def load(self, reference_id: str, *, expected_configuration: dict) -> MeasuredReference:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', reference_id):
            raise ValueError('Invalid reference ID')
        data = json.loads((self.directory / f'{reference_id}.json').read_text(encoding='utf-8-sig'), object_pairs_hook=_unique_object)
        reference = self.validate(data, expected_configuration)
        if reference.reference_id != reference_id:
            raise ValueError('Reference ID does not match filename')
        return reference
