from __future__ import annotations

import argparse

from iv_measure.config import load_project_config
from iv_measure.routines import run_routines_from_csv, write_routine_measurements_csv
from iv_measure.sweep import run_iv_sweep, write_measurements_csv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iv-measure",
        description="Run transistor I-V sweeps over USB-to-RS232 instruments.",
    )
    parser.add_argument(
        "--config",
        default="instrument_list.yaml",
        help="Path to YAML config file.",
    )
    parser.add_argument(
        "--routines-csv",
        default=None,
        help="Path to measurement-routines CSV. If set, runs all routines in CSV.",
    )
    parser.add_argument(
        "--output-csv",
        default="data/routines_measurements.csv",
        help="Output CSV path for --routines-csv mode.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    config = load_project_config(args.config)

    if args.routines_csv:
        points = run_routines_from_csv(config, args.routines_csv)
        write_routine_measurements_csv(args.output_csv, points)
        print(f"Saved {len(points)} points to {args.output_csv}")
        return

    points = run_iv_sweep(config)
    write_measurements_csv(config.sweep.output_csv, points)

    print(f"Saved {len(points)} points to {config.sweep.output_csv}")


if __name__ == "__main__":
    main()
