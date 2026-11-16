"""Compare Vg-sweep (transfer) curves across settle-time scan runs.

The Vg-sweep routine ("Accumulation to Inversion") sweeps Vg and steps Vd, so
each run is a family of transfer curves keyed by the stepped Vd. This overlays
two or more runs (e.g. the same device measured with different ``--ids-settle-s``
values) and lays the figure out as a grid:

    * one plot **column per Vd step**, and
    * three plot **rows**:
        1. ``Id`` vs ``Vg`` on a linear scale,
        2. ``|Id|`` vs ``Vg`` on a log scale, and
        3. fractional residuals ``(Id - Id_ref) / Id_ref`` vs ``Vg`` against a
           chosen reference dataset (default: the first/slowest run).

Each dataset gets its own marker/linestyle; the stepped Vd shares a color across
every dataset. The underlying CSV data is never modified.

Usage::

    python compare_vg_sweep_settle.py \
        --dataset "1.0 s=data/array_scan_board1_chip2_vg_sweep_settle1p0.csv" \
        --dataset "0.3 s=data/array_scan_board1_chip2_vg_sweep_settle0p3.csv" \
        --dataset "0.1 s=data/array_scan_board1_chip2_vg_sweep_settle0p1.csv" \
        --dataset "0.05 s=data/array_scan_board1_chip2_vg_sweep_settle0p05.csv" \
        --reference-label "1.0 s" \
        --out data/compare_vg_sweep_settle_chip2.png
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


_DATASET_STYLES = [
    {"marker": "^", "linestyle": "-"},
    {"marker": "s", "linestyle": "--"},
    {"marker": "o", "linestyle": ":"},
    {"marker": "D", "linestyle": "-."},
]


def _parse_dataset(spec: str) -> tuple[str, Path]:
    if "=" not in spec:
        raise argparse.ArgumentTypeError(f"--dataset must be 'label=path', got: {spec!r}")
    label, _, path = spec.partition("=")
    label, path = label.strip(), path.strip()
    if not label or not path:
        raise argparse.ArgumentTypeError(f"--dataset must be 'label=path', got: {spec!r}")
    return label, Path(path)


def _load(path: Path):
    """Return {vd_step: ([vg], [id])} for the single device in the CSV, plus geometry."""
    if not path.exists():
        raise FileNotFoundError(f"Missing CSV: {path}")
    curves: dict[float, tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
    geom = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for d in csv.DictReader(f):
            if not geom:
                geom = {
                    "name": (d.get("Flavor_name") or "").strip(),
                    "w": (d.get("w") or "").strip(),
                    "l": (d.get("l") or "").strip(),
                    "nf": (d.get("nf") or "").strip(),
                }
            try:
                vd = round(float(d["vd"]), 6)
                vg = float(d["vg"])
                ids = float(d["id"])
            except (TypeError, ValueError):
                continue
            vg_list, id_list = curves[vd]
            vg_list.append(vg)
            id_list.append(ids)
    return curves, geom


def _sorted(vg_list, id_list):
    pairs = sorted(zip(vg_list, id_list), key=lambda p: p[0])
    if not pairs:
        return [], []
    vg, ids = zip(*pairs)
    return list(vg), list(ids)


def _geom_label(geom: dict) -> str:
    def fmt(s):
        try:
            return f"{float(s) * 1e9:g}n"
        except (TypeError, ValueError):
            return s or "?"
    return f"{geom.get('name', '')}  W={fmt(geom.get('w'))} L={fmt(geom.get('l'))} nf={geom.get('nf') or '?'}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dataset", action="append", required=True, metavar="LABEL=PATH",
                        help="A labelled scan CSV; repeat for each run to overlay.")
    parser.add_argument("--reference-label", default=None,
                        help="Dataset label used as the residual reference (default: first).")
    parser.add_argument("--out", default="data/compare_vg_sweep_settle.png",
                        help="Output PNG path.")
    parser.add_argument("--title", default="Vg-sweep settle-time comparison",
                        help="Figure suptitle prefix.")
    parser.add_argument("--skip-first-points", type=int, default=0,
                        help="Drop the first N points of each Vg sweep (by ascending "
                             "Vg) before plotting, to exclude step-in transients.")
    args = parser.parse_args()

    datasets: list[tuple[str, dict, dict]] = []
    for spec in args.dataset:
        label, path = _parse_dataset(spec)
        curves, geom = _load(path)
        datasets.append((label, curves, geom))
    if not datasets:
        raise ValueError("No datasets given.")

    ref_label = args.reference_label or datasets[0][0]
    ref_lookup = {label: curves for label, curves, _ in datasets}
    if ref_label not in ref_lookup:
        raise ValueError(f"--reference-label {ref_label!r} not in {list(ref_lookup)}")
    ref_curves = ref_lookup[ref_label]

    # Columns = union of Vd steps across datasets.
    vd_steps = sorted({vd for _, curves, _ in datasets for vd in curves})
    n_cols = len(vd_steps)
    if n_cols == 0:
        raise ValueError("No Vd steps found.")

    fig, axes = plt.subplots(3, n_cols, figsize=(4.8 * n_cols, 12),
                             squeeze=False, sharex=True)

    color_cycle = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    vd_color = {vd: color_cycle[i % len(color_cycle)] for i, vd in enumerate(vd_steps)}
    dataset_style = {label: _DATASET_STYLES[i % len(_DATASET_STYLES)]
                     for i, (label, _, _) in enumerate(datasets)}

    geom = datasets[0][2]

    for c, vd in enumerate(vd_steps):
        ax_lin, ax_log, ax_res = axes[0][c], axes[1][c], axes[2][c]
        color = vd_color[vd]

        # Reference curve as {vg: id} for residuals.
        ref_map = {}
        if vd in ref_curves:
            rvg, rid = _sorted(*ref_curves[vd])
            rvg, rid = rvg[args.skip_first_points:], rid[args.skip_first_points:]
            ref_map = {round(v, 6): i for v, i in zip(rvg, rid)}

        for label, curves, _ in datasets:
            if vd not in curves:
                continue
            style = dataset_style[label]
            vg, ids = _sorted(*curves[vd])
            vg, ids = vg[args.skip_first_points:], ids[args.skip_first_points:]
            ax_lin.plot(vg, ids, marker=style["marker"], markersize=3.5, linewidth=1.3,
                        linestyle=style["linestyle"], color=color)
            ax_log.plot(vg, [abs(i) for i in ids], marker=style["marker"], markersize=3.5,
                        linewidth=1.3, linestyle=style["linestyle"], color=color)
            if ref_map:
                rvg, res = [], []
                for v, i in zip(vg, ids):
                    ref_i = ref_map.get(round(v, 6))
                    if ref_i is None or ref_i == 0:
                        continue
                    rvg.append(v)
                    res.append((i - ref_i) / ref_i)
                ax_res.plot(rvg, res, marker=style["marker"], markersize=3.5, linewidth=1.3,
                            linestyle=style["linestyle"], color=color)

        ax_lin.set_title(f"Vd = {vd:g} V", fontsize=10)
        ax_log.set_yscale("log")
        for ax in (ax_lin, ax_log, ax_res):
            ax.grid(True, alpha=0.3)
        ax_res.axhline(0.0, color="0.6", lw=0.8)
        ax_res.set_xlabel("Vg (V)", fontsize=9)
        if c == 0:
            ax_lin.set_ylabel("Id (A)", fontsize=9)
            ax_log.set_ylabel("|Id| (A)", fontsize=9)
            ax_res.set_ylabel(f"(Id - Id_ref)/Id_ref\nref = {ref_label}", fontsize=9)

    # Legends: dataset styles and Vd colors.
    style_handles = [
        Line2D([0], [0], color="0.3", marker=dataset_style[label]["marker"],
               linestyle=dataset_style[label]["linestyle"], label=label)
        for label, _, _ in datasets
    ]
    color_handles = [
        Line2D([0], [0], color=vd_color[vd], lw=3, label=f"Vd={vd:g} V")
        for vd in vd_steps
    ]
    fig.legend(handles=style_handles + color_handles, loc="lower center",
               ncol=len(style_handles) + len(color_handles), fontsize=8,
               frameon=False, bbox_to_anchor=(0.5, -0.01))

    fig.suptitle(f"{args.title}\n{_geom_label(geom)}", fontsize=12)
    fig.tight_layout(rect=(0, 0.03, 1, 0.97))
    fig.savefig(args.out, dpi=160)
    plt.close(fig)
    print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()
