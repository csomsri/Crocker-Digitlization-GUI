"""End-to-end local LabVIEW-format packets -> receiver -> monitoring pages."""
import os
from pathlib import Path
import socket
import struct
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for directory in ("Debug", "Release", "build/Debug", "build/Release"):
    sys.path.insert(0, str(ROOT / directory))

import CycloViz
import zmq
from PySide6.QtWidgets import QApplication
from python.app.Monitoring.BeamSourceExtractionPage import BeamSourceExtractionPage
from python.app.Monitoring.BeamTransportMonitoringPage import BeamTransportMonitoringPage
from python.app.Monitoring.VacuumBeamMonitoringPage import VacuumBeamMonitoringPage
from python.app.Monitoring.RfPowerMonitoringPage import RfPowerMonitoringPage
from python.app.Monitoring.TelemetryFields import reading


class LiveMonitoringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_packet_to_pages(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            endpoint = f"tcp://127.0.0.1:{probe.getsockname()[1]}"
        service = CycloViz.ControlService()
        service.StartServer(endpoint)
        context = zmq.Context()
        peer = context.socket(zmq.REQ)
        peer.setsockopt(zmq.RCVTIMEO, 2000)
        peer.setsockopt(zmq.LINGER, 0)
        peer.connect(endpoint)
        pages = [builder(lambda: None) for builder in (BeamSourceExtractionPage,
                 BeamTransportMonitoringPage, VacuumBeamMonitoringPage, RfPowerMonitoringPage)]
        for page in pages:
            page.timer.stop()
            page.set_snapshot_source(service.LatestSnapshot)

        def exchange(middle, stamp=None, channels=14):
            previous = service.LatestSnapshot()["sequence_number"]
            values = [time.time() if stamp is None else stamp, *range(channels), *middle, 0.]
            peer.send(struct.pack(f"<{len(values)}d", *values))
            peer.recv()
            deadline = time.monotonic() + 2
            while service.LatestSnapshot()["sequence_number"] <= previous:
                if time.monotonic() > deadline:
                    self.fail("Receiver did not publish a packet")
                time.sleep(.01)
            for page in pages:
                page.refresh()

        try:
            full = [*range(100, 118), *range(200, 210), *range(300, 305), 25., .0879, 2.]
            exchange(full)
            source, transport, vacuum, rf = pages
            self.assertEqual(source.latest["Source 1"][0], 112.)
            self.assertEqual(source.latest["Extraction 1"][0], 100.)
            self.assertEqual(source.latest["Extraction angle 6"][0], 111.)
            self.assertEqual(transport.latest["Transport 10"][0], 209.)
            self.assertEqual(vacuum.latest["Vacuum 5"][0], 304.)
            self.assertEqual(vacuum.latest["Beam detector"][0], .0879)
            self.assertEqual(rf.latest["RF reading"][0], 25.)
            self.assertEqual(rf.latest["RF reading"][2], "Live")
            rf.refresh()
            self.assertEqual(len(rf.history["RF reading"]), 1, "Do not duplicate a packet on every UI tick")
            rf.toggle_pause()
            exchange([])
            self.assertEqual(rf.latest["RF reading"][0], 25.)
            self.assertIsNone(source.latest["Source 1"][0])
            rf.toggle_pause()
            self.assertIsNone(rf.latest["RF reading"][0])
            self.assertIsNone(rf.history["RF reading"][-1][1], "Missing packets break the trend")
            exchange(full, time.time() - 5)
            self.assertEqual(rf.latest["RF reading"][2], "Stale")
            self.assertEqual(len(rf.history["RF reading"]), 1, "A timestamp reset starts a new trend")
            short_source = [*range(100, 112), *range(200, 210), *range(300, 305), 25., .0879, 2.]
            exchange(short_source)
            self.assertEqual(source.latest["Source 1"][0], 106.)
            self.assertIsNone(source.latest["Extraction angle 1"][0])
            exchange([], channels=12)
            self.assertIsNone(source.latest["Source 1"][0])
            rf.set_snapshot_source(lambda: None)
            rf.refresh()
            self.assertIsNone(rf.latest["RF reading"][0])
            self.assertIn("Waiting", rf.status.text())
        finally:
            for page in pages:
                page.close()
                page.deleteLater()
            peer.close()
            context.term()
            service.Stop()

    def test_invalid_values_and_beam_quality(self):
        for value in (None, float("nan"), float("inf"), "bad"):
            self.assertIsNone(reading({"vacuum": [value]}, ("Vacuum 1", "vacuum", 0, "raw")))
        spec = ("Beam current", "beam", "display_ua", "µA")
        self.assertIsNone(reading({"beam": {"quality": "ok", "display_ua": 7}}, spec))
        self.assertEqual(reading({"beam_current": .1, "beam": {"quality": "ok", "display_ua": 7}}, spec), 7)


if __name__ == "__main__":
    unittest.main()
