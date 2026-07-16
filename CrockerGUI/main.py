from __future__ import annotations

import argparse

from python.app.MainWindow import run_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Crocker Digitalization GUI.")
    backend = parser.add_mutually_exclusive_group(required=True)
    backend.add_argument(
        "-simulation",
        action="store_const",
        const="simulation",
        dest="backend_mode",
        help="Run the GUI against the local C++ simulator backend.",
    )
    backend.add_argument(
        "-ZMQ",
        action="store_const",
        const="zmq",
        dest="backend_mode",
        help="Run the GUI against the ZMQ server backend.",
    )
    parser.add_argument(
        "--zmq-endpoint",
        default="tcp://0.0.0.0:5555",
        help="Endpoint used with -ZMQ. Default: tcp://0.0.0.0:5555",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(run_app(args.backend_mode, args.zmq_endpoint))
