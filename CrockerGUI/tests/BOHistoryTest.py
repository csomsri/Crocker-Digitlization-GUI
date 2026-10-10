"""BO history presentation and stable SQLite trial identity regressions."""
import csv
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QPushButton
from python.app.Automation.PidControlPage import PidControlPage
from python.app.Automation.PIDRecording import PagePIDRecorder
from source.Python.Data.pid_database import PIDDatabase
from source.Python.Optimization.pid_gain_adapter import PidGainCandidate, PidTrialResult


def result(number, score, safe=True):
    return PidTrialResult(PidGainCandidate(.8+number, 1.234567890123e-7, .1),
        score, 2, .1, .2, .3, safe,
        metrics=SimpleNamespace(settled=False, sustained_oscillation=True),
        trial_id=f'trial-{number}', started_at=1700000000+number,
        ended_at=1700000001+number, termination_reason='Completed' if safe else 'Invalid feedback')


class HistoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.page = PidControlPage(lambda:None, 'simulation')
        self.page.timer.stop()
        self.page.tuning_results = [result(1, 1), result(2, 2), result(3, 1e12, False)]
        self.page.tuning_optimizer = SimpleNamespace(
            rejected_validation_candidates={self.page.tuning_results[0].candidate})

    def tearDown(self):
        self.page.tuning_optimizer = None
        self.page.stop_backend()
        self.page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_faults_and_validation_rejections_do_not_hide_best_eligible_trial(self):
        p = self.page
        p._show_tuning_history()
        table = p.trial_history_table
        statuses = {int(table.item(row,0).data(Qt.DisplayRole)):table.item(row,9).text()
                    for row in range(table.rowCount())}
        self.assertEqual(statuses, {1:'Validation rejected', 2:'Best observed', 3:'Faulted'})
        self.assertEqual(table.item(0,13).text(), 'trial-3')
        self.assertIn('T', table.item(0,11).text())
        self.assertIn('Invalid feedback', table.item(0,9).toolTip())

    def test_new_results_keep_filter_sort_and_details_selection(self):
        p = self.page
        p._show_tuning_history()
        p.trial_history_first.setValue(1)
        p.trial_history_last.setValue(1)
        p.trial_history_details.setChecked(True)
        p.trial_history_table.sortItems(4, Qt.AscendingOrder)
        p.tuning_results.append(result(4, 3))
        p._populate_tuning_results()
        self.assertEqual(p.trial_history_last.value(), 1)
        self.assertTrue(p.trial_history_details.isChecked())
        self.assertFalse(p.trial_history_table.isColumnHidden(13))
        self.assertEqual(p.trial_history_table.item(0,4).data(Qt.DisplayRole), 1)

    def test_csv_keeps_small_gain_precision_trial_id_and_timestamps(self):
        p = self.page
        p._show_tuning_history()
        p.trial_history_first.setValue(2)
        p.trial_history_last.setValue(2)
        button = p.trial_history_export
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'trials.csv'
            with patch('python.app.Automation.PidControlPage.QFileDialog.getSaveFileName',
                       return_value=(str(path),'CSV (*.csv)')):
                button.click()
            with path.open(newline='',encoding='utf-8') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows),1)
            self.assertEqual(float(rows[0]['Ki']),p.tuning_results[1].candidate.ki)
            self.assertEqual(rows[0]['SQLite trial ID'],'trial-2')
            self.assertIn('T',rows[0]['Started (local)'])


class TrialIdentityTest(unittest.TestCase):
    def test_next_start_flushes_previous_result_without_stealing_next_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'pid.sqlite3'
            database = PIDDatabase(path)
            page = SimpleNamespace(tuning_results=[], backend_mode='simulation',
                beam_feedback=True, pid_enabled=False, tuning_session_active=False)
            recorder = PagePIDRecorder(page,database,SimpleNamespace(started=False),None)
            config = dict(kp=.8,ki=.1,kd=.1,setpoint=1,measurement_channel=0,dry_run=False)
            try:
                first = recorder.started(config)
                session = recorder.session
                database.sample(session,trial_id=first,timestamp=time.time(),kp=.8,
                                sample_kind='status_poll',controller_iteration=1)
                page.tuning_results.append(PidTrialResult(PidGainCandidate(.8,.1,.1),
                    1,1,0,.1,.2,True,trial_id=first,started_at=1,ended_at=2))
                second = recorder.started(dict(config,kp=.9))
                self.assertNotEqual(first,second)
                self.assertEqual(recorder.trial_id,second)
                database.sample(session,trial_id=second,timestamp=time.time(),kp=.9,
                                sample_kind='status_poll',controller_iteration=1)
                page.tuning_results.append(PidTrialResult(PidGainCandidate(.9,.1,.1),
                    .5,1,0,.1,.2,True,trial_id=second,started_at=3,ended_at=4))
                recorder.results()
                recorder.results()  # Polling must not duplicate a result.
                recorder.close()
            finally:
                database.writer.close()
                self.assertTrue(database.writer.done.wait(3))
            with closing(sqlite3.connect(path)) as connection:
                trials = connection.execute('SELECT id,result FROM pid_trials ORDER BY timestamp').fetchall()
                self.assertEqual([row[0] for row in trials],[first,second])
                self.assertEqual(json.loads(trials[0][1])['result']['trial_id'],first)
                linked = connection.execute('SELECT t.id,s.kp FROM pid_trials t '
                    'JOIN pid_samples s ON s.trial_id=t.id ORDER BY t.timestamp').fetchall()
                self.assertEqual(linked,[(first,.8),(second,.9)])


if __name__ == '__main__':
    unittest.main()
