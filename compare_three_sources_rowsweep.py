"""Three-source Id-Vd row-sweep comparison at a fixed column.

Overlays, for one flavor and a fixed Col_idx across all device rows (widths):
  1. our measurements  (LBL-format scan CSV)          -- solid + markers
  2. LBL reference measurements (LBL-format CSV)        -- dashed
  3. TCAD/SPICE simulation (flavor/geometry-keyed CSV)  -- dotted

One subplot per row; within each panel the Id-Vd family is coloured by the gate
step Vg (shared colour map across all three sources). Our data and the LBL
reference are matched by (flavor, Row_idx, Col_idx); the simulation is matched by
(flavor, w, l, nf) geometry since it carries no array coordinates.

By default a per-source "baseline subtraction" is applied: for each device the
Vg=0 curve (pure drain leakage) is subtracted from every Vg curve, so each panel
shows the gate-induced drain current only. Disable with --no-baseline.

Usage::

    # single flavor
    python compare_three_sources_rowsweep.py --flavor 0 --col 0

    # every flavor present in the measured file
    python compare_three_sources_rowsweep.py --flavor all --col 0
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "src")

import numpy as np
import matplotlib.pyplot as plt
from matplotlib import colors
from matplotlib.lines import Line2D

from iv_measure.device_geometry import FLAVOR_TABLE, ROW_TABLE, ROW_TABLE_NA, _NA_FLAVOR_0BASED


def _geo_key(w, l, nf):
    """Normalise a (w, l, nf) triple to a hashable rounded key."""
    return (round(float(w), 12), round(float(l), 12), round(float(nf) if nf else 0.0, 3))


def _load_lbl(path: Path):
    """Return {(flavor,row,col): {"geo":(w,l,nf), "curves":{vg:([vd],[id])}}}."""
    devices: dict[tuple[int, int, int], dict] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for d in csv.DictReader(f):
            try:
                key = (int(d["flavor"]), int(d["Row_idx"]), int(d["Col_idx"]))
                vg = round(float(d["vg"]), 4)
                vd = float(d["vd"])
                i = float(d["id"])
            except (TypeError, ValueError, KeyError):
                continue
            dev = devices.get(key)
            if dev is None:
                dev = {"geo": _geo_key(d["w"], d["l"], d["nf"]),
                       "curves": defaultdict(lambda: ([], []))}
                devices[key] = dev
            vdl, idl = dev["curves"][vg]
            vdl.append(vd)
            idl.append(i)
    return devices


def _load_sim(path: Path):
    """Return {(flavor, geo): {vg: ([vd],[id])}} keyed by geometry."""
    sim: dict[tuple[int, tuple], dict] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for d in csv.DictReader(f):
            try:
                key = (int(d["flavor"]), _geo_key(d["w"], d["l"], d["nf"]))
                vg = round(float(d["vg"]), 4)
                vd = float(d["vd"])
                i = float(d["id"])
            except (TypeError, ValueError, KeyError):
                continue
            dev = sim.get(key)
            if dev is None:
                dev = defaultdict(lambda: ([], []))
                sim[key] = dev
            vdl, idl = dev[vg]
            vdl.append(vd)
            idl.append(i)
    return sim


def _sorted(vd_list, id_list):
    pairs = sorted(zip(vd_list, id_list), key=lambda p: p[0])
    if not pairs:
        return [], []
    vd, i = zip(*pairs)
    return list(vd), list(i)


def _baseline_subtract(curves):
    """Subtract the lowest-Vg (leakage) curve from every curve in a family.

    ``curves`` maps vg -> (vd_list, id_list). The baseline is the curve at the
    smallest Vg (nominally Vg=0). It is interpolated onto each curve's own Vd
    grid before subtraction, so differing Vd sampling is handled gracefully.
    Returns a new {vg: (vd_list, id_list)} with the baseline removed.
    """
    if not curves:
        return {}
    base_vg = min(curves)
    bvd, bid = _sorted(*curves[base_vg])
    bvd_a = np.asarray(bvd, dtype=float)
    bid_a = np.asarray(bid, dtype=float)
    out = {}
    for vg, (vd_list, id_list) in curves.items():
        vd, i = _sorted(vd_list, id_list)
        vd_a = np.asarray(vd, dtype=float)
        i_a = np.asarray(i, dtype=float)
        if bvd_a.size:
            base_on_grid = np.interp(vd_a, bvd_a, bid_a)
        else:
            base_on_grid = np.zeros_like(i_a)
        out[vg] = (vd_a.tolist(), (i_a - base_on_grid).tolist())
    return out


def _row_width_nm(flavor0, row):
    tab = ROW_TABLE_NA if flavor0 == _NA_FLAVOR_0BASED else ROW_TABLE
    w = tab.get(row)
    return f"{w * 1e9:g} nm" if w is not None else f"row {row}"


def make_figure(flavor0, col, mine, ref, sim, baseline, out_path):
    """Build and save one three-source comparison figure for a single flavor."""
    flavor_name = FLAVOR_TABLE.get(flavor0, f"flavor{flavor0}")

    rows = sorted({r for (fl, r, c) in mine if fl == flavor0 and c == col})
    if not rows:
        print(f"  (skip flavor {flavor0} {flavor_name}: no measured devices at col {col})")
        return None

    def _prep(curves):
        if baseline:
            return _baseline_subtract(curves)
        return {vg: _sorted(*vals) for vg, vals in curves.items()}

    # Shared Vg colour map across every curve drawn.
    all_vg = set()
    for r in rows:
        for store in (mine, ref):
            dev = store.get((flavor0, r, col))
            if dev:
                all_vg.update(dev["curves"])
        md = mine.get((flavor0, r, col))
        geo = md["geo"] if md else None
        if geo and (flavor0, geo) in sim:
            all_vg.update(sim[(flavor0, geo)])
    vg_sorted = sorted(all_vg)
    if not vg_sorted:
        print(f"  (skip flavor {flavor0} {flavor_name}: no curves found)")
        return None
    norm = colors.Normalize(vmin=vg_sorted[0], vmax=vg_sorted[-1])
    cmap = plt.get_cmap("viridis")
    vg_color = {vg: cmap(norm(vg)) for vg in vg_sorted}

    n = len(rows)
    ncols = 3
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(4.6 * ncols, 3.6 * nrows),
                             squeeze=False, constrained_layout=True)
    flat = [ax for rr in axes for ax in rr]

    for ax, r in zip(flat, rows):
        key = (flavor0, r, col)
        md = mine.get(key)
        rd = ref.get(key)
        geo = md["geo"] if md else None
        sd = sim.get((flavor0, geo)) if geo else None

        if md:
            for vg, (vd, i) in sorted(_prep(md["curves"]).items()):
                ax.plot(vd, i, color=vg_color.get(vg, "0.3"), lw=1.3,
                        marker="o", markersize=2.5, linestyle="-")
        if rd:
            for vg, (vd, i) in sorted(_prep(rd["curves"]).items()):
                ax.plot(vd, i, color=vg_color.get(vg, "0.3"), lw=1.2, linestyle="--")
        if sd:
            for vg, (vd, i) in sorted(_prep(sd).items()):
                ax.plot(vd, i, color=vg_color.get(vg, "0.3"), lw=1.4, linestyle=":")

        ax.set_title(f"{flavor_name}  row {r}: W={_row_width_nm(flavor0, r)}", fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.axhline(0.0, color="0.7", lw=0.6)
        ax.set_xlabel("Vd (V)", fontsize=8)
        ax.set_ylabel("Id \u2212 Id(Vg=0)  (A)" if baseline else "Id (A)", fontsize=8)
        ax.tick_params(labelsize=7)

    for ax in flat[n:]:
        ax.axis("off")

    style_handles = [
        Line2D([0], [0], color="0.3", lw=1.3, marker="o", markersize=3, linestyle="-",
               label="This work (measured)"),
        Line2D([0], [0], color="0.3", lw=1.2, linestyle="--", label="LBL reference"),
        Line2D([0], [0], color="0.3", lw=1.4, linestyle=":", label="Simulation"),
    ]
    fig.legend(handles=style_handles, loc="lower center", ncol=3, fontsize=9,
               frameon=False, bbox_to_anchor=(0.5, -0.02))

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=fig.axes, fraction=0.02, pad=0.01)
    cbar.set_label("Vg (V)")

    suffix = " (Vg=0 baseline subtracted)" if baseline else ""
    fig.suptitle(f"{flavor_name} Id-Vd row sweep at col {col} \u2014 "
                 f"measurement vs LBL vs simulation{suffix}", fontsize=12)

    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {out_path}")
    return out_path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--measured", default="data/array_scan_board1_chip2_nmos_vd_sweep_295K.csv")
    p.add_argument("--reference", default="LBL_setup/Will reference data 300K/20260818_194845.csv")
    p.add_argument("--simulation", default="data/Simulation_at_300K.csv")
    p.add_argument("--flavor", default="0",
                   help="0-based flavor index, or 'all' for every flavor in the measured file.")
    p.add_argument("--col", type=int, default=0, help="Fixed Col_idx held while sweeping rows.")
    p.add_argument("--no-baseline", dest="baseline", action="store_false",
                   help="Disable Vg=0 leakage subtraction.")
    p.add_argument("--out", default=None, help="Output path (single-flavor only).")
    args = p.parse_args()

    mine = _load_lbl(Path(args.measured))
    ref = _load_lbl(Path(args.reference))
    sim = _load_sim(Path(args.simulation))

    if str(args.flavor).lower() == "all":
        flavors = sorted({fl for (fl, r, c) in mine if c == args.col})
        if not flavors:
            raise ValueError(f"No measured devices at col {args.col}.")
    else:
        flavors = [int(args.flavor)]

    tag = "_baseline" if args.baseline else ""
    for flavor0 in flavors:
        flavor_name = FLAVOR_TABLE.get(flavor0, f"flavor{flavor0}")
        if args.out and len(flavors) == 1:
            out_path = args.out
        else:
            out_path = (f"data/compare_three_sources_{flavor_name}"
                        f"_rowsweep_col{args.col}{tag}.png")
        make_figure(flavor0, args.col, mine, ref, sim, args.baseline, out_path)


if __name__ == "__main__":
    main()
