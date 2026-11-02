"""Compare measured device curves across settle-time (or other) scan runs.

Unlike ``compare_to_lbl.py`` this script does **not** overlay the LBL reference.
Instead it overlays two or more of our own scans (e.g. the same devices measured
with different ``--ids-settle-s`` values) and lays the figure out as a grid:

    * one plot **column per device** (sorted by flavor, Row_idx, Col_idx), and
    * three plot **rows**:
        1. ``Id`` vs ``Vd`` on a linear scale,
        2. ``Id`` vs ``Vd`` on a log scale (``|Id|``), and
        3. fractional residuals ``(Id - Id_ref) / Id_ref`` vs ``Vd``, using one
          chosen dataset as the reference (default: the first dataset).

Each dataset is given a label and drawn with its own marker/linestyle; gate
steps (``vg``) are distinguished by color so the same ``Vg`` shares a color
across every dataset and every panel.

The input CSVs use the LBL column layout written by
``run_routine_automated_scan.py``::

    flavor, Row_idx, Col_idx, Flavor_name, w, l, nf, vg, vd, Vds_meas_V,
    id, id_2, time_s

Usage::

    python compare_settle_times.py \
        --dataset "1.0 s=data/array_scan_board1_chip2.csv" \
        --dataset "0.3 s=data/array_scan_board1_chip2_settle0p3.csv" \
        --dataset "0.1 s=data/array_scan_board1_chip2_settle0p1.csv" \
        --reference-label "1.0 s" \
        --out data/compare_settle_times_chip2.png

The underlying CSV data is never modified; this is a visualization-only tool.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from compare_to_lbl import _format_geometry, _load_lbl_csv, _sorted_curve


# Markers / linestyles cycled per dataset so overlaid runs stay distinguishable.
_DATASET_STYLES = [
    {"marker": "^", "linestyle": "-"},
    {"marker": "s", "linestyle": "--"},
    {"marker": "o", "linestyle": ":"},
    {"marker": "D", "linestyle": "-."},
]


def _parse_dataset(spec: str) -> tuple[str, Path]:
    """Parse a ``label=path`` dataset spec into ``(label, Path)``."""
    if "=" not in spec:
        raise argparse.ArgumentTypeError(
            f"--dataset must be 'label=path', got: {spec!r}"
        )
    label, _, path = spec.partition("=")
    label = label.strip()
    path = path.strip()
    if not label or not path:
        raise argparse.ArgumentTypeError(
            f"--dataset must be 'label=path', got: {spec!r}"
        )
    return label, Path(path)


def _curve_at(device: dict, vg: float) -> dict[float, float]:
    """Return a ``{vd: id}`` map for one device/gate-step, sorted by vd."""
    vd, ids = _sorted_curve(*device["curves"][vg])
    return {round(v, 6): i for v, i in zip(vd, ids)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dataset",
        action="append",
        required=True,
        metavar="LABEL=PATH",
        help="A labelled scan CSV, e.g. '1.0 s=data/array_scan.csv'. Repeat for "
        "each run to overlay.",
    )
    parser.add_argument(
        "--reference-label",
        default=None,
        help="Label of the dataset used as the residual reference. Defaults to "
        "the first --dataset given.",
    )
    parser.add_argument(
        "--out",
        default="data/compare_settle_times.png",
        help="Output PNG path for the comparison figure.",
    )
    parser.add_argument(
        "--title",
        default="Settle-time comparison",
        help="Figure suptitle prefix.",
    )
    args = parser.parse_args()

    datasets: list[tuple[str, dict]] = []
    for spec in args.dataset:
        label, path = _parse_dataset(spec)
        datasets.append((label, _load_lbl_csv(path)))

    if not datasets:
        raise ValueError("No datasets given.")

    ref_label = args.reference_label or datasets[0][0]
    ref_lookup = {label: data for label, data in datasets}
    if ref_label not in ref_lookup:
        raise ValueError(
            f"--reference-label {ref_label!r} is not one of the dataset labels: "
            f"{list(ref_lookup)}"
        )
    ref_data = ref_lookup[ref_label]

    # Device columns: only devices present in *every* dataset (so each column
    # has a complete set of curves to overlay and residual against).
    def _as_num(text: str) -> float:
        try:
            return float(text)
        except ValueError:
            return float("inf")

    common_keys = set(datasets[0][1])
    for _, data in datasets[1:]:
        common_keys &= set(data)
    device_keys = sorted(
        common_keys, key=lambda k: (_as_num(k[0]), _as_num(k[1]), _as_num(k[2]))
    )
    n_dev = len(device_keys)
    if n_dev == 0:
        raise ValueError("No devices are shared across all datasets.")

    # 3 rows (linear, log, residual) x one column per device.
    fig, axes = plt.subplots(
        3,
        n_dev,
        figsize=(6 * n_dev, 13),
        squeeze=False,
        sharex=True,
    )

    color_cycle = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    # Stable color per gate step across the whole figure.
    all_vgs = set()
    for _, data in datasets:
        for key in device_keys:
            dev = data.get(key)
            if dev is not None:
                all_vgs.update(dev["curves"])
    vg_sorted = sorted(all_vgs)
    vg_color = {vg: color_cycle[i % len(color_cycle)] for i, vg in enumerate(vg_sorted)}
    dataset_style = {
        label: _DATASET_STYLES[i % len(_DATASET_STYLES)]
        for i, (label, _) in enumerate(datasets)
    }

    for c, key in enumerate(device_keys):
        ax_lin = axes[0][c]
        ax_log = axes[1][c]
        ax_res = axes[2][c]

        # Pick a representative device dict for the title / geometry.
        rep = next(
            (data.get(key) for _, data in datasets if data.get(key) is not None),
            None,
        )
        name = (rep or {}).get("name", "")
        geometry = _format_geometry(rep or {})
        flavor, dev_row, dev_col = key

        for label, data in datasets:
            dev = data.get(key)
            if dev is None:
                continue
            style = dataset_style[label]
            for vg in sorted(dev["curves"]):
                vd, ids = _sorted_curve(*dev["curves"][vg])
                color = vg_color.get(vg, "gray")
                ax_lin.plot(
                    vd,
                    ids,
                    marker=style["marker"],
                    markersize=3.5,
                    linewidth=1.3,
                    linestyle=style["linestyle"],
                    color=color,
                )
                # Log panel: plot |Id| so sub-threshold detail is visible.
                ax_log.plot(
                    vd,
                    [abs(i) for i in ids],
                    marker=style["marker"],
                    markersize=3.5,
                    linewidth=1.3,
                    linestyle=style["linestyle"],
                    color=color,
                )

                # Residual vs the reference dataset (skip the reference itself).
                if label == ref_label:
                    continue
                ref_dev = ref_data.get(key)
                if ref_dev is None or vg not in ref_dev["curves"]:
                    continue
                ref_map = _curve_at(ref_dev, vg)
                res_vd = []
                res_dy = []
                for v, i in zip(vd, ids):
                    ref_i = ref_map.get(round(v, 6))
                    if ref_i is None or ref_i == 0:
                        continue
                    res_vd.append(v)
                    res_dy.append((i - ref_i) / ref_i)
                ax_res.plot(
                    res_vd,
                    res_dy,
                    marker=style["marker"],
                    markersize=3.5,
                    linewidth=1.3,
                    linestyle=style["linestyle"],
                    color=color,
                )

        ax_res.axhline(0.0, color="k", linewidth=0.8, alpha=0.5)

        ax_lin.set_title(
            f"{name}  flavor={flavor} row={dev_row} col={dev_col}\n{geometry}"
        )
        ax_log.set_yscale("log")
        ax_res.set_xlabel("Vd (V)")
        for ax in (ax_lin, ax_log, ax_res):
            ax.grid(True, alpha=0.3)

        if c == 0:
            ax_lin.set_ylabel("Id (A) — linear")
            ax_log.set_ylabel("|Id| (A) — log")
            ax_res.set_ylabel(f"(Id − Id[{ref_label}]) / Id[{ref_label}]")

    # Build a combined legend: colors = Vg, markers = dataset label.
    vg_handles = [
        Line2D([0], [0], color=vg_color[vg], linewidth=2, label=f"Vg={vg:g}")
        for vg in vg_sorted
    ]
    ds_handles = [
        Line2D(
            [0],
            [0],
            color="k",
            marker=dataset_style[label]["marker"],
            linestyle=dataset_style[label]["linestyle"],
            markersize=5,
            label=label + (" (ref)" if label == ref_label else ""),
        )
        for label, _ in datasets
    ]
    fig.legend(
        handles=vg_handles + ds_handles,
        loc="upper center",
        ncol=len(vg_handles) + len(ds_handles),
        fontsize=9,
        frameon=False,
        bbox_to_anchor=(0.5, 0.985),
    )

    fig.suptitle(
        f"{args.title} — residuals relative to '{ref_label}' "
        "(linear / log / residual)",
        y=1.0,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=180)
    print(f"Saved comparison figure: {out_path}")


if __name__ == "__main__":
    main()
