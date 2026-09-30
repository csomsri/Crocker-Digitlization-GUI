"""Real offscreen OpenGL: independent contexts, Unicode, DPI, and resource reuse."""
import ctypes
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtGui import QGuiApplication, QOpenGLContext, QOffscreenSurface, QSurfaceFormat
from PySide6.QtOpenGL import QOpenGLFramebufferObject
from shiboken6 import getCppPointer
import CycloViz


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    fmt = QSurfaceFormat()
    fmt.setVersion(4, 6)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    surface = QOffscreenSurface()
    surface.setFormat(fmt)
    surface.create()
    contexts = []
    output = ROOT / "build" / "engine-rendering"
    output.mkdir(parents=True, exist_ok=True)

    def activate(context):
        assert context.makeCurrent(surface), "Could not activate offscreen OpenGL context"
        CycloViz.set_current_render_context(getCppPointer(context)[0])
        CycloViz.load_opengl(lambda name: int(context.getProcAddress(name.encode("ascii")) or 0))

    for _ in range(2):
        context = QOpenGLContext()
        context.setFormat(fmt)
        assert context.create(), "OpenGL 4.6 context creation failed"
        contexts.append(context)
    assert not QOpenGLContext.areSharing(*contexts), "Test needs independent contexts"

    plots = [CycloViz.MagneticFieldBarPlot(), CycloViz.MagneticFieldBarPlot()]
    for plot in plots:
        plot.set_data("Current: µA · ± tolerance · Δ change", ["TC1", "µA", "°C", "Δ"], [200, 450, 650, 850])
    for index, (context, plot) in enumerate(zip(contexts, plots)):
        activate(context)
        for ratio in (1.0, 2.0):
            width, height = int(900 * ratio), int(420 * ratio)
            frame = QOpenGLFramebufferObject(width, height)
            assert frame.isValid() and frame.bind()
            plot.render(width, height, ratio)
            image = frame.toImage()
            assert not image.isNull()
            assert image.save(str(output / f"bars-context-{index}-dpi-{ratio:g}.png"))
            # Regions containing bars/labels differ from the background.
            colors = {image.pixelColor(x, y).rgb() for x in range(0, width, 10) for y in range(0, height, 10)}
            assert len(colors) > 10, "Rendering produced an empty or uniform framebuffer"
            frame.release()
            del frame
        # Explicit cleanup is idempotent; CPU configuration survives recreation.
        plot.release_resources()
        plot.release_resources()
        frame = QOpenGLFramebufferObject(900, 420)
        frame.bind()
        plot.render(900, 420)
        frame.release()
        del frame

    activate(contexts[0])
    try:
        plots[1].render(900, 420)
    except RuntimeError as error:
        assert "different OpenGL context" in str(error)
    else:
        raise AssertionError("Cross-context resource use was not rejected")

    # Exercise the other public native widgets and leave no resources behind.
    frame = QOpenGLFramebufferObject(900, 500)
    frame.bind()
    gauge = CycloViz.MagneticFieldSpeedometer()
    gauge.set_values(300, 299.7, 1000, "TC1")
    gauge.set_status(True, .3, .5, 1.2, False)
    gauge.render(900, 500)
    assert frame.toImage().save(str(output / "gauge.png"))
    line = CycloViz.TimeDomainLinePlot()
    line.set_samples([[i * .1, 50 + math.sin(i * .1), 50, math.sin(i * .1)] for i in range(120)])
    line.render(900, 500)
    assert frame.toImage().save(str(output / "line.png"))
    # Drawing must not leave its VAO, program, texture unit or sampler bound.
    def proc(name, result, *args):
        return ctypes.CFUNCTYPE(result, *args)(int(contexts[0].getProcAddress(name.encode('ascii'))))
    uint = ctypes.c_uint
    integer = ctypes.c_int
    pointer = ctypes.POINTER(uint)
    vao, texture, sampler = uint(), uint(), uint()
    proc('glGenVertexArrays', None, integer, pointer)(1, ctypes.byref(vao))
    proc('glGenTextures', None, integer, pointer)(1, ctypes.byref(texture))
    proc('glGenSamplers', None, integer, pointer)(1, ctypes.byref(sampler))
    proc('glBindVertexArray', None, uint)(vao)
    proc('glActiveTexture', None, uint)(0x84C0)  # GL_TEXTURE0
    proc('glBindTexture', None, uint, uint)(0x0DE1, texture)  # GL_TEXTURE_2D
    proc('glBindSampler', None, uint, uint)(0, sampler)
    proc('glActiveTexture', None, uint)(0x84C3)  # GL_TEXTURE3
    proc('glPixelStorei', None, uint, integer)(0x0CF5, 8)  # UNPACK_ALIGNMENT
    line.render(900, 500)
    get = proc('glGetIntegerv', None, uint, ctypes.POINTER(integer))
    def state(key):
        result = integer()
        get(key, ctypes.byref(result))
        return result.value
    assert state(0x85B5) == vao.value  # VERTEX_ARRAY_BINDING
    assert state(0x84E0) == 0x84C3  # ACTIVE_TEXTURE
    assert state(0x0CF5) == 8
    proc('glActiveTexture', None, uint)(0x84C0)
    assert state(0x8069) == texture.value  # TEXTURE_BINDING_2D
    assert state(0x8919) == sampler.value  # SAMPLER_BINDING (active unit)
    proc('glBindVertexArray', None, uint)(0)
    proc('glBindTexture', None, uint, uint)(0x0DE1, 0)
    proc('glBindSampler', None, uint, uint)(0, 0)
    proc('glDeleteVertexArrays', None, integer, pointer)(1, ctypes.byref(vao))
    proc('glDeleteTextures', None, integer, pointer)(1, ctypes.byref(texture))
    proc('glDeleteSamplers', None, integer, pointer)(1, ctypes.byref(sampler))
    # Check for GL errors after rendering, including texture upload/draw calls.
    get_error = ctypes.CFUNCTYPE(ctypes.c_uint)(int(contexts[0].getProcAddress(b"glGetError")))
    assert get_error() == 0, "OpenGL reported an error"
    gauge.release_resources()
    line.release_resources()
    frame.release()
    del frame
    for context, plot in zip(contexts, plots):
        activate(context)
        plot.release_resources()
        context.doneCurrent()
    CycloViz.set_current_render_context(0)
    print("Independent-context rendering, Unicode labels, DPI and resource recreation passed")


if __name__ == "__main__":
    main()
