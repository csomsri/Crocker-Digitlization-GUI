"""Automatic trial budgets, stop, and fault handling on the simulator only."""
import time
from PidControlPageTest import QApplication, PidControlPage


app = QApplication.instance() or QApplication([])
page = PidControlPage(lambda: None, backend_mode="simulation")


def wait_until(predicate, seconds=40):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert predicate(), page.tuner_status.text()


try:
    page.tuner_trials.setValue(3)
    page.tuner_duration.setValue(0.5)
    page.tuner_target.setValue(10)
    page.auto_tuning_button.click()
    assert page.tuning_auto_run and not page.tuner_trials.isEnabled()
    wait_until(lambda: not page.tuning_session_active)
    assert len(page.tuning_results) == 3
    assert not page.pid_enabled and not page.apply_tuned_gains_button.isEnabled()
    assert page.tuner_trials.isEnabled() and page.auto_tuning_button.isEnabled()

    page.auto_tuning_button.click()
    page.stop_tuning_button.click()
    wait_until(lambda: page.tuning_proposal is None)
    assert not page.tuning_auto_run and page.tuning_trial_candidate is None

    backend = page.backend

    class FaultingTrialBackend:
        def __getattr__(self, name):
            return getattr(backend, name)

        def StartPidTrial(self, config):
            config["max_absolute_error"] = 0.000001
            backend.StartPidTrial(config)

    page.backend = FaultingTrialBackend()
    page.tuner_target.setValue(100)
    page.auto_tuning_button.click()
    wait_until(lambda: not page.tuning_session_active)
    assert len(page.tuning_results) == 1 and not page.tuning_results[0].safe
    assert not page.tuning_auto_run
    print("Automatic N-trial budget, operator stop, and fault-stop tests passed")
finally:
    page.stop_backend()
