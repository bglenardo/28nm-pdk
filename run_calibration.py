"""run_calibration.py -- datasheet calibration/leakage measurement (Section 2.3).

Measures the shared drain/source rails with NOTHING selected. Per the datasheet
"there is an option to calibrate leakage in this scheme, by measuring the
current when [no device is enabled]". If this run shows the SAME ~1 uA pedestal
and diode runaway we see with a device supposedly selected, then that current is
a fixed parasitic/damaged path, NOT a transistor -- strong confirmation the die
(or a shared pad node) is damaged rather than a routing/polarity error.

HOW "nothing selected" is achieved without reflashing:
The flashed SEL sketch has no deselect command, but configureDevice() always
resetScanChain() -> setScanAddress() -> shift -> latch. On an OUT-OF-RANGE
address, setScanAddress() memsets scan_data to 0 and returns early, so the chain
latches ALL ZEROS = every device disabled. We send one such command here.

Reuses existing machinery unchanged: open_scan_arduino / save_iv_plot from
run_device_loop, run_single_routine_from_csv / write_routine_measurements_csv
from iv_measure, and grade_output_family from validate_iv.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from iv_measure.config import load_project_config
from iv_measure.routines import (
    run_single_routine_from_csv,
    write_routine_measurements_csv,
)
from run_device_loop import open_scan_arduino, save_iv_plot
from validate_iv import grade_output_family


def deselect_all(ser, timeout_s: float = 30.0) -> None:
    """Latch an all-zero scan chain (nothing selected) via an out-of-range SEL."""
    # col 99 is out of range for any flavor -> setScanAddress zeros + returns,
    # configureDevice still shifts (all-zero) and latches = calibration mode.
    ser.reset_input_buffer()
    ser.write(b"SEL 1 0 99\n")
    deadline = time.time() + timeout_s
    saw_invalid = False
    while time.time() < deadline:
        line = ser.readline().decode(errors="ignore").strip()
        if "Invalid" in line:
            saw_invalid = True
        if line == "SEL_DONE":
            print(f"    deselect latched all-zeros "
                  f"(sketch reported Invalid address: {saw_invalid})")
            return
    raise RuntimeError("deselect: no SEL_DONE within timeout")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--routines", required=True, help="routine CSV to sweep")
    ap.add_argument("--routine-index", type=int, default=0)
    ap.add_argument("--scan-port", required=True)
    ap.add_argument("--config", default="instrument_list.yaml")
    ap.add_argument("--out", default="data/calibration")
    args = ap.parse_args()

    config = load_project_config(args.config)
    compliance_a = getattr(config.drain_source, "current_compliance_a", None) or 0.01

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"calibration (nothing selected) -> {out_dir}")
    scan = open_scan_arduino(args.scan_port)
    deselect_all(scan)

    spec, points = run_single_routine_from_csv(
        config, args.routines, routine_index=args.routine_index)

    csv_path = out_dir / "calibration.csv"
    png_path = out_dir / "calibration.png"
    write_routine_measurements_csv(csv_path, points)
    save_iv_plot(points, "CALIBRATION (nothing selected)",
                 spec.sweep_param, spec.step_param, png_path)

    verdict = grade_output_family(points, compliance_a=compliance_a)
    (out_dir / "calibration.verdict.txt").write_text(str(verdict))
    print(f"    saved {csv_path.name}, {png_path.name}")
    print(f"    grader: {verdict}")


if __name__ == "__main__":
    main()
