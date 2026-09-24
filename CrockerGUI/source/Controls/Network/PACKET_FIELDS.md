# LabVIEW feedback mapping

## Live monitoring setup

Run the GUI with its ZMQ backend and the configured receiver endpoint (normally
`tcp://0.0.0.0:5555`). LabVIEW connects its existing REQ peer to the GUI machine's
address and sends a binary array of doubles, then receives the reply before
sending the next packet. Monitoring pages share this receiver; they never bind
another socket or send control commands themselves. Existing reply/control
behavior is unchanged.

The tested full transport-first packet has 14 control readings: TC1–TC12,
main magnet and centering magnet. Follow the index table below, with either
12 or 18 source/extraction values, and the bitmask last. Timestamp handling
continues to support the receiver's existing LabVIEW/Unix normalization.
Do not remove the two auxiliary magnet slots from a full extended packet:
some 12-control-channel extended lengths overlap with 14-channel layouts and
the current decoder prioritizes the latter. Confirm the sender layout before
using physical device labels or interpreting extended hardware readings.

Source/Extraction, Beam Transport, Vacuum/Beam, and RF monitoring now show the
decoded fields directly. Missing/non-finite fields show Unavailable; data older
than two seconds or on a non-connected transport shows Stale. Each screen has
a selected-reading trend (up to 1200 UI samples at 4 Hz), Pause/Resume and a CSV
export of displayed readings. Raw extension fields have numbered labels until
facility channel names and calibrations are supplied. The calibrated beam row
uses the existing beam calibration service; the raw detector remains visible.
Field Ctrl plot toggles use the same names as these live pages.

Local integration checks (no LabVIEW/hardware required):

```
python CrockerGUI/tests/ZMQFeedbackFieldsTest.py
python CrockerGUI/tests/LiveMonitoringTest.py
```

The experiment reference `ExperimentFiles/PID_Paper_Adaptive_Direction_Update/MagneticFieldControllerWindow.py`
reads `beam_current` (raw detector voltage) and `beam_range_idx`, separately from
`channels`. It does not include the original receiver, so it establishes the
named-field contract, not the facility's exact wire order.

The current C++ decoder supports the following zero-based double indices for
the 14-control-channel, transport-first layout:

| Field | 12-value source/extraction | 18-value source/extraction |
| --- | --- | --- |
| Timestamp | 0 | 0 |
| TC1–TC12 | 1–12 | 1–12 |
| Main magnet / centering magnet | 13 / 14 | 13 / 14 |
| Extraction | 15–20 | 15–20 |
| Extraction angles | absent | 21–26 |
| Source | 21–26 | 27–32 |
| Transport | 27–36 | 33–42 |
| Vacuum | 37–41 | 43–47 |
| RF raw | 42 | 48 |
| Beam detector raw | 43 | 49 |
| Optional zero-based range | 44 | 50 |
| Bitmask | final double | final double |

There is also legacy support for vacuum/RF/beam/range before transport. Both
orders can have the same length; range-index validity rejects some incorrect
interpretations, but cannot disambiguate every packet. Transport-first retains
priority when both fit. Confirm the actual LabVIEW order before hardware use.
Packets with 12 control channels shift extension offsets two places earlier.

ControlService snapshots now preserve all decoded groups and the original
bitmask. They replace missing fields with None/empty lists on every packet.
Beam calibration uses only the dedicated detector field (or legacy aliases),
never the centering magnet. Explicit packet range takes priority, matching the
experiment; otherwise the configured manual/digital selection applies.

The shipped signal map no longer labels TC1–TC9 as source/vacuum/RF/beam data.
Extended readings remain raw; per-device units/calibration and the positions
within each source/extraction/transport group need the original receiver or
the LabVIEW schema. Existing beam curve coefficients have not been changed.

Smoke2's default short packets do not contain a detector measurement and now
correctly produce invalid beam feedback. The ZMQ beam integration test supplies
a dedicated simulated detector field to exercise the full control loop.
