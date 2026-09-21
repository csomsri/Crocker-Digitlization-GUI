"""OpenGL-backed Qt chart surface with a headless fallback for tests."""
import os
from PySide6.QtGui import QGuiApplication
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget, QSizePolicy


_headless = (os.environ.get('QT_QPA_PLATFORM', '').split(':')[0] in ('offscreen', 'minimal')
             or QGuiApplication.platformName() in ('offscreen', 'minimal'))


class PlotSurface(QWidget if _headless else QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.opengl_enabled = not _headless
        if self.opengl_enabled:
            surface = self.format()
            surface.setSamples(4)
            self.setFormat(surface)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def paintGL(self):
        self.paint_chart(None)

    def paintEvent(self, event):
        if self.opengl_enabled:
            super().paintEvent(event)
        else:
            self.paint_chart(event)
