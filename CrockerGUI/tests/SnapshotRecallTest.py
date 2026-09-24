"""Run: python CrockerGUI/tests/SnapshotRecallTest.py (no hardware required)."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for directory in ("Debug", "Release", "build/Debug", "build/Release"):
    sys.path.insert(0, str(ROOT / directory))

from PySide6.QtWidgets import QApplication, QWidget
from python.app.Controls.SnapshotStore import SnapshotStore, make_snapshot, target_updates
from python.app.Controls.SnapshotDialogs import CaptureDialog, RecallDialog
from python.app.Controls.FieldCtrlPage import FieldCtrlPage
from python.app.widgets.MagneticFieldWidgets import CHANNEL_NAMES


class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name) / "snapshots.db")
        self.telemetry = dict(channels=[dict(actual=100.0 + i, raw=i, on=True, enabled=False)
                                       for i in range(14)],
                              source=[1, 2], extraction=[3], extraction_angles=[4],
                              vacuum=[1e-6], transport=[5], rf_power_kv=6,
                              beam_current=7, beam_range_idx=2, timestamp=123456,
                              sequence_number=20, connection="Connected", simulated=True,
                              unknown_future_field={"value": 123}, signals={"sensor": 8})
        self.record = make_snapshot(self.telemetry, CHANNEL_NAMES, "simulation")

    def test_round_trip_and_names(self):
        first = self.store.save(self.record)
        self.store.save(self.record)
        self.assertEqual(self.store.load(first)["name"], "Snapshot1")
        self.assertEqual(self.store.next_name(), "Snapshot3")
        self.assertEqual(self.store.load(first)["telemetry"], self.telemetry)
        with self.assertRaises(ValueError):
            self.store.save(self.record, "Snapshot1")
        self.assertEqual(len(self.store.list()), 2)
        self.assertEqual(SnapshotStore(self.store.path).load(first)["categories"]["Source"], {"source": [1, 2]})

    def test_missing_and_invalid_values(self):
        record = make_snapshot(dict(channels=[dict(actual=float("nan"))]), CHANNEL_NAMES, "zmq")
        self.assertIsNone(record["categories"]["Trim Coils"]["TC1"])
        self.assertIsNone(record["categories"]["Beam"]["beam_current"])
        self.store.save(record)
        with self.assertRaises(ValueError):
            target_updates(record, ["Trim Coils"], CHANNEL_NAMES, 1000)
        self.record["categories"]["Trim Coils"]["TC12"] = 1001
        with self.assertRaises(ValueError):
            target_updates(self.record, ["Trim Coils"], CHANNEL_NAMES, 1000)

    def test_recall_stages_only_selected_targets(self):
        page = FieldCtrlPage(lambda: None, backend_mode="simulation")
        page.timer.stop()
        try:
            record = self.store.load(self.store.save(self.record))
            actual = list(page.actual_values)
            applied = list(page.applied_targets)
            targets = list(page.target_values)
            toggles = [(on.isChecked(), en.isChecked()) for on, en in zip(page.on_buttons, page.enable_buttons)]
            class ReadOnlyBackend:
                def SequenceStatus(self):
                    return {"state": "Idle"}
                def __getattr__(self, name):
                    raise AssertionError(f"Recall must not call backend {name}")
            original_backend = page.backend
            page.backend = ReadOnlyBackend()
            try:
                page._stage_snapshot(record, {"Trim Coils": record["categories"]["Trim Coils"],
                                              "Vacuum": record["categories"]["Vacuum"]})
                self.assertEqual(page.target_values[:12], [100 + i for i in range(12)])
                self.assertEqual(page.target_values[12:], targets[12:])
                self.assertEqual(page.actual_values, actual)
                self.assertEqual(page.applied_targets, applied)
                self.assertEqual([(on.isChecked(), en.isChecked()) for on, en in zip(page.on_buttons, page.enable_buttons)], toggles)
                self.assertEqual(page.recalled_reference_tree.topLevelItem(0).text(0), "Vacuum")
                before = list(page.target_values)
                invalid = copy.deepcopy(record)
                invalid["categories"]["Trim Coils"]["TC12"] = -1
                with self.assertRaises(ValueError):
                    page._stage_snapshot(invalid, ["Trim Coils"])
                self.assertEqual(page.target_values, before)
            finally:
                page.backend = original_backend
        finally:
            page.close()
            page.deleteLater()

    def test_dialog_filters_and_categories(self):
        self.store.save(self.record, "Morning")
        yesterday = dict(self.record, captured_at="2020-01-02T12:00:00+00:00")
        self.store.save(yesterday, "Old")
        owner = QWidget()
        calls = []
        dialog = RecallDialog(owner, self.store, lambda *args: calls.append(args))
        try:
            self.assertEqual(dialog.snapshots.count(), 2)
            self.assertEqual(list(dialog.selected_categories()), ["Trim Coils"])
            dialog.search.setText("Old")
            self.assertEqual(dialog.snapshots.count(), 1)
            dialog.checks["Trim Coils"].setChecked(False)
            dialog.checks["Source"].setChecked(True)
            dialog.apply_recall()
            self.assertEqual(set(calls[0][1]), {"Source"})
            dialog.search.setText("Missing")
            self.assertFalse(dialog.recall_button.isEnabled())
            dialog.search.clear()
            dialog.date.setCurrentIndex(2)
            self.assertEqual(dialog.snapshots.count(), 1)
        finally:
            dialog.deleteLater()
            owner.deleteLater()


if __name__ == "__main__":
    unittest.main()
