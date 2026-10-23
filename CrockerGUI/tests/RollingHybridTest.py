"""Measured learning/inheritance and rolling-window regression tests; no hardware."""
import importlib.util
import json
import math
import os
from dataclasses import asdict, replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source.Python.Optimization.hybrid_pid_optimizer import HybridConfig, HybridPIDOptimizer, HybridState
from source.Python.Optimization.rolling_hybrid_optimizer import (
    RollingHybridConfig, RollingHybridPIDOptimizer, create_hybrid_optimizer)
from source.Python.Optimization.pid_gain_adapter import PidGainCandidate, PidTrialResult
from source.Python.Optimization.trial_metrics import evaluate_trial


BOUNDS = ((0., 1.),)*3
SEED = PidGainCandidate(.5, .5, .5)


def measured(candidate, score=10., safe=True):
    metrics = evaluate_trial([(0, .9, .1, 0, .5, 0), (1, .9, .1, 0, .5, 0)], 1)
    return PidTrialResult(candidate, score, 0, 0, .1, 0, safe, metrics=metrics)


def config(**changes):
    return replace(RollingHybridConfig(population=4, baseline_repeats=2,
        minimum_distinct=4, coverage=.01, window_size=8,
        reference_interval=100, exploration_interval=100, budget=40,
        refinement_probability=1), **changes)


def local_candidate(center):
    return PidGainCandidate(*(min(1, v+.02) for v in (center.kp, center.ki, center.kd)))


def ready_parent(optimizer):
    # After two baseline repeats and four parents, refinement is queued.
    for _ in range(6):
        candidate = optimizer.propose_batch(1)[0]
        optimizer.record_results([measured(candidate)])
    assert optimizer._parent is not None
    return optimizer._parent.candidate


class RollingPolicyTest(unittest.TestCase):
    def make(self, **changes):
        return RollingHybridPIDOptimizer(BOUNDS, SEED, config(**changes),
            proposer=lambda center: (local_candidate(center), 1., .01))

    def test_lamarckian_inherits_measured_refinement(self):
        o = self.make(learning_mode='lamarckian')
        parent = ready_parent(o)
        candidate = o.propose_batch(1)[0]
        self.assertNotEqual(candidate, parent)
        o.record_results([measured(candidate, 2)])
        selected = o.ga.history[-1]
        self.assertEqual(asdict(selected.gains), asdict(candidate))
        self.assertEqual(selected.fitness, 2)
        self.assertEqual(o.state, HybridState.GA)
        self.assertEqual(o.best_result.candidate, candidate)

    def test_baldwinian_keeps_genotype_and_trains_at_measured_phenotype(self):
        o = self.make(learning_mode='baldwinian')
        parent = ready_parent(o)
        refined = o.propose_batch(1)[0]
        o.record_results([measured(refined, 2)])
        self.assertEqual(asdict(o.ga.history[-1].gains), asdict(parent))
        self.assertEqual(o.ga.history[-1].fitness, 2)
        self.assertEqual(o.optimizer.safe_observations[-1].candidate.values,
                         o._from_pid_candidate(refined).values)
        parent_scores = [r.score for r in o.safe_results if r.candidate == parent]
        self.assertEqual(parent_scores, [10])
        self.assertEqual(o.best_result.candidate, refined)
        self.assertEqual(o.records[-1]['selection']['phenotype'], asdict(refined))
        json.dumps(o.records, allow_nan=False)

    def test_mixed_probability_endpoints_control_inheritance(self):
        for probability, mode in [(0, 'baldwinian'), (1, 'lamarckian')]:
            o = self.make(learning_mode='mixed', lamarckian_probability=probability)
            parent = ready_parent(o)
            candidate = o.propose_batch(1)[0]
            o.record_results([measured(candidate, 2)])
            self.assertEqual(o.records[-1]['selection']['mode'], mode)
            expected = candidate if probability else parent
            self.assertEqual(asdict(o.ga.history[-1].gains), asdict(expected))

    def test_recent_window_keeps_repeats_and_full_archive(self):
        o = self.make(window_size=4, refinement_probability=0)
        for i in range(12):
            c = o.propose_batch(1)[0]
            o.record_results([measured(c, i+1)])
        self.assertEqual(len(o.results), 12)
        self.assertEqual(len(o.optimizer.observations), 12)
        self.assertEqual([r.score for r in o.recent_results], [9, 10, 11, 12])
        self.assertEqual([r.score for r in o.optimizer.safe_observations], [9, 10, 11, 12])
        self.assertEqual(o.best_result.score, 9)
        self.assertEqual(o.optimizer.best_observation.score, 9)
        o = self.make(window_size=4)
        for _ in range(2):
            c = o.propose_batch(1)[0]
            o.record_results([measured(c)])
        self.assertEqual(len(o.optimizer.safe_observations), 2)
        self.assertEqual(o.optimizer.safe_observations[0].candidate,
                         o.optimizer.safe_observations[1].candidate)

    def test_readiness_is_lost_when_diverse_points_age_out(self):
        o = self.make(window_size=4)
        ready_parent(o)
        self.assertTrue(o.readiness()[0])
        # Inject completed repeated measurements into the archive to isolate
        # window readiness from the experiment scheduler.
        from source.Python.Optimization.pid_gain_adapter import BotorchPidOptimizer
        BotorchPidOptimizer.record_results(o, [measured(SEED)]*4)
        ready, distinct, coverage = o.readiness()
        self.assertFalse(ready)
        self.assertEqual((distinct, coverage), (1, 0))

    def test_reference_and_exploration_still_use_the_same_window(self):
        o = self.make(window_size=8, refinement_probability=0,
                      reference_interval=4, exploration_interval=3)
        sources = []
        for _ in range(14):
            c = o.propose_batch(1)[0]
            sources.append(o.pending_source)
            o.record_results([measured(c)])
        self.assertIn('Reference', sources)
        self.assertIn('Exploration', sources)
        self.assertEqual(len(o.optimizer.safe_observations), 8)
        self.assertEqual(len(o.results), 14)
        self.assertEqual(len(o.ga.history), sources.count('GA parent'))

    def test_reference_drift_still_stops_windowed_search(self):
        o = self.make(refinement_probability=0, reference_interval=4)
        for _ in range(8):
            c = o.propose_batch(1)[0]
            o.record_results([measured(c, 30 if o.pending_source == 'Reference' else 10)])
        self.assertTrue(o.reference_drift_detected)
        self.assertIsNone(o.best_result)
        self.assertEqual(o.state, HybridState.STOPPED)

    def test_mixed_schedule_is_reproducible(self):
        def run():
            o = self.make(learning_mode='mixed')
            for _ in range(20):
                c = o.propose_batch(1)[0]
                score = 2 if o.pending_source == 'BO refinement' else 10
                o.record_results([measured(c, score)])
            return [(r.get('selection'), r.get('learning_mode')) for r in o.records]
        self.assertEqual(run(), run())

    def test_fault_kept_in_audit_excluded_from_window_and_stops(self):
        o = self.make()
        ready_parent(o)
        candidate = o.propose_batch(1)[0]
        before = len(o.ga.history)
        o.record_results([measured(candidate, 1e12, False)])
        self.assertEqual(o.state, HybridState.STOPPED)
        self.assertEqual(len(o.optimizer.safe_observations), 6)
        self.assertEqual(len(o.optimizer.observations), 7)
        self.assertEqual(len(o.ga.history), before)
        with self.assertRaises(RuntimeError):
            o.propose_batch(1)

    def test_worse_measured_refinement_cannot_improve_selection(self):
        o = self.make()
        parent = ready_parent(o)
        c = o.propose_batch(1)[0]
        o.record_results([measured(c, 20)])
        self.assertFalse(o.records[-1]['learning_improved'])
        self.assertEqual(o.ga.history[-1].fitness, 10)
        self.assertEqual(asdict(o.ga.history[-1].gains), asdict(parent))
        self.assertEqual(o.optimizer.safe_observations[-1].score, 20)

    def test_budget_counts_refinement_and_never_leaves_partial_selection(self):
        for budget in [6, 7]:
            o = self.make(budget=budget, refinement_trials=3)
            for _ in range(budget):
                c = o.propose_batch(1)[0]
                o.record_results([measured(c, 2 if o.pending_source == 'BO refinement' else 10)])
            self.assertIsNone(o._parent)
            self.assertEqual(len(o.ga.history), 4)
            with self.assertRaises(RuntimeError):
                o.propose_batch(1)

    def test_multistep_learning_spends_each_trial_and_refits_at_new_center(self):
        o = self.make(refinement_trials=2)
        ready_parent(o)
        a = o.propose_batch(1)[0]
        o.record_results([measured(a, 4)])
        self.assertIsNotNone(o._parent)
        b = o.propose_batch(1)[0]
        self.assertEqual(b, local_candidate(a))
        o.record_results([measured(b, 2)])
        self.assertIsNone(o._parent)
        self.assertEqual(o.ga.history[-1].fitness, 2)
        self.assertEqual(len(o.results), 8)

    def test_prediction_rejection_finishes_parent_without_physical_refinement(self):
        o = self.make()
        ready_parent(o)
        o._local_proposer = lambda c: (local_candidate(c), 20, 1)
        c = o.propose_batch(1)[0]
        self.assertEqual(len(o.results), 6)
        self.assertEqual(o.pending_source, 'GA parent')
        self.assertEqual(len(o.ga.history), 4)
        o.record_results([measured(c)])

    def test_invalid_local_proposal_and_outstanding_result_are_rejected(self):
        o = self.make()
        ready_parent(o)
        o._local_proposer = lambda c: (PidGainCandidate(0, 0, 0), 1, .01)
        with self.assertRaises(ValueError):
            o.propose_batch(1)
        o._local_proposer = lambda c: (local_candidate(c), math.nan, .01)
        with self.assertRaises(ValueError):
            o.propose_batch(1)
        o._local_proposer = lambda c: (local_candidate(c), 1, .01)
        c = o.propose_batch(1)[0]
        with self.assertRaises(ValueError):
            o.propose_batch(1)
        with self.assertRaises(ValueError):
            o.record_results([measured(SEED)])
        self.assertEqual(o.pending, c)

    def test_all_ga_survivors_are_remeasured_each_generation(self):
        o = self.make(refinement_probability=0)
        for _ in range(10):
            c = o.propose_batch(1)[0]
            o.record_results([measured(c)])
        self.assertEqual([r.generation for r in o.ga.history], [0]*4+[1]*4)
        self.assertEqual(o.ga.generation, 2)

    def test_legacy_factory_preserves_existing_optimizer_and_defaults(self):
        o = create_hybrid_optimizer(BOUNDS, SEED, window_size=4, local_radius=.5)
        self.assertIs(type(o), HybridPIDOptimizer)
        self.assertEqual(o.config, HybridConfig())
        for mode in ['lamarckian', 'baldwinian', 'mixed']:
            o = create_hybrid_optimizer(BOUNDS, SEED, approach=mode, window_size=20)
            self.assertEqual(o.config.learning_mode, mode)
            self.assertEqual(o.config.window_size, 20)

    def test_invalid_configuration(self):
        for changes in [dict(window_size=3), dict(window_size=4.5),
                        dict(local_radius=0), dict(refinement_probability=2),
                        dict(lamarckian_probability=-1), dict(refinement_trials=0),
                        dict(uncertainty_multiplier=math.inf), dict(mc_samples=0),
                        dict(learning_mode='unknown')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                config(**changes).validate()

    def test_model_plumbing_uses_only_window_and_configured_acquisition_settings(self):
        from unittest.mock import patch
        import source.Python.Optimization.rolling_hybrid_optimizer as module

        class Tensor(list):
            @property
            def T(self):
                return Tensor([list(row) for row in zip(*self)])

            def contiguous(self):
                return self

        class Torch:
            double = 'double'

            @staticmethod
            def tensor(values, **options):
                return Tensor(values)

        o = self.make(window_size=4, mc_samples=32, num_restarts=3, raw_samples=16)
        parent = ready_parent(o)
        o.optimizer._torch = Torch()
        refined = local_candidate(parent)
        with patch.object(o.optimizer, '_require_botorch'), \
             patch.object(module, 'fit_single_task_gp', return_value=object()) as fit, \
             patch.object(module, 'propose_expected_improvement_batch',
                          return_value=[[refined.kp, refined.ki, refined.kd]]) as acquire, \
             patch.object(module, 'predict_posterior_mean_variance', return_value=([-2], [.04])):
            candidate, mu, sigma = o._local_model_proposal(parent)
        self.assertEqual(candidate, refined)
        self.assertEqual((mu, sigma), (2, .2))
        self.assertEqual(len(fit.call_args.kwargs['train_x']), 4)
        self.assertEqual(fit.call_args.kwargs['train_y'], [[-10]]*4)
        args = acquire.call_args.kwargs
        self.assertEqual((args['mc_samples'], args['num_restarts'], args['raw_samples']), (32, 3, 16))
        self.assertEqual(args['bounds'], [list(row) for row in zip(*o._local_bounds(parent))])

    @unittest.skipUnless(importlib.util.find_spec('botorch'), 'BoTorch is not installed')
    def test_real_gp_uses_window_and_proposes_inside_local_bounds(self):
        o = self.make(window_size=4)
        parent = ready_parent(o)
        candidate, mu, sigma = o._local_model_proposal(parent)
        self.assertTrue(all(lo <= getattr(candidate, n) <= hi
            for n, (lo, hi) in zip(('kp', 'ki', 'kd'), o._local_bounds(parent))))
        self.assertTrue(math.isfinite(mu) and math.isfinite(sigma) and sigma >= 0)
        self.assertEqual(len(o.optimizer.safe_observations), 4)

        # Verify the actual fit receives only W rows and the acquisition gets
        # the configured radius, even when the audit archive is larger.
        from unittest.mock import patch
        import source.Python.Optimization.rolling_hybrid_optimizer as module
        with patch.object(module, 'fit_single_task_gp', wraps=module.fit_single_task_gp) as fit:
            o._local_model_proposal(parent)
        self.assertEqual(fit.call_args.kwargs['train_x'].shape[0], 4)


@unittest.skipUnless(importlib.util.find_spec('PySide6') and importlib.util.find_spec('CycloViz'),
                     'GUI/native dependencies are not installed')
class RollingSettingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_switch_legacy_and_all_learning_modes_and_lock(self):
        from python.app.Automation.HybridPIDPage import HybridPIDPage
        p = HybridPIDPage(lambda: None, 'simulation')
        p.timer.stop()
        try:
            self.assertEqual(p._field_values()['approach'], 'legacy')
            self.assertFalse(p.hybrid_fields['window_size'].isEnabled())
            for mode in ['lamarckian', 'baldwinian', 'mixed', 'legacy']:
                p.hybrid_approach.setCurrentIndex(p.hybrid_approach.findData(mode))
                p.hybrid_fields['window_size'].setValue(24)
                settings = p._field_values()
                o = create_hybrid_optimizer(BOUNDS, SEED, **settings, budget=48)
                self.assertEqual(hasattr(o.config, 'window_size'), mode != 'legacy')
                if mode != 'legacy':
                    self.assertEqual(o.config.window_size, 24)
                    self.assertEqual(o.config.learning_mode, mode)
                self.assertEqual(p.hybrid_fields['lamarckian_probability'].isEnabled(), mode == 'mixed')
            p.hybrid_approach.setCurrentIndex(3)
            before = p._fingerprint()
            p.hybrid_fields['window_size'].setValue(25)
            self.assertNotEqual(p._fingerprint(), before)
            p._lock_controller_inputs(True)
            self.assertFalse(p.hybrid_approach.isEnabled())
            self.assertTrue(all(not w.isEnabled() for w in p.hybrid_fields.values()))
            p._lock_controller_inputs(False)
            self.assertTrue(p.hybrid_approach.isEnabled())
            self.assertTrue(p.hybrid_fields['window_size'].isEnabled())
        finally:
            p.stop_backend()
            p.deleteLater()


if __name__ == '__main__':
    unittest.main()
