"""flush_analyze.py -- send a pushed SEL and measure the scan chain length.

WHY THIS EXISTS: the two CryoASIC chips are daisy-chained (Arduino SIn ->
Chip1 344 bits -> R1 -> Chip2 -> Sout). A plain 344-cycle shift only fills
chip 1; to reach chip 2 you must keep clocking to PUSH the pattern deeper.
scan_bits.py can only send "SEL f r c" (no push) and I can't edit it, so this
sends "SEL f r c <push>" (the sketch_may26_r4_SEL_PUSH extension) and reads back
the Bit#/SIN/A0 table.

The measurement: inject the one-hot pattern, then watch at which CYCLE each 1
emerges on Sout. The delay from the SIN=1 cycle to the SOUT=1 cycle is the
number of flip-flops between SIn and whichever Sout net A1 taps -- i.e. the
chain length. ~344 => A1 sees chip 1's Sout; ~688 => it sees chip 2's Sout
(and per-chip length = delay - 344).

Reuses run_device_loop.open_scan_arduino (robust Q6 port open). threshold=100
matches the sketch (already proven healthy, Mismatches:2). Read-only: one SEL.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from run_device_loop import open_scan_arduino

THRESHOLD = 100          # matches the sketch's Sout ADC threshold
CHIP1_BITS = 344         # known chip-1 chain length (CLAUDE.md 2.1)


def capture(ser, flavor, row, col, push, timeout_s=60.0):
    """Send the pushed SEL, collect (cycle, sin, sout) rows until SEL_DONE."""
    ser.reset_input_buffer()
    ser.write(f"SEL {flavor} {row} {col} {push}\n".encode())
    rows, raw = [], []
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        line = ser.readline().decode(errors="ignore").rstrip()
        if not line:
            continue
        raw.append(line)
        p = line.split("\t")
        if len(p) >= 3 and p[0].isdigit():
            rows.append((int(p[0]), int(p[1].strip()[0]), int(p[2].strip()[0])))
        if line == "SEL_DONE":
            break
    return rows, raw


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scan-port", required=True)
    ap.add_argument("--flavor", type=int, default=3)
    ap.add_argument("--row", type=int, default=0)
    ap.add_argument("--col", type=int, default=0)
    ap.add_argument("--push", type=int, default=700,
                    help="extra zero-cycles after the 344-bit pattern (default 700)")
    ap.add_argument("--save", action="store_true",
                    help="write the raw table under data/diagnostics_<date>/")
    args = ap.parse_args()

    ser = open_scan_arduino(args.scan_port)
    try:
        print(f"SEL {args.flavor} {args.row} {args.col} push={args.push}")
        rows, raw = capture(ser, args.flavor, args.row, args.col, args.push)
    finally:
        ser.close()

    if not rows:
        print("no Bit#/SIN/A0 rows parsed -- is the _PUSH sketch flashed?")
        return

    sin_ones  = [c for c, s, o in rows if s == 1]
    sout_ones = [c for c, s, o in rows if o == 1]
    print(f"cycles captured: {len(rows)}   SIN=1 at: {sin_ones}   "
          f"SOUT=1 count: {len(sout_ones)}")

    # Emergence delay: for each SOUT=1 cycle, delay from the nearest EARLIER
    # SIN=1 cycle. The dominant delay = chain length SIn -> A1's Sout tap.
    delays = []
    for c in sout_ones:
        earlier = [s for s in sin_ones if s <= c]
        if earlier:
            delays.append(c - max(earlier))
    if delays:
        dom, n = Counter(delays).most_common(1)[0]
        print(f"dominant emergence delay: {dom} cycles ({n} of {len(delays)} 1s)")
    else:
        dom = None

    # Plain verdict.
    print()
    if not sout_ones:
        print("VERDICT: no 1s on Sout in any cycle -> readback path dead "
              "(wiring/threshold) OR chain not propagating. Remove R1 and "
              "retest chip 1 in isolation via its test point.")
    elif dom is None:
        print("VERDICT: 1s on Sout but none preceded by a SIN=1 -> Sout likely "
              "stuck high; check the A1 tap / threshold.")
    elif abs(dom - CHIP1_BITS) <= 12:
        print(f"VERDICT: dominant delay ~{dom} (~344): A1 taps CHIP1_SOut; "
              "chip-1 chain verified; length confirmed 344.")
    else:
        per_chip = dom - CHIP1_BITS
        print(f"VERDICT: dominant delay ~{dom}: A1 taps CHIP2_SOut; combined "
              f"chain length measured = {dom}; per-chip inferred = {per_chip}. "
              f"Use push={per_chip} (or {dom}) to configure chip 2.")

    # First-344 drain-out: nonzero here after a prior SEL hints reset is weak.
    early_ones = [c for c, s, o in rows if c < CHIP1_BITS and o == 1]
    if early_ones:
        print(f"\nNOTE: {len(early_ones)} SOUT=1 in the first 344 cycles "
              f"(drain-out) at {early_ones[:20]}"
              f"{' ...' if len(early_ones) > 20 else ''}. If this run followed "
              "another SEL, reset may be leaving prior contents -- re-run once "
              "more from a fresh reset to confirm.")

    if args.save:
        out = Path("data") / f"diagnostics_{date.today().isoformat()}" / \
            f"flush_f{args.flavor}r{args.row}c{args.col}_push{args.push}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(raw))
        print(f"\nraw table saved -> {out}")


if __name__ == "__main__":
    main()
