"""CUDA preparation for the shared OpenGL plot."""

import ctypes as c

from backends.cpu_opengl.geometry import CpuGeometry
from backends.native import Timings


class CudaGeometry(CpuGeometry):
    def __init__(self, library, count, device):
        super().__init__(library, count)
        self.device = device
        self.baseline = (c.c_float * count)()
        self.timings = Timings()
        self.error = c.create_string_buffer(512)
        self.handle = None
        text = c.POINTER(c.c_char)
        self.native.bar_cuda_create.argtypes = [c.c_int, c.c_int, text, c.c_int, text, c.c_int]
        self.native.bar_cuda_create.restype = c.c_void_p
        self.native.bar_cuda_run.argtypes = [
            c.c_void_p, *self.native.bar_cpu.argtypes, c.POINTER(Timings), text, c.c_int
        ]
        self.native.bar_cuda_run.restype = c.c_int
        self.native.bar_cuda_destroy.argtypes = [c.c_void_p]
        self.native.bar_cuda_destroy.restype = None

    def start(self):
        if self.handle:
            return
        device_id = c.create_string_buffer(32)
        self.handle = self.native.bar_cuda_create(
            self.device, self.count, device_id, len(device_id), self.error, len(self.error)
        )
        if not self.handle:
            raise RuntimeError(self.error.value.decode(errors="replace"))
        self.device_id = device_id.value.decode()

    def stop(self):
        if self.handle:
            self.native.bar_cuda_destroy(self.handle)
            self.handle = None

    def prepare(self, values, scale, validate):
        args = self.arguments(values, scale)
        if not self.native.bar_cuda_run(
            self.handle, *args, c.byref(self.timings), self.error, len(self.error)
        ):
            raise RuntimeError(self.error.value.decode(errors="replace"))
        if validate:
            channels, count, scale, _, bars = args
            self.native.bar_cpu(channels, count, scale, self.baseline, bars)
            if any(abs(a - b) > 1e-6 for a, b in zip(self.heights, self.baseline)):
                raise RuntimeError("CUDA output differs from the CPU baseline")
        return self.heights, {name: getattr(self.timings, name) for name, _ in Timings._fields_}
