# Controls Network Layer

Low-level ZeroMQ/LabVIEW communication lives here.

There will be a sender and server continuously receiveing and sending messages
```cpp
ZMQServer server("tcp://0.0.0.0:5555");
ZMQSender sender("tcp://*:5566");

server.Start();
sender.Bind();
```

## Terminal packet diagnostics

Rebuild CycloViz after changing C++ sources. From the repository root in
PowerShell, enable logging before launching the GUI:

```powershell
$env:CROCKER_ZMQ_PACKET_LOG = "1"
py -3.13 .\CrockerGUI\main.py -ZMQ
# Disable for subsequent launches:
Remove-Item Env:CROCKER_ZMQ_PACKET_LOG
```

Logging is off by default. Each actual REP receive and reply prints its endpoint,
exchange number, local Unix time, byte count, and full wire-order doubles at
round-trip precision. RX includes the inferred channel count and the monotonic
gap since the preceding request. TX includes elapsed time since receiving that
request; it means the socket accepted the reply, not that LabVIEW applied it.
TX_TIMEOUT identifies a send that timed out. Malformed non-double frames print
as hex. RX values begin with the sender timestamp, followed by channels and
optional telemetry, with the bitmask last. TX contains raw targets and the
bitmask last, without a timestamp. See PACKET_FIELDS.md for channel order.

Use short diagnostic captures: synchronous terminal output can itself delay
the request/reply loop. Compare timing with logging disabled afterward.

## Investigating actuator jitter

- Compare consecutive TX target values and bitmasks with RX feedback. Stable TX
  with moving RX points toward the LabVIEW/local control loop, readback noise,
  scaling, or hardware; changing TX points toward GUI command generation or
  competing writers. This distinction requires a capture from the affected run.
- Before the first operator command, ZMQServer echoes the received measurements
  as reply targets, with GUI enable bits cleared. LabVIEW must honor those enable
  bits; applying disabled targets would feed measurement noise back as commands.
- Replies use the latest stored command before the received measurement is
  queued for the control service. A PID update based on that measurement therefore
  reaches a later request. Check RX gaps and timestamps against controller rate
  and plant response before changing gains.
- Confirm both sides agree on 12 versus 14 channels, native double byte order,
  bitmask positions, raw units, and engineering-to-raw calibration. Replies omit
  the request timestamp. Confirm only the intended controller owns each actuator.
- If TX oscillates only with PID enabled, inspect gains, measurement noise,
  actuator saturation and slew limits. The C++ trial adds its allocated PID output
  to the previous command each fresh sample; zero maximum slew delegates ramping
  to LabVIEW. Do not assume conventional absolute-output PID gains apply unchanged.
