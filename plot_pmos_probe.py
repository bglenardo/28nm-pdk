"""Quick plot of the single-device PMOS validation probe.

Reads an LBL-format scan CSV for one device and plots Id vs Vg transfer
curves, one line per stepped Vd setpoint, in both linear and log|Id| panels.

Note on PMOS re-referencing: the Keithley LO (source) is tied to +0.9 V, so the
recorded setpoints map to device biases as:
    V_GS = vg - 0.9    (vg 0..0.9  -> V_GS -0.9..0)
    V_DS = vd - 0.9    (vd 0..0.9  -> V_DS -0.9..0)
Id is negative (source->drain). The plot uses the true device axes.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict

import matplotlib.pyplot as plt
from matplotlib import colors, cm


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="data/_pmos_probe.csv")
    parser.add_argument("--out", default="plots/pmos_probe_transfer.png")
    args = parser.parse_args()

    rows = list(csv.DictReader(open(args.csv)))
    name = rows[0]["Flavor_name"]
    w = float(rows[0]["w"]) * 1e9
    length = float(rows[0]["l"]) * 1e9
    nf = rows[0]["nf"]
    r_idx = rows[0]["Row_idx"]
    c_idx = rows[0]["Col_idx"]

    # Group by stepped Vd setpoint -> list of (V_GS, Id).
    by_vd = defaultdict(list)
    for r in rows:
        vg = float(r["vg"])
        vd = float(r["vd"])
        idd = float(r["id"])
        by_vd[round(vd, 3)].append((vg - 0.9, idd))

    vd_setpoints = sorted(by_vd)
    vds_values = [vd - 0.9 for vd in vd_setpoints]  # true V_DS per step
    norm = colors.Normalize(vmin=min(vds_values), vmax=max(vds_values))
    cmap = cm.viridis

    fig, (ax_lin, ax_log) = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)

    for vd in vd_setpoints:
        pts = sorted(set(by_vd[vd]))
        vgs = [p[0] for p in pts]
        idd = [p[1] for p in pts]
        vds = vd - 0.9
        color = cmap(norm(vds))
        ax_lin.plot(vgs, [i * 1e3 for i in idd], color=color, marker=".", ms=4, lw=1)
        ax_log.plot(vgs, [abs(i) for i in idd], color=color, marker=".", ms=4, lw=1)

    ax_lin.set_xlabel("$V_{GS}$ (V)")
    ax_lin.set_ylabel("$I_D$ (mA)")
    ax_lin.set_title("Linear")
    ax_lin.grid(True, alpha=0.3)

    ax_log.set_xlabel("$V_{GS}$ (V)")
    ax_log.set_ylabel("$|I_D|$ (A)")
    ax_log.set_yscale("log")
    ax_log.set_title("Log")
    ax_log.grid(True, alpha=0.3, which="both")

    sm = cm.ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=[ax_lin, ax_log], label="$V_{DS}$ (V)")

    fig.suptitle(
        f"PMOS probe — {name}  (row {r_idx}, col {c_idx};  "
        f"W={w:.0f} nm, L={length:.0f} nm, nf={nf})  @ 175 K",
        fontsize=12,
    )

    fig.savefig(args.out, dpi=150)
    print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()
