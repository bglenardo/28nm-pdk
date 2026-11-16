"""Overlay the new row-5 column sweep on top of the old row-4 column sweep.

After the firmware fix the column encoding changed by one, so to land on the
SAME physical device: new (row 5, col j)  <->  old (row 4, col j-1).

This overlays the two Id-Vd families per physical device so you can see the
peak currents agree once the one-column offset is applied.
"""
from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict

import matplotlib.pyplot as plt


def load(path: str, flavor: str):
    # (row, col) -> {vg: ([vd], [id])}
    raw = defaultdict(lambda: defaultdict(lambda: ([], [])))
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["Flavor_name"] != flavor:
                continue
            key = (int(r["Row_idx"]), int(r["Col_idx"]))
            try:
                vg = round(float(r["vg"]), 3)
                vd = float(r["vd"])
                idv = float(r["id"])
            except ValueError:
                continue
            raw[key][vg][0].append(vd)
            raw[key][vg][1].append(idv)
    # sort each curve by vd
    out = {}
    for key, vgs in raw.items():
        out[key] = {}
        for vg, (vd, idv) in vgs.items():
            pairs = sorted(zip(vd, idv))
            out[key][vg] = ([p[0] for p in pairs], [p[1] for p in pairs])
    return out


def vg_color_map(all_vgs):
    vgs = sorted(all_vgs)
    cmap = plt.get_cmap("viridis")
    n = max(len(vgs) - 1, 1)
    return {vg: cmap(i / n) for i, vg in enumerate(vgs)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", default="data/array_scan_row5_cols0to8_check.csv")
    ap.add_argument("--old", default="data/array_scan_board1_chip2_nmos_standard.csv")
    ap.add_argument("--flavor", default="NMOS_LVT")
    ap.add_argument("--new-row", type=int, default=5)
    ap.add_argument("--old-row", type=int, default=4)
    ap.add_argument("--new-cols", default="0-8")
    ap.add_argument("--out", default="data/overlay_colsweep_row5_vs_row4_NMOS_LVT.png")
    args = ap.parse_args()

    lo, hi = (args.new_cols.split("-") + [args.new_cols])[:2]
    new_cols = list(range(int(lo), int(hi) + 1))

    new = load(args.new, args.flavor)
    old = load(args.old, args.flavor)

    all_vgs = set()
    for c in new_cols:
        all_vgs |= set(new.get((args.new_row, c), {}).keys())
        all_vgs |= set(old.get((args.old_row, c - 1), {}).keys())
    colors = vg_color_map(all_vgs)

    n = len(new_cols)
    ncols = math.ceil(math.sqrt(n))
    nrows = math.ceil(n / ncols)
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(4 * ncols, 3 * nrows), constrained_layout=True
    )
    axes = axes.ravel() if hasattr(axes, "ravel") else [axes]

    for ax, c in zip(axes, new_cols):
        new_fam = new.get((args.new_row, c), {})
        old_fam = old.get((args.old_row, c - 1), {}) if c - 1 >= 0 else {}
        for vg, (vd, idv) in sorted(new_fam.items()):
            ax.plot(vd, idv, "-", color=colors[vg], lw=1.8)
        for vg, (vd, idv) in sorted(old_fam.items()):
            ax.plot(vd, idv, "--", color=colors[vg], lw=1.2)
        ax.set_title(
            f"new r{args.new_row} c{c}  vs  old r{args.old_row} c{c-1}", fontsize=9
        )
        ax.set_xlabel("Vd (V)")
        ax.set_ylabel("Id (A)")
        ax.grid(True, alpha=0.3)

    for ax in axes[n:]:
        ax.axis("off")

    # legend proxies
    solid = plt.Line2D([], [], color="k", ls="-", label=f"new (row {args.new_row})")
    dashed = plt.Line2D([], [], color="k", ls="--", label=f"old (row {args.old_row})")
    fig.legend(handles=[solid, dashed], loc="upper right")

    sm = plt.cm.ScalarMappable(
        cmap="viridis", norm=plt.Normalize(min(all_vgs), max(all_vgs))
    )
    fig.colorbar(sm, ax=axes.tolist() if hasattr(axes, "tolist") else list(axes), label="Vg (V)")

    fig.suptitle(
        f"{args.flavor}: new row {args.new_row} overlaid on old row {args.old_row} "
        f"(column offset -1)",
        fontsize=12,
    )
    fig.savefig(args.out, dpi=130)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
