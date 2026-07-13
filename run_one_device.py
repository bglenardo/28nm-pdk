"""run_one_device.py -- select ONE device, run ONE routine, save CSV+PNG.

A single-device runner with NO loop / resume / skip logic, for A/B comparison
against the original repo path (run_routine.py + original sketch). It does
exactly three things:

  1. SEL <flavor> <row> <col>   (via the SEL-patched sketch)
  2. run_single_routine_from_csv(...)   (the SAME engine run_routine.py uses)
  3. save CSV + annotated PNG + shape verdict

Nothing in src/iv_measure/ is touched -- the measurement is byte-for-byte the
same call the original code makes; the only added step is the serial SEL. That
is precisely the variable under test: does driving selection over serial (this
code + SEL sketch) give the same result as the original (hardcoded selection in
the sketch)?

Usage:
    python run_one_device.py --scan-port COM11 --flavor 3 --row 0 --col 0 \
        --routines "Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv" \
        --out data/one_device

Add --ignore-readback if the Sout read-back is known-broken (see CLAUDE.md Q2).
Add --no-select to skip the SEL entirely and measure whatever is currently
latched -- this makes it behave like the ORIGINAL runner (no serial selection),
for the closest possible comparison.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from iv_measure.config import load_project_config
from iv_measure.routines import (
    run_single_routine_from_csv,
    write_routine_measurements_csv,
)
import device_registry
import device_geometry
from validate_iv import grade_output_family
from run_device_loop import open_scan_arduino, select_device, save_iv_plot


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--flavor", type=int, required=True)
    ap.add_argument("--row", type=int, required=True)
    ap.add_argument("--col", type=int, required=True)
    ap.add_argument("--routines", required=True, help="routine CSV")
    ap.add_argument("--routine-index", type=int, default=0)
    ap.add_argument("--scan-port", help="Arduino port; omit with --no-select")
    ap.add_argument("--no-select", action="store_true",
                    help="skip serial SEL; measure whatever is latched "
                    "(mimics the original no-selection runner)")
    ap.add_argument("--ignore-readback", action="store_true")
    ap.add_argument("--config", default="instrument_list.yaml")
    ap.add_argument("--out", default="data/one_device")
    args = ap.parse_args()

    device_registry.validate_flavor(args.flavor, args.row, args.col)
    kind = device_registry.kind_of(args.flavor)
    name = device_registry.name_of(args.flavor)
    dev = f"{name}_r{args.row}c{args.col}"
    geo = device_geometry.label(args.flavor, args.row, args.col)

    config = load_project_config(args.config)
    compliance_a = getattr(config.drain_source, "current_compliance_a", None) or 0.01

    # Step 1: selection (unless --no-select).
    if args.no_select:
        print(f"[no-select] measuring whatever is latched, labeling as {dev}")
    else:
        if not args.scan_port:
            ap.error("--scan-port is required unless --no-select is given")
        print(f"selecting {dev}  ({geo})")
        ser = open_scan_arduino(args.scan_port)
        try:
            select_device(ser, args.flavor, args.row, args.col,
                          ignore_readback=args.ignore_readback)
        finally:
            ser.close()  # release the port before the routine uses instruments

    # Step 2: the SAME measurement engine the original run_routine.py uses.
    spec, points = run_single_routine_from_csv(
        config, args.routines, routine_index=args.routine_index)

    # Step 3: save CSV + annotated PNG + verdict (dated filenames).
    measured_on = date.today().isoformat()
    out_dir = Path(args.out) / kind / dev
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{spec.name.replace(' ', '_')}_{measured_on}"
    csv_path = out_dir / f"{stem}.csv"
    png_path = out_dir / f"{stem}.png"

    write_routine_measurements_csv(csv_path, points)
    save_iv_plot(points, f"{dev} {spec.name}", spec.sweep_param, spec.step_param,
                 png_path, subtitle=f"{geo}  |  measured {measured_on}")

    verdict = grade_output_family(points, compliance_a=compliance_a)
    (out_dir / f"{stem}.verdict.txt").write_text(str(verdict))

    print(f"saved: {csv_path}")
    print(f"       {png_path}")
    print(f"grader: {verdict}")


if __name__ == "__main__":
    main()
