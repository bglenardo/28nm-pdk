#!/usr/bin/env python3
"""Overlay Id-vs-Vd output curves to compare leakage current.

Two data sources are supported and overlaid on the same linear + log|Id| axes:
  --dir FOLDER     folder holding measurement CSVs (schema: step_value_v,
                   sweep_value_v, drain_i_a); one curve per (device, Vg step).
  --digitized CSV  a curve extracted from a PNG screenshot (no raw data on
                   disk). Schema: sweep_value_v, drain_i_a, step_value_v.
                   Plotted dashed to flag that it is pixel-digitized, ~few-%
                   accurate, not instrument data.

All curves here are NMOS output sweeps (Output WO Bulk: sweep=Vd, step=Vg),
so x is plotted as-measured (no PMOS mirroring).

Defaults reproduce the current comparison: the two testat folders (same
device nmos_hvt_r4c5, gate parked at 0 V vs -100 mV) plus the out-of-array
device digitized from its screenshot.
"""
import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless, per project convention
import matplotlib.pyplot as plt

DEFAULT_DIRS = [
    "data/Board_NMOS_testat0V",
    "data/Board_NMOS_testat100mV",
]
DEFAULT_DIGITIZED = [
    ("data/Board_chip1_outofarrdevice_100mV/digitized_from_png.csv",
     "out-of-array device (Vg=-0.1, from PNG)"),
]


def load_curves(folder: Path):
    """Return {(device, step_v): ([Vd], [Id])} for every CSV under folder."""
    curves: dict[tuple[str, float], tuple[list[float], list[float]]] = \
        defaultdict(lambda: ([], []))
    for csv_path in sorted(folder.rglob("*.csv")):
        device = csv_path.parent.name  # leaf dir, e.g. nmos_hvt_r4c5
        with open(csv_path, newline="") as fh:
            for row in csv.DictReader(fh):
                step_v = float(row["step_value_v"])
                xs, ys = curves[(device, step_v)]
                xs.append(float(row["sweep_value_v"]))
                ys.append(float(row["drain_i_a"]))
    return curves


def load_digitized(path: Path):
    """Return ([Vd], [Id]) from a digitized-curve CSV."""
    xs, ys = [], []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            xs.append(float(row["sweep_value_v"]))
            ys.append(float(row["drain_i_a"]))
    return xs, ys


def _plot(ax_lin, ax_log, vd, idc, label, dashed=False):
    pts = sorted(zip(vd, idc))  # monotonic left-to-right in Vd
    x = [p[0] for p in pts]
    y = [p[1] for p in pts]
    style = dict(marker="o", ms=3, lw=1.2, label=label)
    if dashed:
        style["ls"] = "--"
    ax_lin.plot(x, y, **style)
    ax_log.plot(x, [abs(v) + 1e-15 for v in y], **style)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", action="append", dest="dirs",
                    help="data folder to overlay (repeatable)")
    ap.add_argument("--digitized", action="append", nargs=2,
                    metavar=("CSV", "LABEL"), dest="digitized",
                    help="PNG-digitized curve CSV + legend label (repeatable)")
    ap.add_argument("--out", default="leakage_overlay.png",
                    help="output PNG path")
    args = ap.parse_args()

    dirs = args.dirs if args.dirs is not None else DEFAULT_DIRS
    digitized = (args.digitized if args.digitized is not None
                 else DEFAULT_DIGITIZED)

    fig, (ax_lin, ax_log) = plt.subplots(1, 2, figsize=(13, 5.5),
                                         constrained_layout=True)
    n = 0
    for folder_str in dirs:
        folder = Path(folder_str)
        if not folder.is_dir():
            print(f"WARN: {folder} not found, skipping")
            continue
        tag = folder.name
        for (device, step_v), (xs, ys) in sorted(load_curves(folder).items()):
            _plot(ax_lin, ax_log, xs, ys,
                  f"{tag} | {device} | Vg={step_v:.2f} V")
            n += 1

    for csv_str, label in digitized:
        path = Path(csv_str)
        if not path.is_file():
            print(f"WARN: {path} not found, skipping")
            continue
        xs, ys = load_digitized(path)
        _plot(ax_lin, ax_log, xs, ys, label, dashed=True)
        n += 1

    ax_lin.set_title("Id vs Vd (linear)")
    ax_log.set_title("Id vs Vd (log |Id|)")
    ax_log.set_yscale("log")
    for ax in (ax_lin, ax_log):
        ax.set_xlabel("Vd (V)")
        ax.set_ylabel("Drain current (A)")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=7)
    fig.suptitle("Leakage overlay  (dashed = digitized from PNG)", fontsize=11)
    # Off-gate rail conditions for these runs (from CSV cols vgxp_v/vgxn_v):
    # unselected gates parked at vgxp=1.0 V (PMOS side) / vgxn=-0.1 V (NMOS side).
    fig.text(0.5, 0.005, "vgxn = -0.1 V   |   vgxp = 1.0 V",
             ha="center", fontsize=9, style="italic")
    fig.savefig(args.out, dpi=200)
    plt.close(fig)
    print(f"{n} curves -> {args.out}")


if __name__ == "__main__":
    main()
