"""device_geometry.py -- W / L / number-of-fingers for each (flavor, row, col).

Lets automation stamp the physical geometry of the device under test onto its
saved plot. Row index selects W; column index selects (L, nf).

SOURCE: CLAUDE.md Section 2.2, which transcribes datasheet Figures 3-6 (standard
arrays) and 9-10 (native array). Section 1 of CLAUDE.md notes these geometry
figures DO apply to this modified chip (unlike the datasheet's chain map). The
figure tables themselves are images in the PDF and cannot be text-extracted, so
these values come from the brief's transcription; verify against the figures if
a number is ever in doubt.

OPEN QUESTIONS (CLAUDE.md 2.2 -- flagged, NOT resolved by assumption here):
  * whether W is per-finger or total width;
  * the DNW array's multi-finger dimensions (datasheet 2.1.3 contradicts
    itself). We treat DNW (flavor 6) as a standard array per its "exact same
    pattern" statement, and mark it uncertain in the returned notes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import device_registry

# --- Standard arrays (all flavors except native = flavor 4) --------------------
# Rows 0..5 -> W in micrometres.
STD_W_UM = [0.1, 0.2, 0.4, 0.8, 1.6, 3.0]
# Cols 0..6: single finger (nf=1), L in nm.
STD_SINGLE_L_NM = [30, 40, 60, 90, 200, 500, 1000]
# Cols 7..24: multi-finger, grouped by L with nf = 2,4,8 within each group.
# L(nm) = 30 (7-9), 40 (10-12), 60 (13-15), 90 (16-18), 500 (19-21), 1000 (22-24).
# NOTE: no L=200 multi-finger group (CLAUDE.md 2.2).
STD_MULTI_L_NM = [30, 40, 60, 90, 500, 1000]
STD_MULTI_NF = [2, 4, 8]

# --- Native array (flavor 4): 14 columns, different sizing (CLAUDE.md 2.2) -----
NAT_W_UM = [0.5, 0.75, 1.0, 1.5, 2.0, 2.5]
NAT_SINGLE_L_NM = [300, 500, 600, 900, 1000]      # cols 0..4, nf=1
NAT_MULTI_L_NM = [300, 500, 1000]                 # cols 5..13, x nf=2,4,8
NAT_MULTI_NF = [2, 4, 8]

# DRC exception: at L = 1 um, W is capped at 2.65 um (CLAUDE.md 2.2). Affects the
# widest row (row 5, W=3) at L=1000 nm columns.
DRC_L_NM = 1000
DRC_W_CAP_UM = 2.65


@dataclass(frozen=True)
class Geometry:
    flavor: int
    row: int
    col: int
    w_um: float          # width in micrometres (see OPEN QUESTION on per-finger)
    l_nm: int            # channel length in nanometres
    nf: int              # number of fingers
    notes: list[str] = field(default_factory=list)  # caveats/flags for this device


def _std_col(col: int) -> tuple[int, int]:
    """(L_nm, nf) for a standard-array column 0..24."""
    if col < 7:
        return STD_SINGLE_L_NM[col], 1
    idx = col - 7
    return STD_MULTI_L_NM[idx // 3], STD_MULTI_NF[idx % 3]


def _native_col(col: int) -> tuple[int, int]:
    """(L_nm, nf) for a native-array column 0..13."""
    if col < 5:
        return NAT_SINGLE_L_NM[col], 1
    idx = col - 5
    return NAT_MULTI_L_NM[idx // 3], NAT_MULTI_NF[idx % 3]


def geometry_of(flavor: int, row: int, col: int) -> Geometry:
    """Return the W/L/nf Geometry for a device, or raise if out of range.

    Bounds are validated through device_registry (single source of truth,
    native = 14 cols per Q4).
    """
    device_registry.validate_flavor(flavor, row, col)
    fl = device_registry.get(flavor)
    notes: list[str] = []

    if fl.subtype == "native":
        w_um = NAT_W_UM[row]
        l_nm, nf = _native_col(col)
    else:
        w_um = STD_W_UM[row]
        l_nm, nf = _std_col(col)
        # DRC cap only applies to standard arrays' L=1um widest devices.
        if l_nm == DRC_L_NM and w_um > DRC_W_CAP_UM:
            notes.append(f"W capped {w_um}->{DRC_W_CAP_UM} um at L=1um (DRC, 2.2)")
            w_um = DRC_W_CAP_UM

    if fl.subtype == "dnw":
        notes.append("DNW multi-finger dims uncertain (datasheet 2.1.3 conflict)")

    return Geometry(flavor, row, col, w_um, l_nm, nf, notes)


def label(flavor: int, row: int, col: int) -> str:
    """One-line human geometry label for annotating a plot image.

    e.g. 'flavor 3 (nmos_mid) | W=0.1um L=30nm nf=1'
    """
    g = geometry_of(flavor, row, col)
    name = device_registry.name_of(flavor)
    text = (f"flavor {flavor} ({name}) | W={g.w_um:g}um L={g.l_nm}nm nf={g.nf}")
    if g.notes:
        text += "  [" + "; ".join(g.notes) + "]"
    return text
