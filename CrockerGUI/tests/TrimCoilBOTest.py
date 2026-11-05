"""Reference validation and direct-coil session acceptance tests; no devices needed."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from source.Python.Automation.reference_store import ReferenceStore
from source.Python.Automation.trim_coil_bo import TrimCoilConfig, TrimCoilSession
from source.Python.Automation.trim_coil_simulator import CoupledCoilSimulator, simulation_reference
from source.Python.Optimization.parameter_space import OptimizationCandidate, ParameterSpace
from source.Python.Optimization.observations import ObservationHistory


class FixedOptimizer:
    def __init__(self, parameters, point):
        self.space = ParameterSpace(parameters)
        self.parameters = self.space.parameters
        self.parameter_names = self.space.names
        self.history = ObservationHistory(self.space)
        self.observations = self.history.observations
        self.point = point

    def propose_batch(self, count):
        assert count == 1
        return [OptimizationCandidate(dict(self.point))]

    def record_observations(self, observations):
        self.history.record(observations)


def record():
    return {'schema_version': 1, 'record_type': 'measured_reference',
            'reference_id': 'test', 'captured_at': '2026-01-01T00:00:00+00:00',
            'operator': 'test', 'source_dataset': 'synthetic',
            'machine_configuration': {'species': 'synthetic'},
            'coils': [{'channel': 'TC1', 'unit': 'A', 'target': 0, 'readback': 0}],
            'beam': {'diagnostic': 'output', 'unit': 'nA', 'mean': 10,
                     'stddev': .1, 'window_s': 1, 'sample_count': 3}}


class ReferenceTests(unittest.TestCase):
    def test_explicit_id_and_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'test.json').write_text(json.dumps(record()))
            store = ReferenceStore(directory)
            self.assertEqual(store.list_ids(), ['test'])
            loaded = store.load('test', expected_configuration={'species': 'synthetic'})
            self.assertEqual(loaded.recovery_reference({'TC1': 0}).targets_a, ((0, 0.),))
            with self.assertRaises(ValueError):
                store.load('test', expected_configuration={'species': 'alpha'})
            with self.assertRaises(ValueError):
                store.load('../test', expected_configuration={})

    def test_invalid_records(self):
        invalid = []
        for key, value in [('schema_version', 2), ('record_type', 'historical extraction'),
                           ('captured_at', '2026-01-01'), ('machine_configuration', {})]:
            data = record(); data[key] = value; invalid.append(data)
        for key, value in [('unit', 'uA'), ('mean', float('nan')), ('sample_count', 1), ('window_s', 0)]:
            data = record(); data['beam'][key] = value; invalid.append(data)
        data = record(); data['coils'].append(copy.deepcopy(data['coils'][0])); invalid.append(data)
        data = record(); data['coils'][0]['unit'] = 'unknown'; invalid.append(data)
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                ReferenceStore.validate(data)

    def test_default_directory_is_absolute(self):
        self.assertEqual(ReferenceStore().directory, Path(__file__).resolve().parents[2] / 'reference_values')

    def test_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'test.json').write_text('{"schema_version":1,"schema_version":2}')
            with self.assertRaises(ValueError):
                ReferenceStore(directory).load('test', expected_configuration={})


class SessionTests(unittest.TestCase):
    def make_session(self, point=None, **settings):
        self.now = 0.
        reference = simulation_reference()
        parameters = [('TC1', (-.5, .5)), ('TC2', (-.5, .5))]
        backend = CoupledCoilSimulator(reference, dict(parameters), noise_nA=0)
        optimizer = FixedOptimizer(parameters, point or {'TC1': .15, 'TC2': .15})
        config = TrimCoilConfig(trial_budget=2, stable_hold_s=.2, measurement_window_s=.4, **settings)
        session = TrimCoilSession(backend=backend, reference=reference,
                                 parameters=parameters, optimizer=optimizer, config=config)
        return session, backend

    def advance(self, session, until=None):
        for _ in range(2000):
            if session.state in session.TERMINAL or (until and until()):
                return
            self.now = round(self.now + .1, 8)
            session.poll(self.now)
        self.fail('Session did not terminate')

    def test_improvement_confirmed_and_reference_restored(self):
        session, backend = self.make_session()
        session.start(0)
        self.advance(session)
        self.assertEqual(session.state, 'completed', session.reason)
        self.assertGreater(session.incumbent_mean, 10)
        self.assertEqual(session.incumbent, {'TC1': .15, 'TC2': .15})
        self.assertEqual(backend.targets, session.reference.targets_a)
        self.assertIsNone(backend.owner)
        self.assertTrue(any(e.get('promoted') for e in session.audit))
        self.assertTrue(all(o.score < 0 for o in session.optimizer.observations))

    def test_worse_measurements_retained_without_promotion(self):
        session, backend = self.make_session({'TC1': -.2, 'TC2': -.2})
        session.start(0); self.advance(session)
        self.assertEqual(session.state, 'completed', session.reason)
        self.assertEqual(session.incumbent, session.reference_point)
        self.assertEqual(len(session.optimizer.observations), len(session.windows))

    def test_abort_recovers_and_does_not_restart(self):
        session, backend = self.make_session()
        session.start(0)
        self.advance(session, lambda: session.current_kind == 'candidate')
        session.abort(); self.advance(session)
        self.assertEqual(session.state, 'stopped', session.reason)
        self.assertEqual(backend.targets, session.reference.targets_a)
        count = len(backend.command_history)
        session.poll(self.now + 1)
        self.assertEqual(len(backend.command_history), count)

    def test_stale_telemetry_blocks_recovery(self):
        session, backend = self.make_session()
        session.start(0); backend.fault = 'stale'; self.advance(session)
        self.assertEqual(session.state, 'blocked')
        self.assertFalse(session.windows)
        self.assertIsNone(backend.owner)

    def test_partial_write_recovers(self):
        session, backend = self.make_session()
        backend.fault = 'partial_write'
        session.start(0); self.advance(session)
        self.assertEqual(session.state, 'stopped', session.reason)
        self.assertFalse(session.windows)

    def test_interlock_never_bypassed(self):
        session, backend = self.make_session()
        session.start(0); backend.fault = 'interlock'; self.advance(session)
        self.assertEqual(session.state, 'blocked')
        self.assertEqual(len(backend.command_history), 1)

    def test_invalid_candidate_rejected_before_write(self):
        session, backend = self.make_session({'TC1': 99, 'TC2': 0})
        session.start(0); self.advance(session)
        self.assertEqual(session.state, 'stopped')
        self.assertTrue(all(v == session.reference.targets_a for v in backend.command_history))

    def test_exclusive_ownership(self):
        session, backend = self.make_session()
        backend.acquire(object())
        with self.assertRaises(ValueError): session.start(0)
        self.assertFalse(backend.command_history)

    def test_configuration_change_stops(self):
        session, backend = self.make_session()
        original = backend.snapshot
        from dataclasses import replace
        backend.snapshot = lambda now: replace(original(now), configuration={'species': 'other'})
        session.start(0); self.advance(session)
        self.assertEqual(session.state, 'blocked')

    def test_beam_loss_never_trained(self):
        session, backend = self.make_session()
        session.start(0); backend.fault = 'beam_loss'; self.advance(session)
        self.assertEqual(session.state, 'blocked')
        self.assertFalse(session.optimizer.observations)

    def test_hardware_backend_rejected(self):
        session, backend = self.make_session()
        backend.mode = 'hardware'
        with self.assertRaises(ValueError):
            TrimCoilSession(backend=backend, reference=session.reference,
                parameters=session.space.parameters, optimizer=session.optimizer, config=session.config)

    def test_time_budget_stops_and_restores(self):
        session, backend = self.make_session(time_budget_s=.5)
        session.start(0); self.advance(session)
        self.assertEqual(session.state, 'stopped', session.reason)
        self.assertEqual(backend.targets, session.reference.targets_a)

    def test_abort_during_model_fit_never_applies_candidate(self):
        session, backend = self.make_session()
        def propose(count):
            session.request_abort()
            return [OptimizationCandidate({'TC1': .15, 'TC2': .15})]
        session.optimizer.propose_batch = propose
        session.start(0); self.advance(session)
        self.assertEqual(session.state, 'stopped', session.reason)
        self.assertTrue(all(p == session.reference.targets_a for p in backend.command_history))

    def test_settling_timeout_recovers(self):
        session, backend = self.make_session()
        session.start(0)
        self.advance(session, lambda: session.current_kind == 'candidate')
        backend.fault = 'settling'
        self.advance(session)
        self.assertEqual(session.state, 'stopped', session.reason)
        self.assertIn('timeout', session.reason)

    def test_invalid_diagnostic_not_trained(self):
        session, backend = self.make_session()
        session.start(0); backend.fault = 'invalid_diagnostic'; self.advance(session)
        self.assertEqual(session.state, 'blocked')
        self.assertFalse(session.optimizer.observations)

    def test_held_packets_do_not_establish_stability(self):
        session, backend = self.make_session()
        original = backend.snapshot
        held = original(0)
        backend.snapshot = lambda now: held
        session.start(0); self.advance(session)
        self.assertEqual(session.state, 'blocked')
        self.assertFalse(session.windows)

    def test_nonfinite_config_rejected(self):
        with self.assertRaises(ValueError):
            self.make_session(time_budget_s=float('nan'))


class NoisyOptimizerTests(unittest.TestCase):
    def test_noise_aware_proposal_and_distinct_initialization(self):
        import torch
        torch.set_num_threads(1)
        from source.Python.Optimization.trim_coil_optimizer import TrimCoilBayesianOptimizer
        from source.Python.Optimization.observations import OptimizationObservation
        optimizer = TrimCoilBayesianOptimizer([('TC1', (-1, 1))], use_cuda=False,
            initial_safe_trials=3, mc_samples=16, num_restarts=2, raw_samples=16)
        for _ in range(3):
            optimizer.record_observations([OptimizationObservation(OptimizationCandidate({'TC1': 0}), -10,
                metadata={'mean_variance_nA2': .001})])
        first = optimizer.propose_batch(1)[0]
        self.assertNotEqual(first.values['TC1'], 0)
        for value in (-.5, .5):
            optimizer.record_observations([OptimizationObservation(OptimizationCandidate({'TC1': value}),
                -(10 + value - value * value), metadata={'mean_variance_nA2': .001})])
        proposal = optimizer.propose_batch(1)[0]
        self.assertTrue(-1 <= proposal.values['TC1'] <= 1)
        with self.assertRaises(ValueError): optimizer.propose_batch(2)


if __name__ == '__main__':
    unittest.main()
