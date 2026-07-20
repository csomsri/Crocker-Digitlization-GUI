from __future__ import annotations

import argparse
from collections.abc import Sequence

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
        "-cyclotron",
        action="store_true",
        help="Use the cyclotron model as the ZMQ control plant.",
    )
    parser.add_argument(
        "--zmq-endpoint",
        default="tcp://0.0.0.0:5555",
        help="Endpoint used with -ZMQ. Default: tcp://0.0.0.0:5555",
    )
    args = parser.parse_args(argv)
    if args.simulation:
        if args.smoke == args.cyclotron:
            parser.error("-simulation requires exactly one of -smoke or -cyclotron")
        args.backend_mode = "simulation"
        args.simulation_mode = "cyclotron" if args.cyclotron else "smoke"
    else:
        if args.smoke or args.cyclotron:
            parser.error("-smoke and -cyclotron may only be used with -simulation")
        args.simulation_mode = None
    return args


if __name__ == "__main__":
    args = parse_args()
    from python.app.MainWindow import run_app

    raise SystemExit(run_app(args.backend_mode, args.zmq_endpoint, args.simulation_mode))
