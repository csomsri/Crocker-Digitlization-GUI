# LabVIEW feedback mapping

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
