from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

OPTIMIZER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPTIMIZER_DIR))

from bayesian_optimization import BotorchPidOptimizer, PidGainCandidate, PidTrialResult


DEFAULT_SCORE_WEIGHTS = {
    "settling_time": 1.0,
    "overshoot": 1.0,
    "steady_state_error": 1.0,
    "control_effort": 0.1,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run the PID Bayesian optimizer with historical CSV data."
    )
    parser.add_argument("csv", type=Path, help="CSV with kp, ki, kd, and response metrics.")
    parser.add_argument("--kp-bounds", nargs=2, type=float, metavar=("LOW", "HIGH"))
    parser.add_argument("--ki-bounds", nargs=2, type=float, metavar=("LOW", "HIGH"))
    parser.add_argument("--kd-bounds", nargs=2, type=float, metavar=("LOW", "HIGH"))
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional text file to write the dry-run summary to.",
    )
    parser.add_argument("--initial-safe-trials", type=int, default=6)
    parser.add_argument("--mc-samples", type=int, default=64)
    parser.add_argument("--num-restarts", type=int, default=4)
    parser.add_argument("--raw-samples", type=int, default=64)
    return parser.parse_args()


def infer_bounds(values: pd.Series) -> tuple[float, float]:
    low = float(values.min())
    high = float(values.max())
    if low == high:
        margin = abs(low) * 0.1 or 1.0
        return low - margin, high + margin
    margin = (high - low) * 0.05
    return low - margin, high + margin


def require_columns(frame: pd.DataFrame, columns: list[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"CSV is missing required column(s): {', '.join(missing)}")


def score_row(row: pd.Series) -> float:
    if "score" in row and pd.notna(row["score"]):
        return float(row["score"])

    return sum(
        DEFAULT_SCORE_WEIGHTS[column] * float(row[column])
        for column in DEFAULT_SCORE_WEIGHTS
    )


def parse_safe(value: object) -> bool:
    if pd.isna(value):
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"true", "yes", "y", "1", "safe"}:
        return True
    if normalized in {"false", "no", "n", "0", "unsafe"}:
        return False
    raise ValueError(f"Could not parse safe value: {value!r}")


def load_trial_results(csv_path: Path) -> list[PidTrialResult]:
    frame = pd.read_csv(csv_path)
    required = ["kp", "ki", "kd", *DEFAULT_SCORE_WEIGHTS.keys()]
    require_columns(frame, required)
    frame = frame.dropna(subset=required)

    results: list[PidTrialResult] = []
    for _, row in frame.iterrows():
        candidate = PidGainCandidate(
            kp=float(row["kp"]),
            ki=float(row["ki"]),
            kd=float(row["kd"]),
        )
        safe = parse_safe(row["safe"]) if "safe" in frame.columns else True
        results.append(
            PidTrialResult(
                candidate=candidate,
                score=score_row(row),
                settling_time=float(row["settling_time"]),
                overshoot=float(row["overshoot"]),
                steady_state_error=float(row["steady_state_error"]),
                control_effort=float(row["control_effort"]),
                safe=safe,
            )
        )
    return results


def main() -> int:
    args = parse_args()
    frame = pd.read_csv(args.csv)
    require_columns(frame, ["kp", "ki", "kd"])

    kp_bounds = tuple(args.kp_bounds) if args.kp_bounds else infer_bounds(frame["kp"])
    ki_bounds = tuple(args.ki_bounds) if args.ki_bounds else infer_bounds(frame["ki"])
    kd_bounds = tuple(args.kd_bounds) if args.kd_bounds else infer_bounds(frame["kd"])

    optimizer = BotorchPidOptimizer(
        kp_bounds,
        ki_bounds,
        kd_bounds,
        use_cuda=False,
        initial_safe_trials=args.initial_safe_trials,
        mc_samples=args.mc_samples,
        num_restarts=args.num_restarts,
        raw_samples=args.raw_samples,
    )
    optimizer.record_results(load_trial_results(args.csv))

    best = optimizer.best_result
    if best is None:
        raise RuntimeError("No safe trials were found in the CSV.")

    lines = [
        "Best known safe trial:",
        (
            f"  Kp={best.candidate.kp:.6g}, Ki={best.candidate.ki:.6g}, "
            f"Kd={best.candidate.kd:.6g}, score={best.score:.6g}"
        ),
        "",
        "Next suggested candidate(s):",
    ]
    for candidate in optimizer.propose_batch(args.batch_size):
        lines.append(
            f"  Kp={candidate.kp:.6g}, Ki={candidate.ki:.6g}, Kd={candidate.kd:.6g}"
        )

    output = "\n".join(lines)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
