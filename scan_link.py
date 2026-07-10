"""scan_link.py -- shared serial protocol for the SEL-patched Arduino sketch.

Imported by BOTH run_device_loop.py (the unattended loop) and test_scan_link.py
(the pre-flight) so the wire protocol has exactly one implementation and cannot
drift between them. Talks to Arduino/sketch_may26_r4_SEL.

Nothing in here touches the Keithley 2400 / E3631A instruments -- scan chain
only. It is safe to run with no bench instruments connected.

Protocol (see PLAN.md "Serial protocol spec"):
    link            115200 8N1, '\n'-terminated commands, newline replies
                    (baud: sketch Serial.begin(115200), line 265)
    PING        ->  PONG
    SEL f r c   ->  configureDevice() report ... "Mismatches: N" ... then SEL_DONE
    <junk>      ->  "ERR unknown cmd: <text>"

Mismatch grading (CLAUDE.md Q1/Q2, bench log Section 5, July 2026):
    The sketch compares Sout to Sin in the SAME clock cycle of the load pass, so
    what exits during loading is the chain's PREVIOUS contents (zeros after
    reset). A perfectly healthy chain therefore reports exactly 2 phantom
    mismatches (the two one-hot bits) and prints "Test Failed". NEVER gate on the
    "Test Passed/Failed" string. This particular chain reads 3 on the bench
    (one extra bit hovering near the weak-Sout analog-read threshold). So the
    tolerance is: mismatches > 4 -> abort. (2 ideal, 3 bench-normal.)
"""
from __future__ import annotations

import time

import serial

# --- protocol constants (all cited) ------------------------------------------
SCAN_BAUD = 115200          # sketch Serial.begin(115200), line 265
DEFAULT_MISMATCH_ABORT = 4  # CLAUDE.md Q2 / Section 5 bench log: >4 => real fault
SEL_DONE_TIMEOUT_S = 30.0   # PLAN.md: 344-line per-bit report + summary (sketch:150)
READY_TIMEOUT_S = 15.0      # Q6: wait for READY / start banner after reset
PING_TIMEOUT_S = 5.0


class ScanLinkError(RuntimeError):
    """Raised for any scan-link protocol failure (open, PING, SEL, timeout)."""


def _read_line(ser: serial.Serial, verbose: bool) -> str:
    line = ser.readline().decode(errors="ignore").strip()
    if verbose and line:
        print(f"    arduino: {line}")
    return line


def wait_for(
    ser: serial.Serial,
    token: str,
    timeout_s: float,
    capture: dict | None = None,
    verbose: bool = False,
) -> bool:
    """Read lines until one equals `token`. Optionally capture the Mismatches
    count into capture["mismatches"] as it streams past."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        line = _read_line(ser, verbose)
        if not line:
            continue
        if capture is not None and line.startswith("Mismatches:"):
            try:
                capture["mismatches"] = int(line.split(":", 1)[1])
            except ValueError:
                pass
        if line == token:
            return True
    return False


def ping(ser: serial.Serial, timeout_s: float = PING_TIMEOUT_S,
         verbose: bool = False) -> bool:
    """Send PING, return True iff PONG comes back within timeout."""
    ser.reset_input_buffer()
    ser.write(b"PING\n")
    return wait_for(ser, "PONG", timeout_s, verbose=verbose)


def open_scan_link(
    port: str,
    baud: int = SCAN_BAUD,
    ready_timeout_s: float = READY_TIMEOUT_S,
    verbose: bool = False,
) -> serial.Serial:
    """Robustly open the scan port (CLAUDE.md Q6).

    Auto-reset on port-open is unreliable across boards/drivers, so:
      1. open the port,
      2. pulse DTR low->high to *request* a reset,
      3. wait up to ready_timeout_s for the sketch's READY banner (or the
         legacy 'start' banner from un-patched firmware),
      4. if no banner appears, fall back to a PING/PONG liveness check --
         "no banner" alone is NOT treated as failure (Q6).
    Raises ScanLinkError only if the board is truly unresponsive.
    """
    # timeout=2 s per readline keeps the banner/PING loops responsive.
    ser = serial.Serial(port=port, baudrate=baud, timeout=2)

    # Pulse DTR to request a reset (Q6). Some boards reset on the low->high edge;
    # others ignore it entirely, which is why the PING fallback below exists.
    try:
        ser.dtr = False
        time.sleep(0.1)
        ser.dtr = True
    except (OSError, ValueError):
        # Not all drivers expose DTR control; the PING fallback still covers us.
        pass

    time.sleep(2.0)  # let the board boot (mirrors run_routine.py port-reset pause)

    saw_ready = False
    deadline = time.time() + ready_timeout_s
    while time.time() < deadline:
        line = _read_line(ser, verbose)
        if line in ("READY", "start"):
            saw_ready = True
            break

    if saw_ready:
        return ser

    # Fallback: no banner seen -- prove the parser is alive instead (Q6).
    if ping(ser, verbose=verbose):
        return ser

    ser.close()
    raise ScanLinkError(
        f"Arduino on {port} did not respond (no READY/start banner, no PONG). "
        "Likely causes, in order: (1) no chip/board power or wrong --scan-port "
        "(Windows renumbers COMs after replug -- Q5); (2) the Arduino IDE Serial "
        "Monitor or another script is holding the port (single-occupancy -- Q5); "
        "(3) the SEL-patched sketch (sketch_may26_r4_SEL) is not flashed."
    )


def select_device(
    ser: serial.Serial,
    flavor: int,
    row: int,
    col: int,
    mismatch_abort: int = DEFAULT_MISMATCH_ABORT,
    timeout_s: float = SEL_DONE_TIMEOUT_S,
    verbose: bool = False,
    require_readback: bool = True,
) -> int:
    """Send SEL and parse configureDevice()'s existing report.

    Returns the parsed Mismatches count. Raises ScanLinkError on timeout or on a
    missing Mismatches line. Does NOT look at the "Test Passed/Failed" string.

    require_readback (default True): if mismatches > mismatch_abort, raise (the
    read-back tap looks faulty). If False, a high count is downgraded to a printed
    WARNING and the selection is trusted anyway. This is valid because the
    Mismatches count only tests the Sout READ-BACK path; correct device selection
    uses Sin + clocks + Supdate and is proven by measuring a real transistor
    (CLAUDE.md Q2). Use False only when the read-back tap is known-broken but you
    still want to acquire data -- then GRADE THE IV CURVE (Q8) to confirm selection.
    The SEL command still completes and latches regardless of this flag.
    """
    ser.reset_input_buffer()
    ser.write(f"SEL {flavor} {row} {col}\n".encode())

    cap: dict = {}
    if not wait_for(ser, "SEL_DONE", timeout_s, capture=cap, verbose=verbose):
        raise ScanLinkError(
            f"SEL {flavor} {row} {col}: no SEL_DONE within {timeout_s:.0f} s. "
            "Check the link is still up and the sketch is the SEL-patched build."
        )

    mismatches = cap.get("mismatches")
    if mismatches is None:
        raise ScanLinkError(
            f"SEL {flavor} {row} {col}: completed but no 'Mismatches:' line seen."
        )
    if mismatches > mismatch_abort:
        msg = (
            f"SEL {flavor} {row} {col}: {mismatches} mismatches (> {mismatch_abort}). "
            "2 is ideal and 3 is the July-2026 bench norm (Q1/Q2); this many "
            "indicates a real read-back fault -- check the Sout analog threshold "
            "(sketch line 31) and wiring, and confirm chip power."
        )
        if require_readback:
            raise ScanLinkError(msg)
        # Read-back check bypassed: trust selection, but flag it loudly. Selection
        # is only truly confirmed by grading the resulting IV curve (Q8/Q2).
        print(f"    WARNING (--skip-scan-check): {msg}")
    return mismatches
