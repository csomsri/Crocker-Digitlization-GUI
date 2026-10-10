"""October controller parity, control-direction and optimizer regressions."""
import importlib.util
import math
import sys
import unittest
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from source.Python.Control.NLAPID import NLAPID, PIDGains, PIDLimits, AdaptiveDirectionSettings
from source.Python.Control.FeedbackAverage import FeedbackAverage
from source.Python.Optimization.genetic_optimizer import GAPIDTuner, GainBounds, GATuningConfig

spec = importlib.util.spec_from_file_location("october_reference", ROOT / "ExperimentFiles/OctoberPID/pid_controller.py")
reference = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reference
spec.loader.exec_module(reference)


class OctoberControllerTest(unittest.TestCase):
    def test_ga_evolution_matches_october_source(self):
        from source.Python.Optimization import october_ga
        bounds = GainBounds((0, 1), (0, 1), (0, 1))
        ours = GAPIDTuner(bounds, GATuningConfig(6, 3, 123, .25, .12))
        original = october_ga.GAPIDTuner(october_ga.GainBounds(bounds.kp,bounds.ki,bounds.kd),
            october_ga.GATuningConfig(population_size=6,generations=3,random_seed=123))
        current = ours.initialize(PIDGains(.8,.1,.1))
        expected = original.initialize(PIDGains(.8,.1,.1))
        for i in range(18):
            self.assertEqual(current.gains, expected.gains)
            score = current.gains.kp + current.gains.ki + current.gains.kd
            current = ours.submit_fitness(score, valid=i%5 != 0)
            expected = original.submit_fitness(score, valid=i%5 != 0)
        self.assertIsNone(current)
        self.assertIsNone(expected)
        self.assertEqual(ours.best_candidate().gains, original.best_candidate().gains)

    def test_evaluation_matches_october_source_with_large_errors_and_motion(self):
        import types
        from source.Python.Automation.ga_evaluation import GACandidateEvaluator, GAEvaluationConfig
        source = (ROOT/'ExperimentFiles/OctoberPID/ga_test_runner.py').read_text(encoding='utf-8')
        source = source.replace('from pid_controller import PIDGains',
            'from source.Python.Control.NLAPID import PIDGains')
        module = types.ModuleType('october_evaluation_reference')
        sys.modules[module.__name__] = module
        exec(compile(source, str(ROOT/'ExperimentFiles/OctoberPID/ga_test_runner.py'), 'exec'), module.__dict__)
        config = dict(warmup_s=.2,evaluation_s=2,steady_state_window_s=.5)
        evaluators = [GACandidateEvaluator(GAEvaluationConfig(**config)),
                      module.GACandidateEvaluator(module.GAEvaluationConfig(**config))]
        for evaluator in evaluators:
            evaluator.start(candidate_number=1,generation_number=1,gains=PIDGains(.8,.1,.1),
                setpoint_nA=1,baseline_target_a=10,timestamp_s=100)
        for i in range(1,23):
            sample = dict(timestamp_s=100+i*.1, beam_nA=0 if i%2 else 100,
                tc_target_a=700 if i%2 else 0, tc_actual_a=500, pid_delta_a=100,
                saturated=True)
            results = [e.observe(**sample) for e in evaluators]
            self.assertEqual(results[0].phase.value, results[1].phase.value)
        final = [e.finish_if_due(timestamp_s=102.3) for e in evaluators]
        self.assertFalse(final[0].safety_violation)
        self.assertEqual(final[0].score, final[1].score)
        self.assertEqual(asdict(final[0].terms), asdict(final[1].terms))

    def test_october_reference_replay(self):
        for reset_integral in (False, True):
            settings = dict(deadband=.05, direction_each_update=True,
                            reset_integral_on_direction_change=reset_integral,
                            integral_memory_s=2.15)
            gains = dict(kp=.2, ki=.1, kd=.03)
            limits = dict(output_max=.2, integral_max=.03)
            engines = [NLAPID(PIDGains(**gains), PIDLimits(**limits), AdaptiveDirectionSettings(**settings)),
                       reference.AdaptiveDirectionPIDController(reference.PIDGains(**gains),
                           reference.PIDLimits(**limits), reference.AdaptiveDirectionSettings(**settings))]
            for i in range(700):
                if i == 350:
                    for engine in engines:
                        engine.reset(setpoint=10, measurement=8, direction=-1)
                target = 10 if i < 500 else 12
                value = target if i % 50 < 3 else 8 + 3*math.sin(i/40)
                dt = .8 if i % 79 == 0 else .3
                actual, expected = [asdict(e.update(target, value, dt, hold_integrator=i % 23 == 0)) for e in engines]
                self.assertEqual(actual.keys(), expected.keys())
                for key in actual:
                    if isinstance(actual[key], float):
                        self.assertAlmostEqual(actual[key], expected[key], places=11, msg=(i,key))
                    else:
                        self.assertEqual(actual[key], expected[key], (i,key))

    def test_wrong_direction_reverses_on_next_observation(self):
        for slope in (1, -1):
            engine = NLAPID(PIDGains(.2), settings=AdaptiveDirectionSettings(
                direction_each_update=True, direction_check_interval=60,
                initial_direction=-slope))
            engine.reset(setpoint=10, measurement=8)
            wrong = engine.update(10, 8, .3)
            measurement = 8 + slope*wrong.output
            corrected = engine.update(10, measurement, .3)
            self.assertTrue(corrected.direction_changed)
            self.assertEqual(corrected.direction, slope)
            self.assertGreater(slope*corrected.output, 0)

    def test_closed_loop_both_plant_directions(self):
        for slope in (1, -1):
            engine = NLAPID(PIDGains(.8), settings=AdaptiveDirectionSettings(
                direction_each_update=True, deadband=.02))
            measurement = 8
            for _ in range(100):
                result = engine.update(10, measurement, .3)
                measurement += slope*result.output
            self.assertLessEqual(abs(10-measurement), .02)

    def test_fresh_nonoverlapping_average(self):
        average = FeedbackAverage(.3)
        self.assertIsNone(average.add(1, 2))
        self.assertIsNone(average.add(1, 1000))
        self.assertIsNone(average.add(1.1, 4))
        self.assertEqual(average.add(1.4, 6), 4)
        self.assertIsNone(average.add(1.5, 8))
        self.assertEqual(average.add(1.8, 10), 9)
        with self.assertRaises(ValueError):
            average.add(1.7, 12)

    def test_invalid_ga_candidate_cannot_be_best(self):
        ga = GAPIDTuner(GainBounds((0,1),(0,1),(0,1)), GATuningConfig(seed=10))
        ga.initialize(PIDGains(.2,.1,0))
        ga.submit_fitness(0, valid=False)
        self.assertIsNone(ga.best_candidate())
        ga.submit_fitness(2)
        ga.submit_fitness(3)
        ga.submit_fitness(4)
        self.assertEqual(ga.best_candidate().fitness, 2)
        self.assertEqual(ga.generation, 1)

    def test_cpp_matches_october_mode(self):
        from source.Python.Control.CppPIDAdapter import CppPIDAdapter
        cpp = CppPIDAdapter()
        settings = AdaptiveDirectionSettings(direction_each_update=True, deadband=.05,
                                             reset_integral_on_direction_change=True)
        py = NLAPID(PIDGains(.2,.1,.03), settings=settings)
        cpp.set_gains(PIDGains(.2,.1,.03))
        cpp.set_settings(settings)
        for i in range(500):
            value = 8 + 3*math.sin(i/40)
            dt = .8 if i % 79 == 0 else .3
            expected, actual = asdict(py.update(10,value,dt)), asdict(cpp.update(10,value,dt))
            for key in expected:
                if isinstance(expected[key], float):
                    self.assertAlmostEqual(expected[key], actual[key], places=10, msg=(i,key))
                else:
                    self.assertEqual(expected[key], actual[key], (i,key))


class OctoberWorkerTest(unittest.TestCase):
    def test_october_worker_ignores_added_error_slew_and_output_gates(self):
        import time
        import CycloViz
        from CppNLAPIDIntegrationTest import config, wait_for
        from source.Python.Control.PythonNLATrial import PythonNLATrial
        for python_worker in (False, True):
            service = CycloViz.ControlService()
            service.StartSimulator(100)
            worker = PythonNLATrial(service) if python_worker else service
            try:
                settings = config(nla_direction_each_update=True, continuous=True,
                    dry_run=True, max_absolute_error=.0001, max_overshoot=.0001,
                    max_control_output=.0001, max_saturation_seconds=.0001,
                    maximum_slew_per_second=[.0001]*14)
                if python_worker:
                    worker.start(settings)
                    status = worker.status
                else:
                    service.StartPidTrial(settings)
                    status = service.PidTrialStatus
                wait_for(lambda:status()['iterations'] > 0)
                self.assertEqual(status()['state'], 'Running')
                self.assertGreater(abs(status()['command_target']), .001)
            finally:
                if python_worker:
                    worker.stop(False)
                service.Stop()

    def test_cpp_worker_waits_for_fresh_average(self):
        import time
        import CycloViz
        from CppNLAPIDIntegrationTest import config, wait_for
        service = CycloViz.ControlService()
        service.StartSimulator(100)
        try:
            service.SetPidBeamMeasurement(0, time.time(), True)
            service.StartPidTrial(config(external_beam_measurement=True, continuous=True,
                dry_run=True, feedback_average_seconds=.1, nla_direction_each_update=True))
            time.sleep(.04)
            service.SetPidBeamMeasurement(2, time.time(), True)
            time.sleep(.03)
            self.assertEqual(service.PidTrialStatus()['iterations'],0)
            time.sleep(.06)
            service.SetPidBeamMeasurement(4, time.time(), True)
            wait_for(lambda:service.PidTrialStatus()['iterations']==1)
            self.assertAlmostEqual(service.PidTrialStatus()['measured_field'],2)
            time.sleep(.03)
            self.assertEqual(service.PidTrialStatus()['iterations'],1)
        finally:
            service.Stop()


class OctoberBOTest(unittest.TestCase):
    def test_diagnostic_thresholds_do_not_change_fitness(self):
        from source.Python.Optimization.trial_metrics import TuningQuality, evaluate_trial, trial_cost
        rows = [(i*.1, 1+math.sin(i*.1*math.tau), -math.sin(i*.1*math.tau), 0, 50+i%2, 1)
                for i in range(201)]
        strict = evaluate_trial(rows, 1, quality=TuningQuality())
        loose = evaluate_trial(rows, 1, quality=TuningQuality(10, .1, 10, .1, 2))
        self.assertTrue(strict.sustained_oscillation)
        self.assertFalse(loose.sustained_oscillation)
        self.assertEqual(trial_cost(strict), trial_cost(loose))

    def test_initial_command_and_warmup_movement_are_scored(self):
        from source.Python.Optimization.trial_metrics import evaluate_trial, trial_cost
        rows = [(0,1,0,0,12,0), (1,1,0,0,15,0), (2,1,0,0,15,0)]
        metrics = evaluate_trial(rows, 1, baseline_target=10, warmup_seconds=1)
        self.assertAlmostEqual(trial_cost(metrics), .25*5/10)

    def test_oscillation_is_training_data_during_search(self):
        from source.Python.Optimization.trial_metrics import TuningQuality, evaluate_trial, trial_cost
        from source.Python.Optimization.pid_gain_adapter import BotorchPidOptimizer, PidGainCandidate, PidTrialResult
        rows = [(i*.1, 1+math.sin(i*.1*math.tau), -math.sin(i*.1*math.tau), 0, 50, 0)
                for i in range(201)]
        metrics = evaluate_trial(rows, 1, quality=TuningQuality())
        self.assertTrue(metrics.sustained_oscillation)
        result = PidTrialResult(PidGainCandidate(.2,.1,0),trial_cost(metrics),
                               metrics.settling_time,metrics.overshoot,metrics.steady_state_error,
                               metrics.control_effort,True,metrics=metrics)
        optimizer = BotorchPidOptimizer((0,1),(0,1),(0,1),use_cuda=False)
        optimizer.record_results([result])
        self.assertEqual(len(optimizer.optimizer.safe_observations),1)
        self.assertIs(optimizer.best_result, result)

    def test_search_and_validation_both_keep_oscillation_as_scored_data(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from unittest.mock import Mock, patch
        from types import SimpleNamespace
        from python.app.Automation.PidControlPage import PidControlPage
        from source.Python.Optimization.trial_metrics import TuningQuality
        for validating in (False, True):
            page = SimpleNamespace(
                _check_tuning_hold=lambda:True, tuning_proposal=None,
                tuning_surface_proposal=None, tuning_surrogate_proposal=None,
                tuning_trial_candidate=object(), backend=object(),
                _trial_status=lambda:dict(state='Running', elapsed_seconds=12,
                    measured_field=1, error=0, control_output=0, control_rate=0,
                    command_target=50,saturated=False,iterations=20),
                _tuning_controller_config=dict(controller_kind='nla',nla_deadband=.05),
                tuning_samples=[(i,1,0,0,50,0) for i in range(12)],
                _refresh_coil_response=Mock(), tuner_status=Mock(),
                _set_tuning_progress=Mock(),_validating_gains=validating,
                tuning_results=[],tuner_trials=Mock(),tuner_duration=SimpleNamespace(value=lambda:30),
                tuner_target=Mock(),_validation_seconds=lambda:60,
                _tuning_quality_settings=TuningQuality(), _oscillation_stopped=False,
                _complete_tuning_trial=Mock())
            with patch('python.app.Automation.PidControlPage.evaluate_trial',
                       return_value=SimpleNamespace(sustained_oscillation=True)) as evaluator:
                PidControlPage._poll_tuning_workflow(page)
            self.assertFalse(evaluator.called)
            self.assertFalse(page._complete_tuning_trial.called)
            self.assertFalse(page._oscillation_stopped)


if __name__ == "__main__":
    unittest.main()
