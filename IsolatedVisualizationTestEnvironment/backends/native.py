"""C ABI shared by the native OpenGL configurations."""

import ctypes as c


class Timings(c.Structure):
    _fields_ = [(name, c.c_float) for name in ("upload_ms", "kernel_ms", "download_ms")]


def load_library(library):
    native = c.CDLL(str(library.resolve()))
    floats = c.POINTER(c.c_float)
    native.bar_cpu.argtypes = [floats, c.c_int, c.c_float, floats, c.c_int]
    native.bar_cpu.restype = None
    return native
