from __future__ import annotations

import json
import time
from collections.abc import Callable

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from python.app.PageShell import DetailPage
from python.app.widgets.MagneticFieldWidgets import CHANNEL_NAMES, MAX_GAUGE_VALUE

try:
    from NodeGraphQt import BaseNode, NodeGraph
except Exception:
    BaseNode = None
    NodeGraph = None

try:
    import CycloViz
except Exception:
    CycloViz = None


NODE_NAMESPACE = "crocker.sequencer"
NODE_COLORS = {
    "start": (14, 88, 92),
    "field": (9, 56, 66),
    "parallel": (16, 68, 96),
    "timer": (82, 45, 96),
    "loop": (94, 70, 16),
    "end": (96, 28, 42),
}
NODE_TYPES = {
    "start": f"{NODE_NAMESPACE}.StartNode",
    "field": f"{NODE_NAMESPACE}.FieldCommandNode",
    "parallel": f"{NODE_NAMESPACE}.ParallelFieldsNode",
    "timer": f"{NODE_NAMESPACE}.TimerNode",
    "loop": f"{NODE_NAMESPACE}.LoopNode",
    "end": f"{NODE_NAMESPACE}.EndNode",
}


if BaseNode is not None:

    class StartNode(BaseNode):
        __identifier__ = NODE_NAMESPACE
        NODE_NAME = "Start"

        def __init__(self) -> None:
            super().__init__()
            self.set_color(*NODE_COLORS["start"])
            self.add_output("next", multi_output=False, color=(53, 244, 255))
            self.add_text_input("label", "Label", "Cyclotron sequence", "Sequence run label")


    class FieldCommandNode(BaseNode):
        __identifier__ = NODE_NAMESPACE
        NODE_NAME = "Set Field"

        def __init__(self) -> None:
            super().__init__()
            self.set_color(*NODE_COLORS["field"])
            self.add_input("in", multi_input=False, color=(53, 244, 255))
            self.add_output("next", multi_output=False, color=(143, 255, 210))
            self.add_combo_menu("channel", "Channel", CHANNEL_NAMES)
            self.add_spinbox(
                "target",
                "Target A",
                0.0,
                0.0,
                MAX_GAUGE_VALUE,
                "Target current in amps",
                double=True,
            )
            self.add_spinbox(
                "increment",
                "Increment A",
                0.0,
                -MAX_GAUGE_VALUE,
                MAX_GAUGE_VALUE,
                "Amps added on each loop pass",
                double=True,
            )
            self.add_checkbox("output_on", "Output", "On", True)
            self.add_checkbox("enabled", "Enabled", "Enabled", True)
            self.add_checkbox("hold_until_stable", "Stable", "Wait stable", False)


    class ParallelFieldsNode(BaseNode):
        __identifier__ = NODE_NAMESPACE
        NODE_NAME = "Parallel Fields"

        def __init__(self) -> None:
            super().__init__()
            self.set_color(*NODE_COLORS["parallel"])
            self.add_input("in", multi_input=False, color=(53, 244, 255))
            self.add_output("next", multi_output=False, color=(143, 255, 210))
            for index, channel in enumerate(CHANNEL_NAMES):
                default_enabled = index < 3
                self.add_checkbox(
                    f"channel_{index}_enabled",
                    channel,
                    "Set",
                    default_enabled,
                )
                self.add_spinbox(
                    f"channel_{index}_target",
                    f"{channel} A",
                    0.0,
                    0.0,
                    MAX_GAUGE_VALUE,
                    f"{channel} target current in amps",
                    double=True,
                )
            self.add_checkbox("output_on", "Output", "On", True)
            self.add_checkbox("enabled", "Enabled", "Enabled", True)


    class TimerNode(BaseNode):
        __identifier__ = NODE_NAMESPACE
        NODE_NAME = "Timer"

        def __init__(self) -> None:
            super().__init__()
            self.set_color(*NODE_COLORS["timer"])
            self.add_input("in", multi_input=False, color=(53, 244, 255))
            self.add_output("next", multi_output=False, color=(143, 255, 210))
            self.add_spinbox(
                "seconds",
                "Seconds",
                5.0,
                0.1,
                3600.0,
                "Delay before continuing",
                double=True,
            )
            self.add_combo_menu("behavior", "Behavior", ["Wait", "Hold", "Poll Stable"])


    class LoopNode(BaseNode):
        __identifier__ = NODE_NAMESPACE
        NODE_NAME = "Loop"

        def __init__(self) -> None:
            super().__init__()
            self.set_color(*NODE_COLORS["loop"])
            self.add_input("in", multi_input=False, color=(255, 181, 45))
            self.add_output("body", multi_output=False, color=(255, 181, 45))
            self.add_output("done", multi_output=False, color=(143, 255, 210))
            self.add_spinbox("count", "Count", 3, 1, 999, "Loop iterations")
            self.add_spinbox(
                "step_delay",
                "Delay",
                1.0,
                0.0,
                3600.0,
                "Delay between loop passes",
                double=True,
            )
            self.add_checkbox("incremental", "Incremental", "Use node increments", True)


    class EndNode(BaseNode):
        __identifier__ = NODE_NAMESPACE
        NODE_NAME = "End"

        def __init__(self) -> None:
            super().__init__()
            self.set_color(*NODE_COLORS["end"])
            self.add_input("in", multi_input=True, color=(255, 81, 105))
            self.add_checkbox("safe_zero", "Safe", "Zero outputs", False)


class SequencerPage(DetailPage):
    def __init__(
        self,
        go_back: Callable[[], None],
        backend_mode: str = "simulation",
        zmq_endpoint: str = "tcp://0.0.0.0:5555",
        control_backend=None,
    ) -> None:
        super().__init__(
            "Sequencer",
            "Sequence control",
            "Back to Field Ctrl",
            go_back,
        )
        self.backend_mode = backend_mode.lower()
        self.zmq_endpoint = zmq_endpoint
        self.backend = control_backend
        self.backend_available = control_backend is not None
        self.owns_backend = control_backend is None
        self.backend_connection = "Not Connected"
        self.backend_destination = "None"
        self.backend_status = f"{self.backend_mode.upper()} backend not connected"
        self.plan_steps: list[dict[str, object]] = []
        self.active_steps: list[dict[str, object]] = []
        self.current_step_index = 0
        self.running = False
        self.wait_started_at: float | None = None
        self.wait_seconds = 0.0
        self.current_step_label = "Idle"
        self.next_step_label = "None"
        self.last_result = "Ready"
        if self.owns_backend:
            self._start_backend()
        elif self.backend_available:
            self.backend_connection = "Connected"
            self.backend_destination = "Shared ControlService"
            self.backend_status = f"{self.backend_mode.upper()} shared backend connected"

        workspace_frame, workspace = self.add_workspace()
        workspace_frame.setObjectName("sequencerWorkspace")
        workspace.setContentsMargins(12, 8, 12, 12)
        workspace.setSpacing(10)

        if NodeGraph is None:
            workspace.addWidget(self._build_missing_dependency_panel(), 1)
            return

        self.graph = NodeGraph()
        self._configure_graph()
        self._canvas_pan_dragging = False

        workspace.addWidget(self._build_toolbar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        workspace.addLayout(body, 1)

        graph_widget = self.graph.widget
        graph_widget.setObjectName("sequencerGraph")
        graph_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        body.addWidget(graph_widget, 4)
        body.addWidget(self._build_side_panel(), 1)

        self._seed_default_graph()
        self._refresh_runtime_status()

        self.runner_timer = QTimer(self)
        self.runner_timer.timeout.connect(self._tick_runner)
        self.runner_timer.start(100)

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._refresh_backend_status)
        self.status_timer.start(500)

    def _build_missing_dependency_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("sequencerPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        message = QLabel(
            "NodeGraphQt is not available in this Python environment.\n"
            "Install it with: python -m pip install NodeGraphQt"
        )
        message.setObjectName("sequencerStatus")
        message.setAlignment(Qt.AlignCenter)
        layout.addWidget(message, 1)
        return panel

    def _configure_graph(self) -> None:
        self.graph.set_background_color(1, 7, 8)
        self.graph.set_grid_color(17, 62, 66)
        self.graph.register_node(StartNode)
        self.graph.register_node(FieldCommandNode)
        self.graph.register_node(ParallelFieldsNode)
        self.graph.register_node(TimerNode)
        self.graph.register_node(LoopNode)
        self.graph.register_node(EndNode)
        viewer = self.graph.viewer()
        viewer.setObjectName("sequencerViewer")
        viewer.installEventFilter(self)
        viewer.viewport().installEventFilter(self)
        viewer.setStyleSheet(
            """
            NodeViewer#sequencerViewer {
                background-color: #010708;
                border: 1px solid rgba(53, 244, 255, 0.52);
                border-radius: 8px;
            }
            """
        )

    def _build_toolbar(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("sequencerToolbar")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        for text, handler in (
            ("+ Set Field", self._add_field_node),
            ("+ Parallel Fields", self._add_parallel_node),
            ("+ Timer", self._add_timer_node),
            ("+ Loop", self._add_loop_node),
            ("Delete Selected", self._delete_selected_nodes),
            ("Compile Preview", self._compile_preview),
            ("Run", self._run_sequence),
            ("Stop", self._stop_sequence),
            ("Auto Layout", self._auto_layout),
        ):
            button = QPushButton(text)
            button.setObjectName("sequencerAction")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda checked=False, fn=handler: fn())
            layout.addWidget(button)
        layout.addStretch(1)
        return panel

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API name
        viewer = self.graph.viewer()
        if watched not in {viewer, viewer.viewport()}:
            return super().eventFilter(watched, event)

        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
            item = viewer.itemAt(self._event_pos(event))
            self._canvas_pan_dragging = item is None
            viewer.ALT_state = self._canvas_pan_dragging
        elif event.type() == QEvent.Type.MouseMove and self._canvas_pan_dragging:
            viewer.ALT_state = True
        elif event.type() == QEvent.Type.MouseButtonRelease:
            self._canvas_pan_dragging = False
            viewer.ALT_state = False
        return super().eventFilter(watched, event)

    def _event_pos(self, event):
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    def _build_side_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("sequencerPanel")
        panel.setMinimumWidth(310)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("SEQUENCE STATE")
        title.setObjectName("sequencerPanelTitle")
        self.connection_label = QLabel()
        self.connection_label.setObjectName("sequencerStatusCard")
        self.current_step_label_widget = QLabel()
        self.current_step_label_widget.setObjectName("sequencerStateCard")
        self.next_step_label_widget = QLabel()
        self.next_step_label_widget.setObjectName("sequencerStateCard")
        self.result_label = QLabel()
        self.result_label.setObjectName("sequencerStateCard")

        progress_title = QLabel("TIME TO NEXT STATE")
        progress_title.setObjectName("sequencerPanelTitle")
        self.step_progress = QProgressBar()
        self.step_progress.setObjectName("sequencerProgress")
        self.step_progress.setRange(0, 1000)
        self.step_progress.setValue(0)

        layout.addWidget(title)
        layout.addWidget(self.connection_label)
        layout.addWidget(self.current_step_label_widget)
        layout.addWidget(self.next_step_label_widget)
        layout.addWidget(self.result_label)
        layout.addSpacing(8)
        layout.addWidget(progress_title)
        layout.addWidget(self.step_progress)
        layout.addStretch(1)
        return panel

    def _seed_default_graph(self) -> None:
        start = self.graph.create_node(NODE_TYPES["start"], pos=(-620, -80))
        loop = self.graph.create_node(NODE_TYPES["loop"], pos=(-360, -80))
        field = self.graph.create_node(NODE_TYPES["field"], pos=(-80, -170))
        timer = self.graph.create_node(NODE_TYPES["timer"], pos=(210, -170))
        end = self.graph.create_node(NODE_TYPES["end"], pos=(210, 40))
        start.get_output("next").connect_to(loop.get_input("in"))
        loop.get_output("body").connect_to(field.get_input("in"))
        field.get_output("next").connect_to(timer.get_input("in"))
        loop.get_output("done").connect_to(end.get_input("in"))
        loop.set_property("count", 5)
        loop.set_property("step_delay", 2.0)
        self.graph.clear_selection()
        self.graph.clear_undo_stack()

    def _add_field_node(self) -> None:
        self.graph.create_node(NODE_TYPES["field"], pos=self.graph.cursor_pos())

    def _add_parallel_node(self) -> None:
        self.graph.create_node(NODE_TYPES["parallel"], pos=self.graph.cursor_pos())

    def _add_timer_node(self) -> None:
        self.graph.create_node(NODE_TYPES["timer"], pos=self.graph.cursor_pos())

    def _add_loop_node(self) -> None:
        self.graph.create_node(NODE_TYPES["loop"], pos=self.graph.cursor_pos())

    def _auto_layout(self) -> None:
        nodes = self.graph.selected_nodes() or self.graph.all_nodes()
        self.graph.auto_layout_nodes(nodes=nodes)
        self.graph.fit_to_selection()

    def _delete_selected_nodes(self) -> None:
        nodes = self.graph.selected_nodes()
        if nodes:
            self.graph.delete_nodes(nodes)
            self._refresh_runtime_status()

    def _compile_preview(self) -> None:
        plan = self._compile_plan()
        dialog = QDialog(self)
        dialog.setWindowTitle("Compiled Sequence Preview")
        dialog.resize(720, 560)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        preview = QTextEdit()
        preview.setObjectName("sequencerPreview")
        preview.setReadOnly(True)
        preview.setPlainText(json.dumps(plan, indent=2))
        close_button = QPushButton("Close")
        close_button.setObjectName("sequencerAction")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(preview, 1)
        layout.addWidget(close_button, 0, Qt.AlignRight)
        dialog.exec()

    def _compile_plan(self) -> dict[str, object]:
        return {
            "version": 1,
            "target": "ControlService",
            "notes": "Compiled from SequencerPage node graph.",
            "steps": self._compile_steps(),
        }

    def _compile_steps(self) -> list[dict[str, object]]:
        start_nodes = self.graph.get_nodes_by_type(NODE_TYPES["start"])
        if not start_nodes:
            return [self._node_to_step(node) for node in self._position_ordered_nodes()]

        steps: list[dict[str, object]] = []
        visited: set[str] = set()
        self._walk_node(start_nodes[0], steps, visited)
        remaining = [
            self._node_to_step(node)
            for node in self._position_ordered_nodes()
            if node.id not in visited
        ]
        if remaining:
            steps.append({"type": "unwired_nodes", "steps": remaining})
        return steps

    def _walk_node(self, node, steps: list[dict[str, object]], visited: set[str]) -> None:
        if node.id in visited:
            steps.append({"type": "cycle_reference", "node": node.name()})
            return
        visited.add(node.id)
        step = self._node_to_step(node)

        if node.type_ == NODE_TYPES["loop"]:
            body = self._collect_branch(node, "body", visited)
            step["body"] = body
            steps.append(step)
            next_node = self._connected_node(node, "done")
        else:
            steps.append(step)
            next_node = self._connected_node(node, "next")

        if next_node is not None:
            self._walk_node(next_node, steps, visited)

    def _collect_branch(self, node, output_name: str, visited: set[str]) -> list[dict[str, object]]:
        branch_start = self._connected_node(node, output_name)
        if branch_start is None:
            return []
        branch_steps: list[dict[str, object]] = []
        self._walk_node(branch_start, branch_steps, visited)
        return branch_steps

    def _connected_node(self, node, output_name: str):
        output = node.get_output(output_name)
        if output is None:
            return None
        connected_ports = output.connected_ports()
        if not connected_ports:
            return None
        return connected_ports[0].node()

    def _position_ordered_nodes(self) -> list:
        return sorted(self.graph.all_nodes(), key=lambda item: (item.x_pos(), item.y_pos()))

    def _node_to_step(self, node) -> dict[str, object]:
        node_type = node.type_
        if node_type == NODE_TYPES["start"]:
            return {
                "type": "start",
                "label": node.get_property("label"),
            }
        if node_type == NODE_TYPES["field"]:
            channel = node.get_property("channel")
            return {
                "type": "set_field",
                "channel": channel,
                "channel_index": CHANNEL_NAMES.index(channel) if channel in CHANNEL_NAMES else 0,
                "target_amps": self._number(node.get_property("target")),
                "increment_amps": self._number(node.get_property("increment")),
                "output_on": bool(node.get_property("output_on")),
                "enabled": bool(node.get_property("enabled")),
                "hold_until_stable": bool(node.get_property("hold_until_stable")),
            }
        if node_type == NODE_TYPES["parallel"]:
            channels = []
            for index, channel in enumerate(CHANNEL_NAMES):
                if bool(node.get_property(f"channel_{index}_enabled")):
                    channels.append({
                        "channel": channel,
                        "channel_index": index,
                        "target_amps": self._number(node.get_property(f"channel_{index}_target")),
                    })
            return {
                "type": "parallel_fields",
                "channels": channels,
                "output_on": bool(node.get_property("output_on")),
                "enabled": bool(node.get_property("enabled")),
            }
        if node_type == NODE_TYPES["timer"]:
            return {
                "type": "timer",
                "seconds": self._number(node.get_property("seconds")),
                "behavior": node.get_property("behavior"),
            }
        if node_type == NODE_TYPES["loop"]:
            return {
                "type": "loop",
                "count": int(float(node.get_property("count"))),
                "step_delay_seconds": self._number(node.get_property("step_delay")),
                "incremental": bool(node.get_property("incremental")),
            }
        if node_type == NODE_TYPES["end"]:
            return {
                "type": "end",
                "safe_zero": bool(node.get_property("safe_zero")),
            }
        return {
            "type": "unknown",
            "node": node.name(),
        }

    def _number(self, value) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _start_backend(self) -> None:
        if CycloViz is None or not hasattr(CycloViz, "ControlService"):
            self.backend_status = "ControlService unavailable; build CycloViz bindings to run sequences"
            return
        try:
            self.backend = CycloViz.ControlService()
            if self.backend_mode == "simulation":
                self.backend.StartSimulator(20.0)
                self.backend_available = True
                self.backend_connection = "Connected"
                self.backend_destination = "Simulation"
                self.backend_status = "SIMULATION Connected"
            elif self.backend_mode == "zmq":
                self.backend.StartServer(self.zmq_endpoint)
                self.backend_available = True
                self.backend_connection = "Listening"
                self.backend_destination = self.zmq_endpoint
                self.backend_status = f"ZMQ Listening | {self.zmq_endpoint}"
            else:
                self.backend_status = f"Unknown backend mode: {self.backend_mode}"
        except Exception as exc:
            self.backend = None
            self.backend_available = False
            self.backend_connection = "Not Connected"
            self.backend_destination = self.backend_mode.upper()
            self.backend_status = f"{self.backend_mode.upper()} unavailable: {exc}"

    def _refresh_backend_status(self) -> None:
        if self.backend_available and self.backend is not None:
            try:
                health = self.backend.Health()
                self.backend_connection = str(health["connection"])
                self.backend_destination = str(health["endpoint"])
                self.backend_status = (
                    f"{self.backend_mode.upper()} {health['connection']} | "
                    f"packets {health['received_packets']}"
                )
            except Exception as exc:
                self.backend_available = False
                self.backend_connection = "Not Connected"
                self.backend_status = f"Backend status failed: {exc}"
        self._refresh_runtime_status()

    def _run_sequence(self) -> None:
        if self.running:
            return
        plan = self._compile_plan()
        self.plan_steps = list(plan["steps"])
        self.active_steps = self._expand_steps(self.plan_steps)
        if not self.active_steps:
            self.last_result = "No runnable steps"
            self._refresh_runtime_status()
            return
        if not self.backend_available or self.backend is None:
            self.last_result = self.backend_status
            self._refresh_runtime_status()
            return
        self.running = True
        self.current_step_index = 0
        self.wait_started_at = None
        self.wait_seconds = 0.0
        self.last_result = "Running"
        self._refresh_runtime_status()

    def _stop_sequence(self) -> None:
        self.running = False
        self.wait_started_at = None
        self.wait_seconds = 0.0
        self.last_result = "Stopped"
        self._refresh_runtime_status()

    def _tick_runner(self) -> None:
        if not self.running:
            return
        if self.wait_started_at is not None:
            elapsed = time.perf_counter() - self.wait_started_at
            if elapsed < self.wait_seconds:
                self._refresh_runtime_status()
                return
            self.wait_started_at = None
            self.wait_seconds = 0.0
            self.current_step_index += 1

        if self.current_step_index >= len(self.active_steps):
            self.running = False
            self.last_result = "Sequence complete"
            self._refresh_runtime_status()
            return

        step = self.active_steps[self.current_step_index]
        step_type = step.get("type")
        if step_type in {"start", "end"}:
            if step_type == "end" and step.get("safe_zero") and self.backend is not None:
                try:
                    self.backend.DisableAll()
                    self.last_result = "Safe zero / disable all sent"
                except Exception as exc:
                    self.last_result = f"Safe zero failed: {exc}"
                    self.running = False
                    self._refresh_runtime_status()
                    return
            self.current_step_index += 1
        elif step_type == "set_field":
            if self._execute_set_field(step):
                self.current_step_index += 1
            else:
                self.running = False
        elif step_type == "parallel_fields":
            if self._execute_parallel_fields(step):
                self.current_step_index += 1
            else:
                self.running = False
        elif step_type == "timer":
            self.wait_seconds = max(0.0, float(step.get("seconds", 0.0)))
            self.wait_started_at = time.perf_counter()
            self.last_result = f"Timer started: {self.wait_seconds:.1f}s"
        else:
            self.last_result = f"Skipped unsupported step: {step_type}"
            self.current_step_index += 1
        self._refresh_runtime_status()

    def _execute_set_field(self, step: dict[str, object]) -> bool:
        if self.backend is None:
            self.last_result = "Backend not connected"
            return False
        try:
            target = float(step.get("effective_target_amps", step.get("target_amps", 0.0)))
            loop_iteration = int(step.get("loop_iteration", 0))
            if "effective_target_amps" not in step and bool(step.get("loop_incremental", False)):
                target += float(step.get("increment_amps", 0.0)) * loop_iteration
            target = max(0.0, min(MAX_GAUGE_VALUE, target))
            self.backend.SetChannelCommand(
                int(step.get("channel_index", 0)),
                target,
                bool(step.get("output_on", True)),
                bool(step.get("enabled", True)),
            )
            applied = bool(self.backend.ApplyCommand())
            channel = step.get("channel", "channel")
            self.last_result = f"{channel} -> {target:.2f} A {'applied' if applied else 'rejected'}"
            return applied
        except Exception as exc:
            self.last_result = f"Set field failed: {exc}"
            return False

    def _execute_parallel_fields(self, step: dict[str, object]) -> bool:
        if self.backend is None:
            self.last_result = "Backend not connected"
            return False
        channels = step.get("channels", [])
        if not isinstance(channels, list) or not channels:
            self.last_result = "Parallel fields node has no enabled channels"
            return False
        try:
            labels = []
            for channel in channels:
                target = max(0.0, min(MAX_GAUGE_VALUE, float(channel.get("target_amps", 0.0))))
                self.backend.SetChannelCommand(
                    int(channel.get("channel_index", 0)),
                    target,
                    bool(step.get("output_on", True)),
                    bool(step.get("enabled", True)),
                )
                labels.append(f"{channel.get('channel')}={target:.2f}A")
            applied = bool(self.backend.ApplyCommand())
            self.last_result = f"Parallel {'applied' if applied else 'rejected'}: {', '.join(labels)}"
            return applied
        except Exception as exc:
            self.last_result = f"Parallel fields failed: {exc}"
            return False

    def _expand_steps(
        self,
        steps: list[dict[str, object]],
        loop_iteration: int = 0,
        loop_incremental: bool = False,
    ) -> list[dict[str, object]]:
        expanded: list[dict[str, object]] = []
        for step in steps:
            step_type = step.get("type")
            if step_type == "loop":
                count = max(0, int(step.get("count", 0)))
                body = step.get("body", [])
                for iteration in range(count):
                    expanded.extend(
                        self._expand_steps(
                            body if isinstance(body, list) else [],
                            loop_iteration=iteration,
                            loop_incremental=bool(step.get("incremental", False)),
                        )
                    )
                    delay = float(step.get("step_delay_seconds", 0.0))
                    if delay > 0:
                        expanded.append({
                            "type": "timer",
                            "seconds": delay,
                            "behavior": "Loop Delay",
                        })
            elif step_type == "unwired_nodes":
                continue
            else:
                next_step = dict(step)
                next_step["loop_iteration"] = loop_iteration
                next_step["loop_incremental"] = loop_incremental
                if next_step.get("type") == "set_field":
                    target = float(next_step.get("target_amps", 0.0))
                    if loop_incremental:
                        target += float(next_step.get("increment_amps", 0.0)) * loop_iteration
                    next_step["effective_target_amps"] = max(0.0, min(MAX_GAUGE_VALUE, target))
                expanded.append(next_step)
        return expanded

    def _refresh_runtime_status(self) -> None:
        if not hasattr(self, "connection_label"):
            return
        if self.running and self.current_step_index < len(self.active_steps):
            current_step = self.active_steps[self.current_step_index]
            self.current_step_label = self._step_label(current_step)
            next_index = self.current_step_index + 1
            self.next_step_label = (
                self._step_label(self.active_steps[next_index])
                if next_index < len(self.active_steps)
                else "Complete"
            )
        else:
            self.current_step_label = "Idle"
            self.next_step_label = "None"

        self.connection_label.setText(
            f"Connection\n{self.backend_connection}\n{self.backend_destination}"
        )
        self.current_step_label_widget.setText(f"Current\n{self.current_step_label}")
        self.next_step_label_widget.setText(f"Next\n{self.next_step_label}")
        self.result_label.setText(f"Last Result\n{self.last_result}")

        if self.wait_started_at is None or self.wait_seconds <= 0:
            self.step_progress.setValue(0 if not self.running else 1000)
        else:
            elapsed = time.perf_counter() - self.wait_started_at
            self.step_progress.setValue(int(min(1.0, elapsed / self.wait_seconds) * 1000))

    def _step_label(self, step: dict[str, object]) -> str:
        step_type = step.get("type")
        if step_type == "set_field":
            target = step.get("effective_target_amps", step.get("target_amps", 0))
            return f"{step.get('channel', 'channel')} -> {target} A"
        if step_type == "parallel_fields":
            channels = step.get("channels", [])
            if isinstance(channels, list):
                names = ", ".join(str(channel.get("channel")) for channel in channels[:4])
                suffix = "..." if len(channels) > 4 else ""
                return f"Parallel {names}{suffix}"
            return "Parallel fields"
        if step_type == "timer":
            return f"Timer {step.get('seconds', 0)}s"
        if step_type == "start":
            return "Start"
        if step_type == "end":
            return "End"
        return str(step_type)

    def closeEvent(self, event) -> None:
        if self.owns_backend and self.backend is not None:
            try:
                self.backend.Stop()
            except Exception:
                pass
        super().closeEvent(event)
