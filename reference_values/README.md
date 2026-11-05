# Reference values

Measured, unit-verified machine reference records still need to be captured.

A reference value is a set of cyclotron operating values that we know produced
beam. Together, these settings describe a known beam-producing operating point
that we can look up and reuse as a starting point or recovery reference.

Keep shared reference records in this folder so future optimization, control,
and recovery features can use one consistent source. Historical alpha settings
have been extracted, but no measured beam objectives accompany those rows.
`source/Python/Automation/reference_store.py` now loads versioned measured records
by explicit ID and configuration. It rejects the historical extraction JSON.

For each reference, record:

- A unique reference ID, capture date/time, operator, and source dataset.
- Machine configuration (particle species, energy, and relevant RF, magnet,
  source, and other operating settings).
- Trim-coil channel names, commanded currents, measured currents, and units.
- Beam diagnostic name, measured beam current and units, measurement window,
  variability, and evidence that beam was present and stable.
- Applicable operating limits and notes about when this reference is valid.

A past beam-producing setting does not guarantee beam under a different machine
configuration. Verify the configuration and live measurements before reuse.
Preserve original captures; store improved operating points as new references.

See [the direct trim-coil optimization plan](../CrockerGUI/MISO_TRIM_COIL_BO_PLAN.md)
for the algorithm, and [implementation usage](../CrockerGUI/MISO_TRIM_COIL_BO_USAGE.md)
for the simulation workspace and measured-reference record format.
