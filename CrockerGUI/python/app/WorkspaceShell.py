"""Persistent page directory; navigation and detaching are separate actions."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QToolButton, QVBoxLayout, QWidget,
)


PAGE_LABELS = {"PID Control": "PID + BO", "Hybrid GA + BO PID": "PID + Hybrid"}


class WorkspaceShell(QWidget):
    def __init__(self, stack, categories, details, navigate, open_window, mode, exit_button=None):
        super().__init__()
        self.setObjectName("workspaceShell")
        self.buttons = {}
        self.category_buttons = {}
        self.category_contents = {}
        self.parents = {name: parent for name, (parent, _) in details.items()}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QFrame()
        header.setObjectName("workspaceHeader")
        bar = QHBoxLayout(header)
        bar.setContentsMargins(20, 12, 20, 12)
        bar.setSpacing(24)
        self.toggle_sidebar = QPushButton("Pages")
        self.toggle_sidebar.setCheckable(True)
        self.toggle_sidebar.setChecked(True)
        self.toggle_sidebar.setAccessibleName("Show page directory")
        bar.addWidget(self.toggle_sidebar)
        brand = QLabel("Crocker Nuclear Laboratory Control")
        brand.setWordWrap(True)
        brand.setMinimumWidth(0)
        brand.setObjectName("workspaceBrand")
        bar.addWidget(brand, 1)
        bar.addStretch()
        environment = QLabel(mode.upper())
        environment.setObjectName("workspaceEnvironment")
        bar.addWidget(environment)
        if exit_button is not None:
            bar.addWidget(exit_button)
        outer.addWidget(header)

        self.splitter = QSplitter(Qt.Horizontal)
        self.sidebar = QScrollArea()
        self.sidebar.setObjectName("workspaceSidebar")
        self.sidebar.setWidgetResizable(True)
        self.sidebar.setFrameShape(QFrame.NoFrame)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar.setMinimumWidth(210)
        directory = QWidget()
        directory.setObjectName("workspaceDirectory")
        self.sidebar.setWidget(directory)
        navigation = QVBoxLayout(directory)
        navigation.setContentsMargins(10, 14, 10, 14)
        navigation.setSpacing(8)
        home = QPushButton("Home")
        home.setObjectName("workspacePageLink")
        home.setCheckable(True)
        home.clicked.connect(lambda: navigate("Home"))
        navigation.addWidget(home)
        self.buttons["Home"] = home
        for category in categories:
            toggle = QToolButton()
            toggle.setObjectName("workspaceCategory")
            toggle.setText(category)
            toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            toggle.setCheckable(True)
            toggle.setChecked(category == "Automation")
            toggle.setArrowType(Qt.DownArrow if toggle.isChecked() else Qt.RightArrow)
            toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            toggle.setAccessibleName(f"Expand {category} pages")
            navigation.addWidget(toggle)
            contents = QWidget()
            contents.setObjectName("workspaceCategoryPages")
            entries = QVBoxLayout(contents)
            entries.setContentsMargins(0, 0, 0, 4)
            entries.setSpacing(3)
            names = [category, *(name for name, (parent, _) in details.items() if parent == category)]
            for name in names:
                row = QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(4)
                label = f"All {category.lower()}" if name == category else PAGE_LABELS.get(name, name)
                go = QPushButton(label + "  →")
                go.setObjectName("workspacePageLink")
                go.setCheckable(True)
                go.setMinimumWidth(0)
                go.setToolTip(f"Go to {label}")
                go.setAccessibleName(f"Go to {name}")
                go.clicked.connect(lambda checked=False, n=name: navigate(n))
                row.addWidget(go, 1)
                detach = QPushButton("+")
                detach.setObjectName("workspaceNewWindow")
                detach.setFixedWidth(32)
                detach.setToolTip(f"Open {label} in a separate window")
                detach.setAccessibleName(f"Open {name} in a separate window")
                detach.clicked.connect(lambda checked=False, n=name: open_window(n))
                row.addWidget(detach)
                entries.addLayout(row)
                self.buttons[name] = go
            toggle.toggled.connect(lambda expanded, c=contents, b=toggle: self._expand(c, b, expanded))
            contents.setVisible(toggle.isChecked())
            navigation.addWidget(contents)
            self.category_buttons[category] = toggle
            self.category_contents[category] = contents
        navigation.addStretch()
        self.splitter.addWidget(self.sidebar)
        self.edge_rail = QFrame()
        self.edge_rail.setObjectName('workspaceSidebarRail')
        self.edge_rail.setFixedWidth(30)
        rail_layout = QVBoxLayout(self.edge_rail)
        rail_layout.setContentsMargins(0, 8, 0, 0)
        self.edge_toggle = QToolButton()
        self.edge_toggle.setObjectName('workspaceSidebarToggle')
        self.edge_toggle.setText('‹')
        self.edge_toggle.setToolTip('Collapse page directory')
        self.edge_toggle.setAccessibleName('Collapse page directory')
        self.edge_toggle.setFixedSize(30, 44)
        self.edge_toggle.clicked.connect(lambda: self.toggle_sidebar.setChecked(
            not self.toggle_sidebar.isChecked()))
        rail_layout.addWidget(self.edge_toggle)
        rail_layout.addStretch()
        self.splitter.addWidget(self.edge_rail)
        self.splitter.addWidget(stack)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setCollapsible(2, False)
        self.splitter.setStretchFactor(2, 1)
        self.splitter.setSizes([260, 30, 1040])
        self._sidebar_width = 260
        outer.addWidget(self.splitter, 1)
        self.toggle_sidebar.toggled.connect(self.set_directory_visible)
        self.set_current("Home")

    @staticmethod
    def _expand(contents, button, expanded):
        contents.setVisible(expanded)
        button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def set_directory_visible(self, visible):
        if not visible and self.sidebar.isVisible():
            self._sidebar_width = max(210, self.splitter.sizes()[0])
        self.sidebar.setVisible(visible)
        self.edge_toggle.setText('‹' if visible else '›')
        label = 'Collapse page directory' if visible else 'Expand page directory'
        self.edge_toggle.setToolTip(label)
        self.edge_toggle.setAccessibleName(label)
        if visible:
            self.splitter.setSizes([self._sidebar_width, 30,
                                     max(1, self.width()-self._sidebar_width-30)])

    def set_current(self, name):
        for title, button in self.buttons.items():
            button.setChecked(title == name)
        category = self.parents.get(name, name)
        if category in self.category_buttons:
            self.category_buttons[category].setChecked(True)

    def resizeEvent(self, event):
        # Leave small displays enough room for the control page. The Pages
        # button always allows the directory to be reopened.
        if event.size().width() < 760 and event.oldSize().width() >= 760:
            self.toggle_sidebar.setChecked(False)
        super().resizeEvent(event)
