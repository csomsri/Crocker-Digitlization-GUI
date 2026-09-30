"""Bridge Qt context lifetime/DPI to the C++ graphics engine."""
from PySide6.QtGui import QOpenGLContext
from shiboken6 import getCppPointer


class NativeRenderLifecycle:
    def _connect_native_cleanup(self):
        context = self.context()
        previous = getattr(self, "_native_gl_context", None)
        if previous is context:
            return
        self._native_gl_context = context
        context.aboutToBeDestroyed.connect(self.release_native_resources)

    def _activate_native_context(self):
        import CycloViz
        context = QOpenGLContext.currentContext()
        if context is None or context != self.context():
            raise RuntimeError("The widget's OpenGL context must be current before rendering.")
        CycloViz.set_current_render_context(getCppPointer(context)[0])

    def release_native_resources(self):
        """May also be called at application shutdown; next paint can recreate."""
        native = getattr(self, "_native", None)
        context = getattr(self, "_native_gl_context", None)
        if native is None or context is None or not context.isValid():
            return
        self.makeCurrent()
        try:
            self._activate_native_context()
            native.release_resources()
        finally:
            self.doneCurrent()
            import CycloViz
            CycloViz.set_current_render_context(0)

    def closeEvent(self, event):
        # Release while this widget still has a usable native context. Keeping
        # the CPU object permits closing/reopening a panel without losing data.
        self.release_native_resources()
        super().closeEvent(event)
