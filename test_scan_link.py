"""test_scan_link.py -- 60-second pre-flight for the SEL-patched Arduino.

Run this BEFORE run_device_loop.py, with NO instruments needed (scan chain
only, chip powered). Drop in the repo root next to run_device_loop.py.

    python test_scan_link.py --scan-port COM8

Checks, in order:
  1. READY banner appears after port-open (patched sketch is flashed).
  2. PING -> PONG (command parser is alive).
  3. SEL 3 0 0 (nmos_mid, row 0, col 0) completes, and the sketch's own
     verification report shows Mismatches <= 2.
     REMINDER: exactly 2 mismatches + "Test Failed" is the EXPECTED result
     on a healthy chain (the sketch's same-cycle check flags the two one-hot
     bits). 0 would mean the comparison saw nothing at all; >2 means a real
     problem (Sout threshold, wiring, chip power).
  4. SEL of a second device (3 0 1) also completes -- proves repeat
     selections work without re-flashing or power cycling.

Exit code 0 = ready for run_device_loop.py.
"""
from __future__ import annotations

import argparse
import sys
import time

import serial


def wait_for(ser: serial.Serial, token: str, timeout_s: float,
             capture: dict | None = None) -> bool:
    """Read lines until one equals `token`; optionally capture Mismatches."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        line = ser.readline().decode(errors="ignore").strip()
        if not line:
            continue
        print(f"    arduino: {line}")
        if capture is not None and line.startswith("Mismatches:"):
            capture["mismatches"] = int(line.split(":")[1])
        if line == token:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan-port", required=True)
    args = ap.parse_args()

    print("[1/4] opening port (Arduino auto-resets)...")
    ser = serial.Serial(args.scan_port, 115200, timeout=5)
    time.sleep(2.0)
    if not wait_for(ser, "READY", 15):
        print("FAIL: no READY. Is sketch_may26_r4_SEL flashed? Right port? "
              "(The ORIGINAL sketch prints 'start' then hangs -- if you saw "
              "'start' and a scan report but no READY, the old firmware is "
              "still on the board.)")
        return 1
    print("PASS")

    print("[2/4] PING...")
    ser.write(b"PING\n")
    if not wait_for(ser, "PONG", 5):
        print("FAIL: no PONG -- parser not responding.")
        return 1
    print("PASS")

    for step, (r, c) in (("3/4", (0, 0)), ("4/4", (0, 1))):
        print(f"[{step}] SEL 3 {r} {c}  (nmos_mid r{r}c{c})...")
        cap: dict = {}
        ser.write(f"SEL 3 {r} {c}\n".encode())
        if not wait_for(ser, "SEL_DONE", 30, cap):
            print("FAIL: no SEL_DONE within 30 s.")
            return 1
        m = cap.get("mismatches")
        if m is None or m > 2:
            print(f"FAIL: Mismatches={m} (expected 0-2; 2 is the healthy-"
                  "chain norm). Check Sout wiring/threshold and chip power.")
            return 1
        print(f"PASS (Mismatches={m}"
              + (", the expected same-cycle-check artifact)" if m == 2 else ")"))

    print("\nAll checks passed -- proceed to run_device_loop.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
