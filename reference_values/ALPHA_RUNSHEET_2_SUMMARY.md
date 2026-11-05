# Alpha run sheet _2: extracted operating values

Source: `Bunch of Run Sheets/alphas 1 2020_2.xlsx`, `alpha data!A1:AU31`.

Extracted 30 operating rows; 29 have convertible dates. Latest dated entry: **2020-03-17**, row 14, beamline **test**. Rows are organized by energy, not chronological order.

## Latest dated entry

| Field | Recorded value |
| --- | --- |
| Date | 2020-03-17 (Excel serial 43907) |
| Beamline | test |
| Energy | 35 |
| Main Magnet | 1192 |
| Beam Centering | 0 |
| Trim Coil 1 | 0 |
| Trim Coil 2 | 76 |
| Trim Coil 3 | 465 |
| Trim Coil 4 | 704 |
| Trim Coil 5 | 589 |
| Trim Coil 6 | 642 |
| Trim Coil 7 | 682 |
| Trim Coil 8 | 627 |
| Trim Coil 9 | 80 |
| Trim Coil 10 | -583 |
| ESD KVolts | 66.5 |
| ESD mAmps | 0.19 |
| Coax Amps | 2375 |
| Inside Iron | 328 |
| Outside Iron | 1963 |
| Fringe Field | 60 |
| ESD Entrance | 28.27 |
| ESD Exit or Center | 0.836 |
| Coax Entrance | 31.22 |
| Coax Exit | 32.68 |
| Iron Entrance | 5.68 |
| Iron Exit | 1.5 |
| RF Freq | 8.718 |
| Shorting Plane Position | 9378 |
| Dee Voltage | 59 |
| Plate Voltage | 10 |
| Plate Current | 0.2 |
| Grid Current | 1.2 |
| Rotation | 432 |
| Azimuth | 2879 |
| Radius | 61 |
| Puller I/O | 246 |
| Puller N/S | 509 |

## Interpretation for Bayesian optimization

- Use the ten trim-coil fields as historical candidate inputs after verifying their units and mapping.
- Match configuration using energy, beamline, main magnet, RF, extraction and source geometry settings. Do not pool different energies into one stationary coil-only GP.
- The latest row is marked test; the newer non-test row is 2019-07-02, row 9, energy 30, beamline 2. Neither has a recorded beam objective.
- Stop 1, circulating, deflected and Stop 2 beam-current fields (AP:AS, headers in uA) are blank across all 30 operating rows. No measured beam maximum or efficiency can be recovered from these rows.
- Coil/magnet, energy and RF headers omit units. Preserve the numbers as recorded; do not silently label them amperes, MeV or MHz without confirmation. ESD kV/mA and Coax Amps have explicit header units.
- Targets versus actual readbacks, acquisition windows, uncertainties and operating limits are not established by these rows. These are historical configurations, not live-verified recovery references.
- The Copy variant has the same 29-date latest timestamp, despite its newer filesystem timestamp. The With H2Plus variant has dated entries through 2023-05-25; its mixed-species additions are not merged into this alpha extraction.
- Formula-only and auxiliary areas after row 31 are excluded. Cached extraction-efficiency errors elsewhere are not valid efficiency observations.

## Saved extraction

- `alpha_2020_2_operating_settings.csv`: all 30 rows with original field labels and ISO dates.
- `alpha_runsheet_extraction_raw.json`: source cell coordinates, missing-objective markers and unverified status.

Original workbooks were not modified.
