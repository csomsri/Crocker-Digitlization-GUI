# -*- coding: utf-8 -*-
"""
Created on Tue Jul 22 23:00:02 2025

@author: clasa
"""

import zmq
import struct
import time

ADDRESS = "tcp://127.0.0.1:5555"  # Same as your LabVIEW
NUM_CHANNELS = 14
EPOCH_OFFSET = 2082844800

context = zmq.Context()
socket = context.socket(zmq.REQ)
socket.connect(ADDRESS)

# Dummy values to test
target_values = [300.0] * 14
on_off = [1] * 14
enable_ctrl = [1] * 14

bitmask = sum([(on_off[i] << i) | (enable_ctrl[i] << (14 + i)) for i in range(NUM_CHANNELS)])

timestamp = time.time() + EPOCH_OFFSET
packet = struct.pack("<16d", timestamp, *target_values, float(bitmask))

print("🎯 Sending to LabVIEW...")
socket.send(packet)
reply = socket.recv()
print("✅ LabVIEW responded:", reply.decode())
