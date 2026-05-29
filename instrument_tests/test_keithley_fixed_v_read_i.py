from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Allow running this script directly from repository root without pip install -e .
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from iv_measure.config import load_project_config
from iv_measure.keithley2400 import Keithley2400


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Set the Keithley drain source to a fixed voltage and read current once."
        )
    )
    parser.add_argument(
        "--voltage",
        type=float,
        required=True,
        help="Fixed drain voltage to source in volts.",
    )
    parser.add_argument(
        "--config",
        default="instrument_list.yaml",
        help="Path to YAML instrument config.",
    )
    parser.add_argument(
        "--current-compliance-a",
        type=float,
        default=0.01,
        help="Current compliance in amps (default: 0.01).",
    )
    parser.add_argument(
        "--settle-s",
        type=float,
        default=1.0,
        help="Settling time in seconds before reading current (default: 1.0).",
    )
    parser.add_argument(
        "--leave-on",
        action="store_true",
        help="Leave output on after measurement (default is to turn output off).",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.current_compliance_a <= 0:
        raise ValueError("--current-compliance-a must be > 0")
    if args.settle_s < 0:
        raise ValueError("--settle-s must be >= 0")

    config = load_project_config(args.config)
    drain_cfg = config.drain_source

    with Keithley2400(
        port=drain_cfg.port,
        baudrate=drain_cfg.baudrate,
        timeout_s=drain_cfg.timeout_s,
        bytesize=drain_cfg.bytesize,
        parity=drain_cfg.parity,
        stopbits=drain_cfg.stopbits,
        write_termination=drain_cfg.write_termination,
        read_termination=drain_cfg.read_termination,
    ) as k2400:
        print(f"Connected to: {k2400.identify()}")
        k2400.reset()
        k2400.source_voltage(args.voltage, args.current_compliance_a)
        k2400.output_on()

        time.sleep(args.settle_s)
        measured_i_a = k2400.measure_source_current()
        print(f"Set Vd = {args.voltage:.6f} V")
        print(f"Measured Ids = {measured_i_a:.12g} A")

        if args.leave_on:
            print("Leaving Keithley output ON (--leave-on).")
        else:
            k2400.output_off()
            print("Keithley output OFF.")


if __name__ == "__main__":
    main()
