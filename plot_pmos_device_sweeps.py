"""PMOS-aware diagnostic row/column sweep plots from an LBL-format scan CSV.

Mirrors plot_device_sweeps.py (row sweep = width scaling at fixed column; column
sweep = length/finger scaling at fixed row), but re-references the axes to true
PMOS device biases. The Keithley LO (source) is tied to +0.9 V for PMOS, so:

    V_GS = vg - 0.9    (vg 0..0.9  -> V_GS -0.9..0)
    V_DS = vd - 0.9    (vd 0..0.9  -> V_DS -0.9..0)

and Id is negative (source->drain). Panels are coloured by V_GS.

Usage::

    python plot_pmos_device_sweeps.py \
        --measured data/array_scan_board1_chip2_PMOS_ULVT_vdsweep_175K.csv \
        --flavors PMOS_ULVT --row-sweep-col 0 --col-sweep-row 5 --out-dir plots
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, "src")

import matplotlib.pyplot as plt
from matplotlib import cm, colors

from compare_to_lbl import _load_lbl_csv, _sorted_curve
from iv_measure.device_geometry import (
    COL_TABLE,
    COL_TABLE_NA,
    FLAVOR_TABLE,
    ROW_TABLE,
    ROW_TABLE_NA,
    _NA_FLAVOR_0BASED,
)

# Source rail the LO is tied to for PMOS; used to re-reference vg/vd.
_SOURCE_REF_V = 0.9

_NAME_TO_FLAVOR0 = {name: idx for idx, name in FLAVOR_TABLE.items()}


def _resolve_flavor0(token: str) -> int:
    token = token.strip()
    if token in _NAME_TO_FLAVOR0:
        return _NAME_TO_FLAVOR0[token]
    try:
        idx = int(token)
    except ValueError as exc:
        raise ValueError(
            f"Unknown flavor '{token}'. Use a name (e.g. PMOS_ULVT) or 0-based index."
        ) from exc
    if idx not in FLAVOR_TABLE:
        raise ValueError(f"Flavor index {idx} is out of range 0..{max(FLAVOR_TABLE)}.")
    return idx


def _grid_shape(n: int) -> tuple[int, int]:
    if n <= 0:
        return 1, 1
    cols = int(n ** 0.5)
    if cols * cols < n:
        cols += 1
    rows = (n + cols - 1) // cols
    return rows, cols


def _vgs_color_map(devices: dict, keys: list[tuple[str, str, str]]):
    """Build a stable V_GS -> colour map across every curve in the figure."""
    vgs: set[float] = set()
    for key in keys:
        dev = devices.get(key)
        if dev is None:
            continue
        vgs.update(dev["curves"].keys())
    ordered = sorted(vgs)
    if not ordered:
        return {}, None
    vgs_vals = [vg - _SOURCE_REF_V for vg in ordered]
    norm = colors.Normalize(vmin=min(vgs_vals), vmax=max(vgs_vals))
    cmap = plt.get_cmap("viridis")
    return {vg: cmap(norm(vg - _SOURCE_REF_V)) for vg in ordered}, (cmap, norm)


def _plot_panel(ax, device: dict | None, vgs_colors: dict, title: str) -> None:
    ax.set_title(title, fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.axhline(0.0, color="0.7", lw=0.6)
    if device is None:
        ax.text(0.5, 0.5, "no data", ha="center", va="center", transform=ax.transAxes,
                fontsize=8, color="0.5")
        return
    for vg in sorted(device["curves"].keys()):
        vd_list, id_list = device["curves"][vg]
        vd, ids = _sorted_curve(vd_list, id_list)
        if not vd:
            continue
        vds = [v - _SOURCE_REF_V for v in vd]
        ax.plot(vds, ids, color=vgs_colors.get(vg, "0.3"), lw=1.0)
    ax.set_xlabel("$V_{DS}$ (V)", fontsize=7)
    ax.set_ylabel("$I_D$ (A)", fontsize=7)
    ax.tick_params(labelsize=6)


def _describe_col(flavor0: int, col: int) -> str:
    table = COL_TABLE_NA if flavor0 == _NA_FLAVOR_0BASED else COL_TABLE
    entry = table.get(col)
    if entry is None:
        return f"col {col}"
    length_m, nf = entry
    return f"col {col}: L={length_m * 1e9:g} nm, nf={nf}"


def _describe_row(flavor0: int, row: int) -> str:
    table = ROW_TABLE_NA if flavor0 == _NA_FLAVOR_0BASED else ROW_TABLE
    width_m = table.get(row)
    if width_m is None:
        return f"row {row}"
    return f"row {row}: W={width_m * 1e9:g} nm"


def _figure_add_legend(fig, legend_info) -> None:
    if legend_info is None:
        return
    cmap, norm = legend_info
    sm = cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=fig.axes, fraction=0.025, pad=0.02)
    cbar.set_label("$V_{GS}$ (V)")


def _make_sweep_figure(
    devices: dict,
    flavor0: int,
    flavor_name: str,
    *,
    sweep: str,
    fixed_index: int,
    panel_indices: list[int],
    board: int,
    chip: int,
    out_path: Path,
) -> bool:
    if sweep == "row":
        keys = [(str(flavor0), str(idx), str(fixed_index)) for idx in panel_indices]
        panel_titles = [_describe_row(flavor0, idx) for idx in panel_indices]
        fixed_desc = _describe_col(flavor0, fixed_index)
        sweep_label = "Row (width) sweep"
    else:
        keys = [(str(flavor0), str(fixed_index), str(idx)) for idx in panel_indices]
        panel_titles = [_describe_col(flavor0, idx) for idx in panel_indices]
        fixed_desc = _describe_row(flavor0, fixed_index)
        sweep_label = "Column (length/nf) sweep"

    if not any(key in devices for key in keys):
        print(f"  [skip] {flavor_name} {sweep} sweep: no matching devices in CSV.")
        return False

    vgs_colors, legend_info = _vgs_color_map(devices, keys)

    n = len(keys)
    nrows, ncols = _grid_shape(n)
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(3.0 * ncols, 2.6 * nrows), squeeze=False, constrained_layout=True
    )
    flat_axes = [ax for row in axes for ax in row]

    for ax, key, title in zip(flat_axes, keys, panel_titles):
        _plot_panel(ax, devices.get(key), vgs_colors, title)

    for ax in flat_axes[n:]:
        ax.axis("off")

    fig.suptitle(
        f"Board {board} \u2014 Chip {chip} \u2014 {flavor_name} (PMOS, 175 K)\n"
        f"{sweep_label} at fixed {fixed_desc}",
        fontsize=11,
    )
    _figure_add_legend(fig, legend_info)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  wrote {out_path}")
    return True


def _column_indices_for_flavor(flavor0: int) -> list[int]:
    table = COL_TABLE_NA if flavor0 == _NA_FLAVOR_0BASED else COL_TABLE
    return sorted(table.keys())


def _row_indices_for_flavor(flavor0: int) -> list[int]:
    table = ROW_TABLE_NA if flavor0 == _NA_FLAVOR_0BASED else ROW_TABLE
    return sorted(table.keys())


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--measured",
        default="data/array_scan_board1_chip2_PMOS_ULVT_vdsweep_175K.csv",
        help="Path to the measured LBL-format PMOS scan CSV.",
    )
    parser.add_argument(
        "--flavors",
        default="PMOS_ULVT",
        help="Comma list of flavor names or 0-based indices (default: PMOS_ULVT).",
    )
    parser.add_argument("--row-sweep-col", type=int, default=0)
    parser.add_argument("--col-sweep-row", type=int, default=5)
    parser.add_argument("--out-dir", default="plots")
    parser.add_argument("--board", type=int, default=1)
    parser.add_argument("--chip", type=int, default=2)
    args = parser.parse_args()

    devices = _load_lbl_csv(Path(args.measured))
    if not devices:
        raise ValueError(f"No device rows found in CSV: {args.measured}")

    out_dir = Path(args.out_dir)
    stem = Path(args.measured).stem

    for token in args.flavors.split(","):
        token = token.strip()
        if not token:
            continue
        flavor0 = _resolve_flavor0(token)
        flavor_name = FLAVOR_TABLE[flavor0]
        print(f"{flavor_name} (flavor0={flavor0}):")

        row_indices = _row_indices_for_flavor(flavor0)
        col_indices = _column_indices_for_flavor(flavor0)

        _make_sweep_figure(
            devices,
            flavor0,
            flavor_name,
            sweep="row",
            fixed_index=args.row_sweep_col,
            panel_indices=row_indices,
            board=args.board,
            chip=args.chip,
            out_path=out_dir / f"{stem}_{flavor_name}_rowsweep_col{args.row_sweep_col}.png",
        )
        _make_sweep_figure(
            devices,
            flavor0,
            flavor_name,
            sweep="col",
            fixed_index=args.col_sweep_row,
            panel_indices=col_indices,
            board=args.board,
            chip=args.chip,
            out_path=out_dir / f"{stem}_{flavor_name}_colsweep_row{args.col_sweep_row}.png",
        )


if __name__ == "__main__":
    main()
