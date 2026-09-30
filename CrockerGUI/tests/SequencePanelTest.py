"""Exercise the real Field Control editor with a simulator, never hardware."""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox
from python.app.Controls.FieldCtrlPage import FieldCtrlPage
from python.app.theme import load_stylesheet


def main():
    app = QApplication.instance() or QApplication([])
    font_path = Path("C:/Windows/Fonts/segoeui.ttf")
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
    app.setStyleSheet(load_stylesheet("Segoe UI"))
    page = FieldCtrlPage(lambda: None, "simulation", snapshot_db_path=ROOT / "build" / "sequence-ui-test.db")
    page.resize(1100, 850)
    page.control_stack.setCurrentIndex(page.control_stack.count() - 1)
    page.show()
    for _ in range(10):
        app.processEvents()
    assert page.backend_available, "Test requires the built CycloViz simulator"
    assert page.sequence_table.horizontalHeaderItem(1).text() == "Hold after arrival (s)"
    page.sequence_table.setRowCount(0)
    page._add_sequence_step(targets={0: 20.0, 1: 30.0}, hold=5)
    page._add_sequence_step(targets={0: 10.0}, hold=0)
    page.sequence_table.selectRow(1)
    page._move_sequence_step(-1)
    assert page._sequence_steps_from_table()[0]["targets"] == {0: 10.0}
    page._move_sequence_step(1)
    assert page._sequence_steps_from_table()[0]["targets"] == {0: 20.0, 1: 30.0}

    # Edit simultaneous channel targets through the actual modal editor.
    def edit_dialog():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        checks = dialog.findChildren(QCheckBox)
        values = dialog.findChildren(QDoubleSpinBox)
        for check in checks:
            check.setChecked(False)
        save = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save)
        assert not save.isEnabled()
        checks[0].setChecked(True)
        checks[1].setChecked(True)
        values[0].setValue(20)
        values[1].setValue(30)
        assert save.isEnabled()
        save.click()
    QTimer.singleShot(0, edit_dialog)
    page._edit_sequence_targets(page.sequence_table.cellWidget(0, 0))
    assert page._sequence_steps_from_table()[0]["targets"] == {0: 20.0, 1: 30.0}
    page.sequence_stop_policy.setCurrentIndex(1)
    page._start_sequence()
    assert not page.sequence_table.isEnabled()
    assert page.sequence_stop_button.isEnabled()
    assert not page._apply_selected_command()
    assert "Stop the sequence" in page.backend_label.text()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        page._refresh_sequence_status()
        if page.backend.SequenceStatus()["state"] == "Dwelling":
            break
        time.sleep(0.02)
    assert page.backend.SequenceStatus()["state"] == "Dwelling", page.backend.SequenceStatus()
    assert "Holding" in page.sequence_status_label.text()
    if "--capture" in sys.argv:
        panel = page.control_stack.currentWidget()
        panel.grab().save(str(ROOT / "build" / "sequence-panel.png"))
    page._stop_sequence()
    assert page.backend.SequenceStatus()["state"] == "Stopped"
    assert page.sequence_table.isEnabled()
    assert not page.sequence_stop_button.isEnabled()
    command = page.backend.PendingCommand()
    assert not command[0]["enabled"] and not command[1]["on"]
    assert "Disable command sent" in page.sequence_status_label.text()
    page._sync_targets_from_running_sequence()
    assert not page.applied_enabled[0]
    page.backend.Stop()
    page.close()
    print("Sequence editor, multi-channel editing, ordering, simulator run and stop passed")


if __name__ == "__main__":
    main()
