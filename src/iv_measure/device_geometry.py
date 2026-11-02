"""Device-array geometry lookup tables (ported from the LBL automation code).

Maps scan-chain coordinates to the physical device parameters recorded in the
LBL CSV format (``Flavor_name``, ``w``, ``l``, ``nf``).

Index conventions (matching the bench ``unified_scan_select`` firmware):
- ``flavor`` is **1-based** on the wire / CLI (1 = nmos_lvt ... 10 = pmos_hvt),
  which is what gets sent to the Arduino. The LBL CSV ``flavor`` column and the
  ``FLAVOR_TABLE`` below are **0-based**, so ``flavor_0based = flavor - 1``.
- ``row`` and ``col`` are 0-based in both the firmware and the CSV.
- Flavor index 3 (0-based) is ``NMOS_NA`` (native array) and uses the dedicated
  NA width/length tables.
"""

from __future__ import annotations

# 0-based flavor index -> flavor name, matching the LBL CSV ``flavor`` column.
FLAVOR_TABLE: dict[int, str] = {
    0: "NMOS_LVT",
    1: "NMOS_HVT",
    2: "NMOS_MID",
    3: "NMOS_NA",
    4: "NMOS_ULVT",
    5: "NMOS_DNW",
    6: "PMOS_ULVT",
    7: "PMOS_LVT",
    8: "PMOS_MID",
    9: "PMOS_HVT",
}

# Row index -> device width (m).
ROW_TABLE: dict[int, float] = {
    0: 100e-9,
    1: 200e-9,
    2: 400e-9,
    3: 800e-9,
    4: 1600e-9,
    5: 3000e-9,
}

# Column index -> (device length (m), number of fingers).
COL_TABLE: dict[int, tuple[float, int]] = {
    0: (30e-9, 1),
    1: (40e-9, 1),
    2: (60e-9, 1),
    3: (90e-9, 1),
    4: (200e-9, 1),
    5: (500e-9, 1),
    6: (1000e-9, 1),
    7: (30e-9, 2),
    8: (30e-9, 4),
    9: (30e-9, 8),
    10: (40e-9, 2),
    11: (40e-9, 4),
    12: (40e-9, 8),
    13: (60e-9, 2),
    14: (60e-9, 4),
    15: (60e-9, 8),
    16: (90e-9, 2),
    17: (90e-9, 4),
    18: (90e-9, 8),
    19: (500e-9, 2),
    20: (500e-9, 4),
    21: (500e-9, 8),
    22: (1000e-9, 2),
    23: (1000e-9, 4),
    24: (1000e-9, 8),
}

# NMOS_NA (native array) variants -- only 14 columns.
ROW_TABLE_NA: dict[int, float] = {
    0: 500e-9,
    1: 750e-9,
    2: 1000e-9,
    3: 1500e-9,
    4: 2000e-9,
    5: 2500e-9,
}

COL_TABLE_NA: dict[int, tuple[float, int]] = {
    0: (300e-9, 1),
    1: (500e-9, 1),
    2: (600e-9, 1),
    3: (900e-9, 1),
    4: (1000e-9, 1),
    5: (300e-9, 2),
    6: (300e-9, 4),
    7: (300e-9, 8),
    8: (500e-9, 2),
    9: (500e-9, 4),
    10: (500e-9, 8),
    11: (1000e-9, 2),
    12: (1000e-9, 4),
    13: (1000e-9, 8),
}

_NA_FLAVOR_0BASED = 3


class DeviceGeometry:
    """Resolved physical parameters for one scan-chain device."""

    __slots__ = ("flavor_0based", "flavor_name", "width_m", "length_m", "nf")

    def __init__(
        self,
        flavor_0based: int | None,
        flavor_name: str | None,
        width_m: float | None,
        length_m: float | None,
        nf: int | None,
    ) -> None:
        self.flavor_0based = flavor_0based
        self.flavor_name = flavor_name
        self.width_m = width_m
        self.length_m = length_m
        self.nf = nf


def lookup_geometry(
    flavor_1based: int | None,
    row_idx: int | None,
    col_idx: int | None,
) -> DeviceGeometry:
    """Resolve LBL geometry fields from scan-chain coordinates.

    ``flavor_1based`` is the value sent to the Arduino (1..10); the returned
    ``flavor_0based`` and ``flavor_name`` use the LBL 0-based convention. Any
    coordinate that is ``None`` or out of range yields ``None`` for the fields
    that depend on it, so a plain single-device run (no device selection) still
    produces a valid, mostly-empty row.
    """
    if flavor_1based is None:
        return DeviceGeometry(None, None, None, None, None)

    flavor_0based = flavor_1based - 1
    flavor_name = FLAVOR_TABLE.get(flavor_0based)
    is_na = flavor_0based == _NA_FLAVOR_0BASED

    width_m: float | None = None
    if row_idx is not None:
        row_table = ROW_TABLE_NA if is_na else ROW_TABLE
        width_m = row_table.get(row_idx)

    length_m: float | None = None
    nf: int | None = None
    if col_idx is not None:
        col_table = COL_TABLE_NA if is_na else COL_TABLE
        col_entry = col_table.get(col_idx)
        if col_entry is not None:
            length_m, nf = col_entry

    return DeviceGeometry(flavor_0based, flavor_name, width_m, length_m, nf)
