"""C++ CPU preparation for the OpenGL plot."""

import ctypes as c

from backends.native import load_library


class CpuGeometry:
    device_id = ""

    def __init__(self, library, count):
        self.native = load_library(library)
        self.channels = (c.c_float * 14)()
        self.heights = (c.c_float * count)()
        self.count = count

    def start(self):
        pass

    def stop(self):
        pass

    def arguments(self, values, scale):
        self.channels[:len(values)] = values
        return self.channels, len(values), scale, self.heights, self.count

    def prepare(self, values, scale, validate):
        self.native.bar_cpu(*self.arguments(values, scale))
        return self.heights, {}
