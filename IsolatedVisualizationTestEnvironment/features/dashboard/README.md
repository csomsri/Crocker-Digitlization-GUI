# All-section telemetry dashboard

Each update uses a single machine-state packet for eight panels: trim, extraction, extraction angles, source, transport, vacuum, RF power, and beam current. The built-in simulator uses the existing extended Smoke2 packet layout. Beam range is recorded as metadata when supplied. Older or partial packets leave unavailable panels labeled **no data**.

The default dashboard draws 49 bars across eight panels for a complete simulator packet. Each panel uses its first usable peak plus 25% headroom as a fixed display scale. Bars are normalized to that scale, with larger magnitudes clipped. This is a benchmark display of decoded readings. A shorter channel vector leaves the trailing bar positions blank at the default size. With `--bars`, multichannel panels repeat their available inputs to reach the requested stress size. RF and beam stay at one bar each.

Each CSV row represents one selected packet. It reports aggregate handler time, sums of individual panel preparation and rendering times, CUDA stage times, each panel's reading count and pixel dimensions, and counts of panels with data and reported paints. For a full-dashboard comparison, use runs with eight populated panels and check that every panel reported a paint. Paint times do not measure monitor presentation.
