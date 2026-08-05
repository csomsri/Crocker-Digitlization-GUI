# Monitoring Page Plan

This README is the reminder board for the Monitoring page work. Start here before
adding the individual monitoring pages.

## Current Direction

The Monitoring page should work like a fighting-game character select screen:

- The right side shows selectable monitoring options.
- Arrow keys move the current selection.
- Enter opens the selected monitoring page.
- The small circle next to the selected option fills/highlights.
- The large circle on the left shows a preview or overview of the selected data
  visualization.
- The page should keep the dark spaceship HUD style used by the rest of the GUI.

## Monitoring Selector

Current selector options:

- Magnetic Field Monitoring
- Beam Transport Monitoring
- Beam Source & Extraction
- Vacuum / Beam Monitoring
- RF Power Monitoring

Expected controls:

- Up/Down: move selection.
- W/S: move selection.
- Enter/Space: open selected page.
- Mouse click: open clicked page.

## Visualization Preview Ideas

Each selected option should eventually draw a lightweight preview in the big
circle before the page is opened.

- Magnetic Field Monitoring: live B-field vector trace, current convergence,
  magnet temperature bands.
- Beam Transport Monitoring: beamline stability view, transport channel profile,
  quadrupole response map.
- Beam Source & Extraction: source current telemetry, extraction trend, ion
  source health.
- Vacuum / Beam Monitoring: pressure timeline, beam intensity overlay, interlock
  state.
- RF Power Monitoring: forward/reflected RF power, cavity phase response,
  amplifier status.

## Page Build Plan

Build one monitoring page at a time. Each page should have:

- A clear live visualization area.
- Compact status/metric panels.
- Backend connection state.
- A useful fallback when live data is not available.
- Controls only when they help monitoring; avoid clutter.

## Next Step

Start with the Monitoring selector and preview behavior. After that, implement
the first real monitoring detail page, likely Magnetic Field Monitoring, because
it already overlaps with the existing CycloViz/OpenGL work.
