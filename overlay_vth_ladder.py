"""overlay_vth_ladder.py -- overlay the min-size (col 0, L=30nm) flavor curves
so the Vth ladder (lvt < mid < hvt) is readable on one axis.

Reads the Accumulation-to-Inversion (Id vs Vg) CSVs written by
run_device_loop.py, picks the highest-Vd step curve for each flavor, and plots
them together (linear + log). Pure read/plot; touches no hardware.
"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path("data/curves_request/nmos")
# (folder, label) for the matched-geometry min-size devices (W=0.1um, L=30nm).
DEVICES = [
    ("nmos_lvt_r0c0", "lvt (1,0,0)"),
    ("nmos_mid_r0c0", "mid (3,0,0)"),
    ("nmos_hvt_r0c0", "hvt (2,0,0)"),
]


def load_acc(folder: str):
    (path,) = ROOT.joinpath(folder).glob("*Accumulation_to_Inversion_*.csv")
    rows = list(csv.DictReader(path.open(newline="")))
    top = max(float(r["step_value_v"]) for r in rows)  # highest Vd step
    xs = [float(r["sweep_value_v"]) for r in rows
          if float(r["step_value_v"]) == top]
    ys = [float(r["drain_i_a"]) for r in rows
          if float(r["step_value_v"]) == top]
    return xs, ys, top


fig, (ax_lin, ax_log) = plt.subplots(1, 2, figsize=(12, 5),
                                     constrained_layout=True)
for folder, label in DEVICES:
    xs, ys, vd = load_acc(folder)
    ax_lin.plot(xs, ys, marker="o", ms=3, lw=1.3, label=f"{label} @ Vd={vd:g}V")
    ax_log.plot(xs, [abs(y) + 1e-15 for y in ys], marker="o", ms=3, lw=1.3,
                label=f"{label} @ Vd={vd:g}V")
fig.suptitle("nMOS Vth ladder -- min-size devices (W=0.1um, L=30nm), Id vs Vg",
             fontsize=11)
ax_lin.set_title("linear")
ax_log.set_title("log")
ax_log.set_yscale("log")
for ax in (ax_lin, ax_log):
    ax.set_xlabel("Vg (V)")
    ax.set_ylabel("Drain current (A)")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=9)

out = Path("data/curves_request/vth_ladder_overlay.png")
fig.savefig(out, dpi=200)
plt.close(fig)
print("wrote", out)
