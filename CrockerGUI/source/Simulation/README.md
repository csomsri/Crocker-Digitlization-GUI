# Cyclotron particle model

`CyclotronModel` is the first beam-physics layer of the GUI simulator. It tracks
one proton in the median plane using relativistic momentum and a Boris pusher.
The initial field model is deliberately small and testable:

- uniform vertical magnetic field;
- time-varying horizontal electric field inside a central RF gap;
- circular chamber loss boundary;
- energy, speed, radius, RF phase, and loss diagnostics.

It does not yet model measured field maps, trim coils, dee geometry, injection,
extraction, particle ensembles, space charge, or material interactions.

## Python example

After building the `CycloViz` extension:

```python
import CycloViz

config = CycloViz.CyclotronConfig()
config.magnetic_field_t = 1.0
config.rf_frequency_hz = 15.0e6
config.rf_peak_electric_field_v_m = 100_000.0
config.time_step_s = 1.0e-10

particle = CycloViz.ParticleState()
particle.px_kg_m_s = 7.32e-21

model = CycloViz.CyclotronModel(config)
model.reset(particle)

orbit = []
for _ in range(20_000):
    model.step()
    orbit.append((model.state.x_m, model.state.y_m))
    if model.diagnostics.lost:
        break

print(model.diagnostics.kinetic_energy_ev)
```

Use the collected `orbit` points in the GUI plot. The next physics upgrade
should replace the uniform field with an interpolated measured field map.
