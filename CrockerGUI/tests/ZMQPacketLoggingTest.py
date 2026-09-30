"""Verify wire logs against local REQ/REP exchanges, without facility hardware."""
import os
from pathlib import Path
import struct
import subprocess
import sys
import time


def exchange():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import zmq
    import CycloViz

    service = CycloViz.ZMQServer("tcp://127.0.0.1:*")
    service.Start()
    context = zmq.Context()
    client = context.socket(zmq.REQ)
    client.setsockopt(zmq.RCVTIMEO, 3000)
    client.setsockopt(zmq.LINGER, 0)
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            endpoint = service.BoundEndpoint()
            if endpoint:
                break
            time.sleep(.02)
        client.connect(endpoint)
        for count in (12, 14):
            values = [time.time()] + [float(i + 1) for i in range(count)] + [0.]
            client.send(struct.pack(f"{len(values)}d", *values))
            reply = client.recv()
            assert struct.unpack(f"{count + 1}d", reply) == tuple(values[1:])
        client.send(b"bad")
        assert len(client.recv()) == 13 * 8
    finally:
        client.close()
        context.term()
        service.Stop()


if __name__ == "__main__":
    if "--worker" in sys.argv:
        exchange()
    else:
        for enabled in (False, True):
            env = dict(os.environ, CROCKER_ZMQ_PACKET_LOG="1" if enabled else "0")
            run = subprocess.run([sys.executable, __file__, "--worker"], env=env,
                                 capture_output=True, text=True, timeout=15)
            assert run.returncode == 0, run.stdout + run.stderr
            lines = [line for line in run.stdout.splitlines() if line.startswith("[ZMQ")]
            if not enabled:
                assert not lines, lines
                continue
            assert len(lines) == 6, lines
            for index in range(3):
                rx, tx = lines[2 * index:2 * index + 2]
                assert rx.startswith("[ZMQ RX]") and tx.startswith("[ZMQ TX]")
                assert f"exchange={index + 1} " in rx and f"exchange={index + 1} " in tx
                assert "reply_ms=" in tx
                if index:
                    assert "rx_gap_ms=" in rx
            assert "inferred_channels=12" in lines[0]
            assert "inferred_channels=14" in lines[2]
            assert "invalid_frame_hex=626164" in lines[4]
            assert "values=[1,2,3,4,5,6,7,8,9,10,11,12,0]" in lines[1]
        print("PASS: logging on/off, paired wire values, timing, 12/14 channels, malformed RX")
