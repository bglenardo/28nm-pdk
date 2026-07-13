"""device_registry.py -- single source of truth for the chip's device flavors.

Maps the sketch's 1..11 flavor numbers to their type (nmos/pmos), subtype,
column count, and scan-chain base bit, so that automation can DERIVE a device's
polarity from an authoritative source instead of a human guessing a routine
index. This closes the failure exposed on the bench (2026-07-13): an nMOS
routine, with Vg stepped POSITIVE, was run on a pMOS device -> zero gate
modulation, current pinned at the Keithley compliance rail (CLAUDE.md Q8).

GROUND TRUTH (CLAUDE.md Section 1 hierarchy):
  * Flavor numbers, names, column counts, and base bits are transcribed
    VERBATIM from the authoritative r4 sketch's flavor_base[] table:
      Arduino/sketch_may26_r4_copy_20260609150247/...ino:39-56
    (TOTAL_BITS = 344; flavor 4 = nmos_na has 14 columns, all others 25.)
  * The nmos/pmos split is CONFIRMED by the datasheet p.2: eight Vt-variant
    flavors exist for both PMOS and NMOS; the native and deep-N-well arrays
    are both NMOS. The datasheet also fixes the bias convention we route on:
    "Vgx ... slightly below ground for NMOS and slightly above VDD for PMOS
    ... separate Vgxn, Vgxp pads."
  * Sketch and datasheet do NOT conflict on the type mapping (Phase A
    discrepancy check: zero mismatches).

This module is PURE: no hardware, no I/O. Import and call.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

NMOS = "nmos"
PMOS = "pmos"


@dataclass(frozen=True)
class Flavor:
    number: int   # the sketch's 1..11 flavor number (SEL <flavor> <row> <col>)
    name: str     # human name, from the sketch's flavor_base[] comments
    kind: str     # NMOS or PMOS -- determines routine polarity
    subtype: str  # "standard" | "native" | "dnw"
    cols: int     # column count (0..cols-1 valid); native (flavor 4) = 14
    base: int     # scan-chain base bit (for cross-checking against the sketch)


# Transcribed from sketch flavor_base[] (…ino:39-51) + flavor_cols() (…ino:54-56).
# kind/subtype confirmed against datasheet p.2. Do NOT edit without re-checking
# the sketch -- the sketch is ground truth (CLAUDE.md Section 1).
FLAVORS: dict[int, Flavor] = {
    1:  Flavor(1,  "nmos_lvt",   NMOS, "standard", 25, 0),
    2:  Flavor(2,  "nmos_hvt",   NMOS, "standard", 25, 32),
    3:  Flavor(3,  "nmos_mid",   NMOS, "standard", 25, 64),   # "mid" = regular Vt
    4:  Flavor(4,  "nmos_na",    NMOS, "native",   14, 96),   # NATIVE: 14 cols (Q4)
    5:  Flavor(5,  "nmos_ulvt",  NMOS, "standard", 25, 120),
    6:  Flavor(6,  "nmos_dnw",   NMOS, "dnw",      25, 152),  # deep n-well; usable Vb
    7:  Flavor(7,  "pmos_ulvt",  PMOS, "standard", 25, 184),
    8:  Flavor(8,  "pmos_lvt",   PMOS, "standard", 25, 216),
    9:  Flavor(9,  "pmos_mid",   PMOS, "standard", 25, 248),
    10: Flavor(10, "pmos_hvt",   PMOS, "standard", 25, 280),
    11: Flavor(11, "pmos_lvt_b", PMOS, "standard", 25, 312),  # genuine 2nd pmos_lvt
}

ROWS = 6  # rows 0..5 in every array (CLAUDE.md Section 2.1)


def get(flavor: int) -> Flavor:
    """Return the Flavor record, or raise with the valid range."""
    try:
        return FLAVORS[flavor]
    except KeyError:
        raise ValueError(
            f"unknown flavor {flavor}; valid flavors are 1..{len(FLAVORS)}"
        ) from None


def kind_of(flavor: int) -> str:
    """NMOS or PMOS -- the property that decides routine polarity."""
    return get(flavor).kind


def name_of(flavor: int) -> str:
    """Human flavor name, e.g. 'nmos_mid' (used for output directory names)."""
    return get(flavor).name


def max_col(flavor: int) -> int:
    """Number of columns; native array (flavor 4) has 14, all others 25 (Q4)."""
    return get(flavor).cols


def is_pmos(flavor: int) -> bool:
    return get(flavor).kind == PMOS


def validate_flavor(flavor: int, row: int, col: int) -> None:
    """Raise ValueError unless (flavor, row, col) is a real device on this chip.

    Enforces the native-array 14-column bound (CLAUDE.md Q4) via the registry
    rather than a magic number, so there is one source of truth for bounds.
    """
    fl = get(flavor)  # raises on bad flavor number
    if not (0 <= row < ROWS):
        raise ValueError(
            f"row {row} out of range for {fl.name} (valid 0..{ROWS - 1})"
        )
    if not (0 <= col < fl.cols):
        raise ValueError(
            f"col {col} out of range for {fl.name} (valid 0..{fl.cols - 1}"
            + (" -- native array has only 14 columns, Q4)" if fl.subtype == "native"
               else ")")
        )


def routine_file_for(flavor: int, *, nmos_path: str | Path,
                     pmos_path: str | Path) -> Path:
    """Return the correct-polarity routine CSV path for this flavor's kind.

    This is the routing decision that prevents an nMOS sweep from landing on a
    pMOS device (the 2026-07-13 bench failure): pMOS flavors get the pMOS
    routine file (negative Vd sweep), nMOS flavors get the nMOS file.
    """
    return Path(pmos_path if is_pmos(flavor) else nmos_path)
