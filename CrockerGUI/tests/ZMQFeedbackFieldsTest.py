"""Verify extended decoder fields survive ControlService snapshots on localhost."""
import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import zmq
import CycloViz


def main():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        endpoint = f'tcp://127.0.0.1:{probe.getsockname()[1]}'
    service = CycloViz.ControlService()
    service.StartServer(endpoint)
    context = zmq.Context()
    peer = context.socket(zmq.REQ)
    peer.setsockopt(zmq.RCVTIMEO, 2000)
    peer.setsockopt(zmq.LINGER, 0)
    peer.connect(endpoint)

    def exchange(middle, mask=0):
        previous = service.LatestSnapshot()['sequence_number']
        values = [time.time(), *range(14), *middle, float(mask)]
        peer.send(struct.pack(f'<{len(values)}d', *values))
        peer.recv()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            snap = service.LatestSnapshot()
            if snap['sequence_number'] > previous:
                return snap
            time.sleep(.01)
        raise AssertionError('No snapshot update')

    try:
        for source_count in (12, 18):
            for vacuum_first in (False, True):
                src = list(range(100, 100 + source_count))
                transport = list(range(200, 210))
                vacuum_rf_beam = [301., 302., 303., 304., 305., 306., .0879]
                tail = (vacuum_rf_beam + [2.] + transport if vacuum_first
                        else transport + vacuum_rf_beam + [2.])
                snap = exchange(src + tail, 123)
                assert snap['extraction'] == src[:6], snap
                assert snap['extraction_angles'] == (src[6:12] if source_count == 18 else []), snap
                assert snap['source'] == src[-6:], snap
                assert snap['transport'] == transport, snap
                assert snap['vacuum'] == vacuum_rf_beam[:5], snap
                assert snap['rf_power_kv'] == 306., snap
                assert snap['beam_current'] == .0879 and snap['beam_range_idx'] == 2, snap
                assert snap['bitmask'] == 123, snap
                assert snap['channels'][13]['raw'] == 13., snap
        snap = exchange([])
        assert snap['beam_current'] is None and snap['beam_range_idx'] is None, snap
        assert snap['vacuum'] == [] and snap['source'] == [] and snap['rf_power_kv'] is None, snap
        print('PASS: four extended layouts retain all fields; short packet clears old feedback')
    finally:
        peer.close()
        context.term()
        service.Stop()


if __name__ == '__main__':
    main()
