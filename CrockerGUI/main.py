from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from source.Python.Data.pipeline_schema import DEFAULT_DB_PATH


def preload_zmq_for_qt(simulation_mode: str | None) -> None:
    if simulation_mode not in {"smoke2", "cyclotron"}:
        return
    # PySide installs an import hook that can interfere with pyzmq's import
    # chain on Python 3.13. Load pyzmq before Qt/PySide modules are imported.
    import zmq  # noqa: F401


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Crocker Digitalization GUI.")
    backend = parser.add_mutually_exclusive_group(required=True)
    backend.add_argument(
        "-simulation",
        action="store_true",
        help="Run one of the local simulation modes.",
    )
    backend.add_argument(
        "-ZMQ",
        action="store_const",
        const="zmq",
        dest="backend_mode",
        help="Run the GUI against the ZMQ server backend.",
    )
    parser.add_argument(
        "-smoke",
        action="store_true",
        help="Use the existing 14-channel equipment smoke simulator.",
    )
    parser.add_argument(
        "-smoke2",
        action="store_true",
        help=(
            "Use the running-machine smoke simulator. Channels start at "
            "nonzero current and accept GUI commands after control is enabled."
        ),
    )
    parser.add_argument(
        "-cyclotron",
        action="store_true",
        help="Use the cyclotron model as the ZMQ control plant.",
    )
    parser.add_argument(
        "--zmq-endpoint",
        default="tcp://0.0.0.0:5555",
        help="Endpoint used with -ZMQ. Default: tcp://0.0.0.0:5555",
    )
    parser.add_argument(
        "--data-pipeline",
        action="store_true",
        help="Start the experimental SQLite data logger and processor processes.",
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help=f"SQLite path for --data-pipeline. Default: {DEFAULT_DB_PATH}",
    )
    args = parser.parse_args(argv)
    args.db_path = str(Path(args.db_path))
    if args.simulation:
        selected_modes = sum(bool(mode) for mode in (args.smoke, args.smoke2, args.cyclotron))
        if selected_modes != 1:
            parser.error("-simulation requires exactly one of -smoke, -smoke2, or -cyclotron")
        args.backend_mode = "simulation"
        if args.cyclotron:
            args.simulation_mode = "cyclotron"
        elif args.smoke2:
            args.simulation_mode = "smoke2"
        else:
            args.simulation_mode = "smoke"
    else:
        if args.smoke or args.smoke2 or args.cyclotron:
            parser.error("-smoke, -smoke2, and -cyclotron may only be used with -simulation")
        args.simulation_mode = None
    return args


if __name__ == "__main__":
    args = parse_args()
    preload_zmq_for_qt(args.simulation_mode)
    from python.app.MainWindow import run_app

    raise SystemExit(
        run_app(
            args.backend_mode,
            args.zmq_endpoint,
            args.simulation_mode,
            enable_data_pipeline=args.data_pipeline,
            db_path=args.db_path,
        )
    )
