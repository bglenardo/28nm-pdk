"""run_device_loop.py -- loop devices -> run existing routines -> save CSV + PNG.

Drop this file in the REPO ROOT of bglenardo/28nm-pdk, next to run_routine.py.
It is written in the same style as run_routine.py and reuses the existing
machinery UNCHANGED:

    iv_measure.config.load_project_config      (instrument_list.yaml)
    iv_measure.routines.load_routines_csv      (the lab's routine CSVs)
    iv_measure.routines.run_single_routine_from_csv
    iv_measure.routines.write_routine_measurements_csv

The ONLY new behavior: before each routine it sends "SEL <flavor> <row> <col>"
to the Arduino (which must be running the ~30-line patch in
ARDUINO_PATCH.txt), then loops devices x routines, and saves a linear+log
Ids plot PNG next to each CSV.

Usage:
    python run_device_loop.py \
        --devices devices.csv \
        --routines "Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv" \
        --routine-index 0 \
        --scan-port COM8 \
        --out data/loop_run1

devices.csv format (header required); flavor uses the SKETCH's 1..11 numbers:
    flavor,row,col
    3,0,0
    3,0,1
    ...
Generate a whole block (e.g. all 150 of flavor 3 = nmos_mid) with:
    python -c "print('flavor,row,col');
    [print(f'3,{r},{c}') for r in range(6) for c in range(25)]" > devices.csv

Re-running with the same --out skips (device, routine) pairs whose CSV
already exists, so an interrupted overnight run resumes where it stopped.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless-safe: overnight runs have no display
import matplotlib.pyplot as plt
import serial

# Same import shim as run_routine.py: run from repo root without pip install.
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from iv_measure.config import load_project_config
from iv_measure.routines import (
    RoutineMeasurement,
    load_routines_csv,
    run_single_routine_from_csv,
    write_routine_measurements_csv,
)

# Sketch flavor number -> human name (from the sketch's flavor_base[] order).
FLAVOR_NAMES = {
    1: "nmos_lvt", 2: "nmos_hvt", 3: "nmos_mid", 4: "nmos_na",
    5: "nmos_ulvt", 6: "nmos_dnw", 7: "pmos_ulvt", 8: "pmos_lvt",
    9: "pmos_mid", 10: "pmos_hvt", 11: "pmos_lvt_b",
}


# --------------------------------------------------------------------------- #
# Scan-Arduino helpers (talks to the SEL-patched sketch)
# --------------------------------------------------------------------------- #
def open_scan_arduino(port: str, baud: int = 115200) -> serial.Serial:
    """Open the port and wait for the sketch's READY banner (post-reset)."""
    ser = serial.Serial(port=port, baudrate=baud, timeout=10)
    time.sleep(2.0)  # Arduino auto-resets on port open
    deadline = time.time() + 15
    while time.time() < deadline:
        line = ser.readline().decode(errors="ignore").strip()
        if line == "READY":
            return ser
    raise RuntimeError("Arduino never printed READY -- is the patched sketch "
                       "flashed, and is this the right port?")


def select_device(ser: serial.Serial, flavor: int, row: int, col: int) -> None:
    """Send SEL and parse configureDevice()'s existing report.

    IMPORTANT: the sketch's built-in verification compares Sout to Sin in the
    SAME clock cycle of the load pass, so on a perfectly healthy chain it
    reports exactly 2 "mismatches" (the two one-hot bits) and prints
    "Test Failed". We therefore accept Mismatches <= 2 and only abort on
    more, which indicates a real chain problem (stuck bit, threshold, wiring).
    """
    ser.reset_input_buffer()
    ser.write(f"SEL {flavor} {row} {col}\n".encode())
    mismatches: int | None = None
    deadline = time.time() + 30
    while time.time() < deadline:
        line = ser.readline().decode(errors="ignore").strip()
        if line.startswith("Mismatches:"):
            mismatches = int(line.split(":")[1])
        if line == "SEL_DONE":
            if mismatches is None:
                raise RuntimeError("SEL completed but no Mismatches line seen")
            if mismatches > 2:
                raise RuntimeError(
                    f"scan verification: {mismatches} mismatches (>2). "
                    "2 is expected (same-cycle check quirk); more means a "
                    "real chain fault -- check Sout threshold and wiring.")
            return
    raise RuntimeError("timed out waiting for SEL_DONE")


# --------------------------------------------------------------------------- #
# Plotting (same content as plot_ids_vs_vgs.py / run_routine.py live plot,
# rendered once from the finished point list)
# --------------------------------------------------------------------------- #
def save_iv_plot(points: list[RoutineMeasurement], routine_name: str,
                 sweep_param: str, step_param: str, out_png: Path) -> None:
    """Linear + log Ids vs sweep parameter, one curve per step value."""
    by_step: dict[float, tuple[list[float], list[float]]] = {}
    for p in points:
        xs, ys = by_step.setdefault(p.step_value_v, ([], []))
        xs.append(p.sweep_value_v)
        ys.append(p.drain_i_a)

    fig, (ax_lin, ax_log) = plt.subplots(1, 2, figsize=(12, 5),
                                         constrained_layout=True)
    for step_v in sorted(by_step):
        xs, ys = by_step[step_v]
        label = f"{step_param}={step_v:.3f} V"
        ax_lin.plot(xs, ys, marker="o", ms=3, lw=1.2, label=label)
        ax_log.plot(xs, [abs(y) + 1e-15 for y in ys], marker="o", ms=3,
                    lw=1.2, label=label)
    ax_lin.set_title(f"{routine_name} (linear)")
    ax_log.set_title(f"{routine_name} (log)")
    ax_log.set_yscale("log")
    for ax in (ax_lin, ax_log):
        ax.set_xlabel(f"{sweep_param} (V)")
        ax.set_ylabel("Drain current (A)")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)
    fig.savefig(out_png, dpi=200)
    plt.close(fig)


# --------------------------------------------------------------------------- #
def load_device_list(path: Path) -> list[tuple[int, int, int]]:
    """Read devices.csv -> [(flavor, row, col), ...] with bounds checks."""
    devices: list[tuple[int, int, int]] = []
    with path.open(newline="") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            fl, r, c = int(row["flavor"]), int(row["row"]), int(row["col"])
            max_col = 14 if fl == 4 else 25  # nmos_na has 14 columns
            if not (1 <= fl <= 11 and 0 <= r < 6 and 0 <= c < max_col):
                raise ValueError(f"{path}:{i}: out of range (flavor {fl}, "
                                 f"row {r}, col {c})")
            devices.append((fl, r, c))
    return devices


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--devices", required=True, help="CSV: flavor,row,col")
    ap.add_argument("--routines", required=True, help="lab routine CSV")
    ap.add_argument("--routine-index", type=int, nargs="+", default=[0],
                    help="which routine row(s) to run per device")
    ap.add_argument("--scan-port", required=True, help="Arduino serial port")
    ap.add_argument("--config", default="instrument_list.yaml")
    ap.add_argument("--out", default="data/device_loop")
    args = ap.parse_args()

    config = load_project_config(args.config)          # existing loader
    routines = load_routines_csv(args.routines)        # existing loader
    devices = load_device_list(Path(args.devices))
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    scan = open_scan_arduino(args.scan_port)
    print(f"{len(devices)} devices x {len(args.routine_index)} routines "
          f"-> {out_root}")

    done = skipped = failed = 0
    for flavor, row, col in devices:
        dev_name = f"{FLAVOR_NAMES[flavor]}_r{row}c{col}"
        for ridx in args.routine_index:
            rname = routines[ridx].name.replace(" ", "_")
            dev_dir = out_root / dev_name
            csv_path = dev_dir / f"{rname}.csv"
            png_path = dev_dir / f"{rname}.png"
            if csv_path.exists():                      # resume: skip finished
                skipped += 1
                continue
            print(f"[{done + skipped + failed + 1}] {dev_name} :: {rname}")
            try:
                select_device(scan, flavor, row, col)
                spec, points = run_single_routine_from_csv(   # existing runner
                    config, args.routines, routine_index=ridx)
                dev_dir.mkdir(parents=True, exist_ok=True)
                write_routine_measurements_csv(csv_path, points)  # existing
                save_iv_plot(points, f"{dev_name} {spec.name}",
                             spec.sweep_param, spec.step_param, png_path)
                done += 1
            except Exception as exc:  # noqa: BLE001 -- one device must not
                failed += 1           # kill the overnight loop
                print(f"    FAILED: {exc} -- continuing with next device")
                (dev_dir / f"{rname}.FAILED.txt").parent.mkdir(
                    parents=True, exist_ok=True)
                (dev_dir / f"{rname}.FAILED.txt").write_text(str(exc))
                time.sleep(1.0)

    print(f"finished: {done} done, {skipped} skipped (already had CSV), "
          f"{failed} failed")


if __name__ == "__main__":
    main()
