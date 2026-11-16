"""Transfer-curve (Id-Vg) plots from a Vg-sweep LBL-format array-scan CSV.

Routine 1 ("Accumulation to Inversion") sweeps Vg and steps Vd, so each device
yields a family of transfer curves. This script lays the devices out on their
physical Row_idx x Col_idx grid and draws one panel per device, each panel
showing Id vs Vg coloured by the stepped Vd value.

Two figures are produced:
  * linear Id-Vg (on-state behaviour, width/length scaling)
  * log |Id|-Vg (subthreshold slope / leakage floor)

Usage::

    python plot_vg_sweep.py \
        --measured data/array_scan_board1_chip2_vg_sweep.csv \
        --out-dir data
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import colors


def _load(path: Path):
    """Load the CSV into devices[(row,col)] -> {meta, curves{vd: (vg[],id[])}}."""
    devices: dict[tuple[int, int], dict] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for d in csv.DictReader(f):
            row = int(d["Row_idx"])
            col = int(d["Col_idx"])
            key = (row, col)
            dev = devices.get(key)
            if dev is None:
                dev = {
                    "flavor_name": d.get("Flavor_name", "").strip(),
                    "w": d.get("w", "").strip(),
                    "l": d.get("l", "").strip(),
                    "nf": d.get("nf", "").strip(),
                    "curves": defaultdict(lambda: ([], [])),
                }
                devices[key] = dev
            vd = float(d["vd"])
            vg = float(d["vg"])
            idv = float(d["id"])
            vg_list, id_list = dev["curves"][vd]
            vg_list.append(vg)
            id_list.append(idv)
    return devices


def _geom_label(dev: dict) -> str:
    def fmt_m(s: str) -> str:
        try:
            return f"{float(s) * 1e9:g}n"
        except ValueError:
            return "?"

    return f"W={fmt_m(dev['w'])} L={fmt_m(dev['l'])} nf={dev['nf'] or '?'}"


def _vd_color_map(devices: dict):
    vds: set[float] = set()
    for dev in devices.values():
        vds.update(dev["curves"].keys())
    ordered = sorted(vds)
    if not ordered:
        return {}, None
    norm = colors.Normalize(vmin=ordered[0], vmax=ordered[-1])
    cmap = plt.get_cmap("viridis")
    return {vd: cmap(norm(vd)) for vd in ordered}, (cmap, norm)


def _sorted_curve(vg_list, id_list):
    pairs = sorted(zip(vg_list, id_list), key=lambda p: p[0])
    if not pairs:
        return [], []
    vg, ids = zip(*pairs)
    return list(vg), list(ids)


def _make_figure(devices, vd_colors, cbar_info, flavor_name, log: bool, out_path: Path):
    rows = sorted({k[0] for k in devices})
    cols = sorted({k[1] for k in devices})
    nrows, ncols = len(rows), len(cols)

    fig, axes = plt.subplots(
        nrows, ncols,
        figsize=(1.7 * ncols + 1.5, 1.9 * nrows + 1.0),
        squeeze=False,
        constrained_layout=True,
    )

    for ri, row in enumerate(rows):
        for ci, col in enumerate(cols):
            ax = axes[ri][ci]
            ax.grid(True, alpha=0.3)
            dev = devices.get((row, col))
            if dev is None:
                ax.text(0.5, 0.5, "no data", ha="center", va="center",
                        transform=ax.transAxes, fontsize=7, color="0.5")
                ax.set_xticks([])
                ax.set_yticks([])
                continue
            for vd in sorted(dev["curves"].keys()):
                vg_list, id_list = dev["curves"][vd]
                vg, ids = _sorted_curve(vg_list, id_list)
                if not vg:
                    continue
                y = [abs(v) for v in ids] if log else ids
                ax.plot(vg, y, color=vd_colors.get(vd, "0.3"), lw=1.0)
            if log:
                ax.set_yscale("log")
            ax.set_title(f"r{row} c{col}  {_geom_label(dev)}", fontsize=6)
            ax.tick_params(labelsize=5)
            if ri == nrows - 1:
                ax.set_xlabel("Vg (V)", fontsize=6)
            if ci == 0:
                ax.set_ylabel("|Id| (A)" if log else "Id (A)", fontsize=6)

    if cbar_info is not None:
        cmap, norm = cbar_info
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=axes, shrink=0.7, pad=0.01)
        cbar.set_label("Vd step (V)", fontsize=8)
        cbar.ax.tick_params(labelsize=7)

    scale = "log" if log else "linear"
    fig.suptitle(f"{flavor_name} transfer curves (Id-Vg, {scale})", fontsize=11)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    print(f"Saved: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--measured",
        default="data/array_scan_board1_chip2_vg_sweep.csv",
        help="Path to the Vg-sweep LBL-format CSV.",
    )
    parser.add_argument(
        "--out-dir",
        default="data",
        help="Directory to write the PNG figures into.",
    )
    args = parser.parse_args()

    src = Path(args.measured)
    if not src.exists():
        raise FileNotFoundError(f"Missing input CSV: {src}")

    devices = _load(src)
    if not devices:
        raise ValueError("No device data found in CSV.")

    flavor_name = next(iter(devices.values()))["flavor_name"] or "device"
    vd_colors, cbar_info = _vd_color_map(devices)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem

    _make_figure(devices, vd_colors, cbar_info, flavor_name, log=False,
                 out_path=out_dir / f"{stem}_transfer_linear.png")
    _make_figure(devices, vd_colors, cbar_info, flavor_name, log=True,
                 out_path=out_dir / f"{stem}_transfer_log.png")


if __name__ == "__main__":
    main()
