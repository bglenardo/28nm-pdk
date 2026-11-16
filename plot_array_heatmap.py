"""Array on-current heatmaps from a Vd-sweep LBL-format scan CSV.

For each device flavor this renders a Row_idx x Col_idx heatmap of the
on-state drain current ``Ion`` (the maximum measured ``id`` per device, i.e.
Vg = Vd = max). Rows map to device width, columns to length/finger count, so
each panel is a physical picture of how drive current varies across the array.

Two figures are written:
  * ``*_ion_heatmaps.png``      -- Ion on a linear colour scale (per-panel)
  * ``*_ion_heatmaps_log.png``  -- Ion on a shared log colour scale

Usage::

    python plot_array_heatmap.py \
        --measured data/array_scan_board1_chip2_nmos_vd_sweep_295K.csv \
        --out-dir data
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "src")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import colors

from iv_measure.device_geometry import (
    COL_TABLE,
    COL_TABLE_NA,
    FLAVOR_TABLE,
    ROW_TABLE,
    ROW_TABLE_NA,
    _NA_FLAVOR_0BASED,
)


def _load_ion(path: Path):
    """Return {flavor0: {(row,col): Ion}} using max |id| as the on-current."""
    ion: dict[int, dict[tuple[int, int], float]] = defaultdict(dict)
    names: dict[int, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for d in csv.DictReader(f):
            try:
                fl = int(d["flavor"])
                row = int(d["Row_idx"])
                col = int(d["Col_idx"])
                i = float(d["id"])
            except (TypeError, ValueError, KeyError):
                continue
            names[fl] = (d.get("Flavor_name") or "").strip()
            key = (row, col)
            cur = ion[fl].get(key)
            if cur is None or i > cur:
                ion[fl][key] = i
    return ion, names


def _axes_labels(flavor0: int):
    row_tab = ROW_TABLE_NA if flavor0 == _NA_FLAVOR_0BASED else ROW_TABLE
    col_tab = COL_TABLE_NA if flavor0 == _NA_FLAVOR_0BASED else COL_TABLE
    rows = sorted(row_tab)
    cols = sorted(col_tab)
    row_lab = [f"{row_tab[r] * 1e9:g}" for r in rows]      # width in nm
    col_lab = [f"{col_tab[c][0] * 1e9:g}/{col_tab[c][1]}" for c in cols]  # L(nm)/nf
    return rows, cols, row_lab, col_lab


def _grid(ion_map, rows, cols):
    grid = np.full((len(rows), len(cols)), np.nan)
    for ri, r in enumerate(rows):
        for ci, c in enumerate(cols):
            v = ion_map.get((r, c))
            if v is not None:
                grid[ri, ci] = v
    return grid


def _make_figure(ion, names, log: bool, out_path: Path):
    flavors = sorted(ion)
    n = len(flavors)
    ncols = 2
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(7.0 * ncols, 3.6 * nrows),
                             squeeze=False, constrained_layout=True)
    flat = [ax for r in axes for ax in r]

    # Shared log scale across panels for comparability.
    shared_norm = None
    if log:
        all_vals = [v for m in ion.values() for v in m.values() if v > 0]
        if all_vals:
            shared_norm = colors.LogNorm(vmin=min(all_vals), vmax=max(all_vals))

    for ax, fl in zip(flat, flavors):
        rows, cols, row_lab, col_lab = _axes_labels(fl)
        grid = _grid(ion[fl], rows, cols)
        if log:
            data = np.where(grid > 0, grid, np.nan)
            im = ax.imshow(data, aspect="auto", origin="lower", cmap="viridis",
                           norm=shared_norm)
        else:
            im = ax.imshow(grid, aspect="auto", origin="lower", cmap="viridis")
        ax.set_title(f"{names.get(fl, '')} (flavor {fl})", fontsize=10)
        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels(col_lab, fontsize=5, rotation=90)
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels(row_lab, fontsize=6)
        ax.set_xlabel("L(nm)/nf", fontsize=8)
        ax.set_ylabel("W (nm)", fontsize=8)
        cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
        cbar.set_label("Ion (A)", fontsize=8)
        cbar.ax.tick_params(labelsize=6)

    for ax in flat[n:]:
        ax.axis("off")

    scale = "log, shared scale" if log else "linear, per-panel scale"
    fig.suptitle(f"On-current (max Id) array heatmaps - {scale}", fontsize=13)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    print(f"Saved: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--measured",
                        default="data/array_scan_board1_chip2_nmos_vd_sweep_295K.csv",
                        help="Path to the Vd-sweep LBL-format CSV.")
    parser.add_argument("--out-dir", default="data", help="Output directory.")
    args = parser.parse_args()

    src = Path(args.measured)
    if not src.exists():
        raise FileNotFoundError(f"Missing input CSV: {src}")

    ion, names = _load_ion(src)
    if not ion:
        raise ValueError("No device data found.")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem

    _make_figure(ion, names, log=False, out_path=out_dir / f"{stem}_ion_heatmaps.png")
    _make_figure(ion, names, log=True, out_path=out_dir / f"{stem}_ion_heatmaps_log.png")


if __name__ == "__main__":
    main()
