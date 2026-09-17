"""Interactive three-gain point cloud colored by posterior mean cost."""
# TODO: Replace the Matplotlib gain-space plot with an OpenGL renderer.
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class GainSurfaceWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.status = QLabel('Run trials to fit the gain-space cost model. All three gains vary.')
        self.status.setWordWrap(True)
        self.status.setStyleSheet('color: #cbd5e1;')
        layout.addWidget(self.status)
        self.figure = Figure(facecolor='#0f172a', layout='constrained')
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumHeight(260)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        self.set_grid(None)

    def set_grid(self, grid):
        self.figure.clear()
        ax = self.figure.add_subplot(111, projection='3d')
        ax.set_facecolor('#0f172a')
        for axis, label in [(ax.xaxis, 'Kp'), (ax.yaxis, 'Ki'), (ax.zaxis, 'Kd')]:
            axis.set_label_text(label, color='#cbd5e1')
            axis.set_pane_color((.08, .12, .20, 1))
        ax.tick_params(colors='#cbd5e1')
        if grid and grid.get('ready'):
            points = np.asarray(grid['points'])
            order = [grid['parameter_names'].index(name) for name in ('kp', 'ki', 'kd')]
            points = points[:, order]
            cloud = ax.scatter(*points.T, c=grid['mean'], cmap='viridis',
                               s=9, alpha=.35, depthshade=False)
            bar = self.figure.colorbar(cloud, ax=ax, shrink=.7, pad=.12)
            bar.set_label('Predicted cost (lower is better)', color='#cbd5e1')
            bar.ax.tick_params(colors='#cbd5e1')
            self.status.setText('All three gains vary | Color = predicted mean cost, not a safety guarantee. '
                                'Drag to rotate; use the toolbar to zoom.')
        else:
            self.status.setText((grid or {}).get('message', 'Waiting for enough safe trials to fit the gain-space model.'))
        trials = (grid or {}).get('trials', [])
        if trials:
            ax.scatter(*np.asarray(trials).T, marker='o', s=35, facecolors='none',
                       edgecolors='white', depthshade=False, label='Tested gains')
        best = (grid or {}).get('best')
        if best is not None:
            ax.scatter(*best, marker='*', s=200, c='#ffbe32', edgecolors='black',
                       depthshade=False, label='Best observed safe result')
        if trials or best is not None:
            ax.legend(facecolor='#172033', labelcolor='#cbd5e1', loc='upper left')
        self.canvas.draw_idle()
