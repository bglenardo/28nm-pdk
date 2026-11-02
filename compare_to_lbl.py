"""Compare measured device curves against the LBL 300 K reference data.

Overlays our scan output (LBL-format CSV written by ``run_routine_automated_scan.py``)
against the LBL reference measurements for the same physical device(s), so we can
sanity-check that we are in the right ballpark.

Both CSVs share the LBL column layout::

    flavor, Row_idx, Col_idx, Flavor_name, w, l, nf, vg, vd, Vds_meas_V,
    id, id_2, time_s

For every (flavor, Row_idx, Col_idx) device present in our scan, the script finds
the matching device in the reference file and plots ``id`` vs ``vd`` grouped by
the gate step ``vg`` -- ours as solid lines with markers, the LBL reference as
dashed lines. One subplot per device; the figure is saved to a PNG.

Usage::

    python compare_to_lbl.py \
        --measured data/array_scan_300K_check.csv \
        --reference "LBL_setup/Will reference data 300K/20260818_194845.csv" \
        --out data/compare_to_lbl_300K.png
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt


# LBL-format column names shared by both the measured and reference CSVs.
_FLAVOR = "flavor"
_ROW = "Row_idx"
_COL = "Col_idx"
_FLAVOR_NAME = "Flavor_name"
_W = "w"
_L = "l"
_NF = "nf"
_VG = "vg"
_VD = "vd"
_ID = "id"

DeviceKey = tuple[str, str, str]  # (flavor, Row_idx, Col_idx) as raw strings.


def _load_lbl_csv(path: Path) -> dict[DeviceKey, dict]:
    """Group an LBL-format CSV by device, then by gate-step voltage.

    Returns ``{(flavor, row, col): {"name": str, "w": str, "l": str, "nf": str,
    "curves": {vg: ([vd], [id])}}}``. The vd/id lists preserve file order (the
    sweep order).
    """
    if not path.exists():
        raise FileNotFoundError(f"Missing CSV: {path}")

    devices: dict[DeviceKey, dict] = {}
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            key = (raw[_FLAVOR].strip(), raw[_ROW].strip(), raw[_COL].strip())
            device = devices.get(key)
            if device is None:
                device = {
                    "name": (raw.get(_FLAVOR_NAME) or "").strip(),
                    "w": (raw.get(_W) or "").strip(),
                    "l": (raw.get(_L) or "").strip(),
                    "nf": (raw.get(_NF) or "").strip(),
                    "curves": defaultdict(lambda: ([], [])),
                }
                devices[key] = device

            try:
                vg = round(float(raw[_VG]), 6)
                vd = float(raw[_VD])
                ids = float(raw[_ID])
            except (TypeError, ValueError):
                continue

            vd_list, id_list = device["curves"][vg]
            vd_list.append(vd)
            id_list.append(ids)

    return devices


def _sorted_curve(vd_list: list[float], id_list: list[float]) -> tuple[list[float], list[float]]:
    """Return the (vd, id) pair sorted by ascending vd for clean line plots."""
    paired = sorted(zip(vd_list, id_list), key=lambda p: p[0])
    if not paired:
        return [], []
    vds, ids = zip(*paired)
    return list(vds), list(ids)


# Display-only y-axis window. Points outside this window are dropped before
# plotting so a stray spike does not draw a vertical connecting segment to the
# axis edge. The underlying CSV data is left untouched.
Y_DISPLAY_MIN = -0.00003
Y_DISPLAY_MAX = 0.00038


def _clip_curve(
    vd_list: list[float], id_list: list[float]
) -> tuple[list[float], list[float]]:
    """Drop (vd, id) points whose current falls outside the display window."""
    kept = [
        (vd, ids)
        for vd, ids in zip(vd_list, id_list)
        if Y_DISPLAY_MIN <= ids <= Y_DISPLAY_MAX
    ]
    if not kept:
        return [], []
    vds, ids = zip(*kept)
    return list(vds), list(ids)



def _format_geometry(device: dict) -> str:
    """Build a 'L=.. W=.. nf=..' label line from the device geometry fields.

    Lengths/widths are stored in meters in the LBL format; render them in
    nanometers/micrometers as appropriate for readability. Falls back to the raw
    string if a value cannot be parsed as a float.
    """

    def _len(text: str) -> str:
        try:
            meters = float(text)
        except (TypeError, ValueError):
            return text or "?"
        nm = meters * 1e9
        if nm < 1000:
            return f"{nm:g} nm"
        return f"{meters * 1e6:g} \u00b5m"

    def _nf(text: str) -> str:
        try:
            return f"{int(float(text))}"
        except (TypeError, ValueError):
            return text or "?"

    return f"L={_len(device.get('l', ''))}  W={_len(device.get('w', ''))}  nf={_nf(device.get('nf', ''))}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--measured",
        default="data/array_scan_300K_check.csv",
        help="Path to our measured LBL-format scan CSV.",
    )
    parser.add_argument(
        "--measured2",
        default=None,
        help="Optional path to a second measured LBL-format scan CSV (e.g. a "
        "different chip), overlaid with a different marker.",
    )
    parser.add_argument(
        "--reference",
        default="LBL_setup/Will reference data 300K/20260818_194845.csv",
        help="Path to the LBL reference CSV (300 K).",
    )
    parser.add_argument(
        "--out",
        default="data/compare_to_lbl_300K.png",
        help="Output PNG path for the comparison figure.",
    )
    parser.add_argument(
        "--board",
        type=int,
        default=1,
        help="Board number shown in the figure title (default: 1).",
    )
    parser.add_argument(
        "--chip",
        type=int,
        default=1,
        help="Chip number for the first measured dataset (default: 1).",
    )
    parser.add_argument(
        "--chip2",
        type=int,
        default=2,
        help="Chip number for the second measured dataset (default: 2).",
    )
    args = parser.parse_args()

    measured = _load_lbl_csv(Path(args.measured))
    measured2 = _load_lbl_csv(Path(args.measured2)) if args.measured2 else {}
    reference = _load_lbl_csv(Path(args.reference))

    if not measured:
        raise ValueError(f"No device rows found in measured CSV: {args.measured}")

    # Arrange devices in a grid: one plot row per device Row_idx, one plot column
    # per device Col_idx. Sort numerically where possible so the panels read in a
    # natural order.
    def _as_num(text: str) -> float:
        try:
            return float(text)
        except ValueError:
            return float("inf")

    all_keys = set(measured) | set(measured2)
    device_rows = sorted({key[1] for key in all_keys}, key=_as_num)
    device_cols = sorted({key[2] for key in all_keys}, key=_as_num)
    n_rows = len(device_rows)
    n_cols = len(device_cols)

    # Share the y-axis across the three panels in each device row for easy
    # magnitude comparison, while letting different device rows keep their own
    # y-scale (row 0 and row 1 have different widths / current levels).
    fig, axes = plt.subplots(
        n_rows,
        n_cols,
        figsize=(6 * n_cols, 5 * n_rows),
        squeeze=False,
        sharey="row",
    )

    color_cycle = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    for r, dev_row in enumerate(device_rows):
        for c, dev_col in enumerate(device_cols):
            ax = axes[r][c]

            # Find the measured device matching this (row, col); flavor is shared.
            key = next((k for k in all_keys if k[1] == dev_row and k[2] == dev_col), None)
            if key is None:
                ax.set_axis_off()
                continue

            flavor = key[0]
            meas_device = measured.get(key)
            meas2_device = measured2.get(key)
            ref_device = reference.get(key)

            # First measured dataset (solid, triangle markers).
            if meas_device is not None:
                for i, vg in enumerate(sorted(meas_device["curves"])):
                    vd, ids = _clip_curve(*_sorted_curve(*meas_device["curves"][vg]))
                    ax.plot(
                        vd,
                        ids,
                        marker="^",
                        markersize=4,
                        linewidth=1.6,
                        color=color_cycle[i % len(color_cycle)],
                        label=f"Chip {args.chip} Vg={vg:g}",
                    )

            # Second measured dataset (solid, square markers).
            if meas2_device is not None:
                for i, vg in enumerate(sorted(meas2_device["curves"])):
                    vd, ids = _clip_curve(*_sorted_curve(*meas2_device["curves"][vg]))
                    ax.plot(
                        vd,
                        ids,
                        marker="s",
                        markersize=4,
                        linewidth=1.6,
                        linestyle="-",
                        color=color_cycle[i % len(color_cycle)],
                        label=f"Chip {args.chip2} Vg={vg:g}",
                    )

            # LBL reference curves (dashed, no markers) for the same device.
            if ref_device is not None:
                for i, vg in enumerate(sorted(ref_device["curves"])):
                    vd, ids = _sorted_curve(*ref_device["curves"][vg])
                    ax.plot(
                        vd,
                        ids,
                        linestyle="--",
                        linewidth=1.4,
                        color=color_cycle[i % len(color_cycle)],
                        alpha=0.7,
                        label=f"LBL Vg={vg:g}",
                    )

            name = (
                (meas_device or meas2_device or ref_device or {}).get("name", "")
            )
            ref_note = "" if ref_device is not None else "  (no LBL match)"
            geometry = _format_geometry(meas_device or meas2_device or {})
            ax.set_title(
                f"{name}  flavor={flavor} row={dev_row} col={dev_col}{ref_note}\n{geometry}"
            )
            ax.set_xlabel("Vd (V)")
            # Only label the y-axis on the leftmost panel of each shared-y row.
            if c == 0:
                ax.set_ylabel("Id (A)")
            # Zoom each plot row to a tighter top end for its current level.
            y_max = 0.00032 if r == n_rows - 1 else 0.00018
            ax.set_ylim(Y_DISPLAY_MIN, y_max)
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=8)

    if measured2:
        suptitle = (
            f"Board {args.board} \u2014 SLAC Chip {args.chip} (\u25b2 solid) & "
            f"Chip {args.chip2} (\u25a0 solid) measured at 300 K "
            "vs LBL 300 K reference (dashed)"
        )
    else:
        suptitle = (
            f"Board {args.board}, Chip {args.chip} \u2014 SLAC measured at 300 K (solid) "
            "vs LBL 300 K reference (dashed)"
        )
    fig.suptitle(suptitle)
    fig.tight_layout()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=180)
    print(f"Saved comparison figure: {out_path}")


if __name__ == "__main__":
    main()
