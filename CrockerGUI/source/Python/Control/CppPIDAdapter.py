"""Adapt the existing bound C++ NLAPID API to the Python PID dataclasses."""
from dataclasses import asdict
from .NLAPID import PIDResult


class CppPIDAdapter:
    def __init__(self):
        try:
            import CycloViz
            self.module = CycloViz
            self.engine = CycloViz.NLAPID()
        except (ImportError, AttributeError) as exc:
            raise RuntimeError('Build CycloViz with NLAPID bindings to use the C++ GA page') from exc

    def _convert(self, value, typename):
        converted = getattr(self.module, typename)()
        for key, item in asdict(value).items():
            if hasattr(converted, key):
                setattr(converted, key, item)
        return converted

    def set_gains(self, gains):
        self.engine.set_gains(self._convert(gains.validated(), 'NLAPIDGains'))

    def set_limits(self, limits):
        self.engine.set_limits(self._convert(limits.validated(), 'NLAPIDLimits'))

    def set_settings(self, settings):
        self.engine.set_settings(self._convert(settings.validated(), 'NLAPIDSettings'))

    def reset(self, setpoint=None, measurement=None, direction=None):
        self.engine.reset(setpoint, measurement, direction)

    @property
    def last_result(self):
        return PIDResult(**self.engine.last_result)

    @property
    def direction(self):
        return self.engine.direction

    def update(self, setpoint, measurement, dt, hold_integrator=False):
        return PIDResult(**self.engine.update(setpoint, measurement, dt, hold_integrator))
