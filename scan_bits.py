"""scan_bits.py -- send a SEL and print the scan chain's SIN vs SOUT bit-by-bit.

Makes the scan read-back visible at a glance: it sends `SEL <flavor> <row> <col>`
to the SEL-patched Arduino, parses the sketch's existing "Bit#  SIN  A0" dump,
and prints three aligned rows per block:

    SIN  = what the Arduino shifted IN (the one-hot selection: two 1s)
    SOUT = what the chip read back (A1 analog > threshold)
    diff = ^ where they differ

Why this exists: the sketch's "Mismatches: N" summary hides the PATTERN. Q1/Q2
say a healthy chain still reports ~2-3 mismatches (same-cycle-compare quirk), so
the count alone is misleading. The SIN/SOUT picture tells you the real story:
  * SOUT all 1s (or all 0s), flat        -> Sout stuck/disconnected (pin 15->A1)
  * SOUT follows a shifted copy of SIN    -> chain shifting, readback alive
  * SOUT = SIN at the two one-hot bits    -> those are the selected row/col bits

Reuses run_device_loop.open_scan_arduino (robust Q6 port open). Read-only w.r.t.
the chip: sends one SEL, changes nothing else. Optionally saves the raw dump.

Usage:
    python scan_bits.py --scan-port COM11 --flavor 3 --row 0 --col 0
    python scan_bits.py --scan-port COM11              # defaults to SEL 3 0 0
    python scan_bits.py --scan-port COM11 --save data/diagnostics/scan.txt
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from run_device_loop import open_scan_arduino

# Sketch prints "Bit#\tSIN\tA0" then 344 rows; it uses reverse order internally,
# but we sort by the printed Bit# and report both printed and logical index.
TOTAL_BITS = 344  # matches sketch TOTAL_BITS


def capture_dump(ser, flavor: int, row: int, col: int,
                 timeout_s: float = 40.0) -> tuple[list[tuple[int, str, str]], list[str]]:
    """Send SEL and collect (bit, sin, sout) rows plus the raw text lines."""
    ser.reset_input_buffer()
    ser.write(f"SEL {flavor} {row} {col}\n".encode())
    rows: list[tuple[int, str, str]] = []
    raw: list[str] = []
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        line = ser.readline().decode(errors="ignore").rstrip()
        if not line:
            continue
        raw.append(line)
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].isdigit():
            # first char of each field -> drop any trailing "<-- MISMATCH" marker
            rows.append((int(parts[0]), parts[1].strip()[0], parts[2].strip()[0]))
        if line == "SEL_DONE":
            break
    rows.sort()
    return rows, raw


def print_bits(rows: list[tuple[int, str, str]], width: int = 50) -> None:
    if not rows:
        print("no bit rows parsed -- did the sketch print the Bit#/SIN/A0 table?")
        return
    n_sin = sum(1 for _, a, _ in rows if a == "1")
    n_sout = sum(1 for _, _, b in rows if b == "1")
    n_mis = sum(1 for _, a, b in rows if a != b)
    print(f"bits: {len(rows)}   SIN=1: {n_sin}   SOUT=1: {n_sout}   "
          f"mismatches: {n_mis}")
    print()
    for start in range(0, len(rows), width):
        chunk = rows[start:start + width]
        print(f"bit {start:3d}: SIN  " + "".join(r[1] for r in chunk))
        print(f"         SOUT " + "".join(r[2] for r in chunk))
        print(f"         diff " + "".join("^" if r[1] != r[2] else "."
                                          for r in chunk))
        print()
    print("SIN=1  at bits:", [b for b, a, _ in rows if a == "1"])
    sout_ones = [b for b, _, c in rows if c == "1"]
    if len(sout_ones) > 20:
        print(f"SOUT=1 at bits: {sout_ones[:20]} ... ({len(sout_ones)} total)")
    else:
        print("SOUT=1 at bits:", sout_ones)
    # Plain-language read of the pattern.
    print()
    if n_sout == len(rows):
        print("=> SOUT stuck HIGH (all 1s): Sout line disconnected/pulled high "
              "or ADC threshold too low. Readback dead (chip pin 15 -> A1).")
    elif n_sout == 0:
        print("=> SOUT stuck LOW (all 0s): Sout not driven / threshold too high.")
    elif n_mis <= 4:
        print("=> readback healthy (<=4 mismatches, Q2 bench norm).")
    else:
        print("=> SOUT has structure but many mismatches: chain may be shifting; "
              "compare the SOUT pattern to a shifted copy of SIN.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scan-port", required=True)
    ap.add_argument("--flavor", type=int, default=3)
    ap.add_argument("--row", type=int, default=0)
    ap.add_argument("--col", type=int, default=0)
    ap.add_argument("--width", type=int, default=50, help="bits per printed block")
    ap.add_argument("--save", help="also write the raw sketch dump to this path")
    args = ap.parse_args()

    ser = open_scan_arduino(args.scan_port)
    try:
        print(f"SEL {args.flavor} {args.row} {args.col}")
        rows, raw = capture_dump(ser, args.flavor, args.row, args.col)
    finally:
        ser.close()

    print_bits(rows, width=args.width)

    if args.save:
        out = Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(raw))
        print(f"\nraw dump saved -> {out}")


if __name__ == "__main__":
    main()
