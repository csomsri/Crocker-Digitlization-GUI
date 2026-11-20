"""Shared instanced OpenGL renderer for the CPU and CUDA configurations."""

from time import perf_counter

import numpy as np
from OpenGL import GL
from OpenGL.GL.shaders import compileProgram, compileShader
from PySide6.QtOpenGLWidgets import QOpenGLWidget


VERTEX = """
#version 330 core
layout(location = 0) in float height;
uniform float barCount;
out vec3 barColor;
const vec2 corners[4] = vec2[4](vec2(0, 0), vec2(0.85, 0), vec2(0, 1), vec2(0.85, 1));
void main() {
    vec2 corner = corners[gl_VertexID];
    float x = 2.0 * (float(gl_InstanceID) + corner.x) / barCount - 1.0;
    gl_Position = vec4(x * 0.92, corner.y * height * 0.92, 0.0, 1.0);
    barColor = height >= 0.0 ? vec3(83, 201, 196) / 255.0 : vec3(233, 166, 107) / 255.0;
}
"""
FRAGMENT = """
#version 330 core
in vec3 barColor;
out vec4 pixel;
void main() {
    pixel = vec4(barColor, 1.0);
}
"""


class OpenGLPlot(QOpenGLWidget):
    def __init__(self, count):
        super().__init__()
        self.count = count
        self.heights = None
        self.paint_ms = None
        self.error = None
        self.renderer_name = ""
        self.vao = self.buffer = self.program = 0

    def initializeGL(self):
        self.context().aboutToBeDestroyed.connect(self.release)
        self.error = None
        try:
            self.renderer_name = GL.glGetString(GL.GL_RENDERER).decode(errors="replace")
            # Program validation can depend on draw state, which is set below.
            self.program = compileProgram(
                compileShader(VERTEX, GL.GL_VERTEX_SHADER),
                compileShader(FRAGMENT, GL.GL_FRAGMENT_SHADER),
                validate=False,
            )
            self.vao = GL.glGenVertexArrays(1)
            self.buffer = GL.glGenBuffers(1)
            GL.glBindVertexArray(self.vao)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.buffer)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, self.count * 4, None, GL.GL_DYNAMIC_DRAW)
            GL.glVertexAttribPointer(0, 1, GL.GL_FLOAT, False, 0, None)
            GL.glEnableVertexAttribArray(0)
            GL.glVertexAttribDivisor(0, 1)
            GL.glUseProgram(self.program)
            GL.glUniform1f(GL.glGetUniformLocation(self.program, "barCount"), self.count)
        except Exception as error:
            self.error = str(error)

    def release(self):
        self.makeCurrent()
        if self.buffer:
            GL.glDeleteBuffers(1, [self.buffer])
        if self.vao:
            GL.glDeleteVertexArrays(1, [self.vao])
        if self.program:
            GL.glDeleteProgram(self.program)
        self.vao = self.buffer = self.program = 0
        self.doneCurrent()

    def render(self, heights):
        if self.isVisible() and not self.isValid():
            raise RuntimeError("The OpenGL widget could not create a context")
        self.heights = np.ctypeslib.as_array(heights)
        self.paint_ms = None
        self.repaint()
        if self.error:
            raise RuntimeError(f"OpenGL rendering failed: {self.error}")
        return self.paint_ms

    def paintGL(self):
        if self.error:
            return
        started = perf_counter()
        try:
            GL.glClearColor(21 / 255, 27 / 255, 36 / 255, 1.0)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            if self.heights is not None:
                GL.glUseProgram(self.program)
                GL.glBindVertexArray(self.vao)
                GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.buffer)
                GL.glBufferSubData(GL.GL_ARRAY_BUFFER, 0, self.heights.nbytes, self.heights)
                GL.glDrawArraysInstanced(GL.GL_TRIANGLE_STRIP, 0, 4, self.count)
                GL.glFinish()
                self.paint_ms = (perf_counter() - started) * 1000
        except Exception as error:
            self.error = str(error)
