"""Relabel off-by-one array-scan CSVs collected before the 2026-11-02 firmware fix.

The pre-fix ``unified_scan_select`` firmware used ``row_bit = base + 1 + row``
and ``col_bit = base + 7 + col``, i.e. the label was one HIGH: a row/col label
N actually selected physical cell N+1. So every device in these CSVs is
mislabeled by -1 in both row and column.

This script, for each target file:
  1. Copies the file verbatim to ``*_OFF_BY_ONE.csv`` (preserving the raw,
     mislabeled data so it's obvious it's not good).
  2. Rewrites the original in place with corrected labels:
       Row_idx -> Row_idx + 1
       Col_idx -> Col_idx + 1
     and recomputes the geometry columns (Flavor_name, w, l, nf) from the new
     indices so the file stays self-consistent (the plotting code reads these
     stored columns). Measurement columns (vg/vd/Vds_meas_V/id/Isupply_*/time_s)
     are left untouched.

Rows that now map past the physical array (row 6, or col 25 for the standard
flavors / col 14 for NMOS_NA) are the "no device selected" dead readings. Their
indices are still incremented so they're clearly out of the valid device map,
and their geometry columns are left blank (no such physical device exists).
"""
from __future__ import annotations

import csv
import shutil
import sys

sys.path.insert(0, "src")

from iv_measure.device_geometry import lookup_geometry  # noqa: E402

TARGET_FILES = [
    "data/array_scan_board1_chip2_nmos_standard.csv",
    "data/array_scan_board1_chip2_nmos_na.csv",
]


def _fmt(x: float | int | None) -> str:
    if x is None:
        return ""
    if isinstance(x, int):
        return str(x)
    return str(x)


def relabel(path: str) -> None:
    backup = path.replace(".csv", "_OFF_BY_ONE.csv")
    shutil.copy2(path, backup)

    with open(backup, newline="", encoding="utf-8") as fin:
        reader = csv.reader(fin)
        header = next(reader)
        col = {name: i for i, name in enumerate(header)}
        out_rows: list[list[str]] = []
        for row in reader:
            flavor_0based = int(row[col["flavor"]])
            new_row = int(row[col["Row_idx"]]) + 1
            new_col = int(row[col["Col_idx"]]) + 1
            geo = lookup_geometry(flavor_0based + 1, new_row, new_col)
            row[col["Row_idx"]] = str(new_row)
            row[col["Col_idx"]] = str(new_col)
            row[col["Flavor_name"]] = geo.flavor_name or ""
            row[col["w"]] = _fmt(geo.width_m)
            row[col["l"]] = _fmt(geo.length_m)
            row[col["nf"]] = _fmt(geo.nf)
            out_rows.append(row)

    with open(path, "w", newline="", encoding="utf-8") as fout:
        writer = csv.writer(fout)
        writer.writerow(header)
        writer.writerows(out_rows)

    print(f"{path}: relabeled {len(out_rows)} rows (+1 row/col); backup -> {backup}")


def main() -> None:
    for path in TARGET_FILES:
        relabel(path)


if __name__ == "__main__":
    main()
