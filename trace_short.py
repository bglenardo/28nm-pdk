"""trace_short.py -- measure the RESISTANCE of whatever is conducting on the
drain node, to tell a hard short (few ohms = fixture/blown device) from leakage
(kohms) from a healthy-open node (Mohms, i.e. we were mis-reading).

Every measurement so far only told us "it rails at 10 mA". This drives Vd over a
SMALL range at LOW compliance so it never slams the rail, reads current finely,
and fits R = dV/dI. That single number is what the multimeter would show, and it
decides whether we chase silicon, fixture, or a measurement artifact.

Reuses the existing Keithley2400 driver UNCHANGED (source_voltage /
measure_current_and_voltage), reading the drain port + compliance from
instrument_list.yaml via load_project_config. No edits to src/ or the yaml.

Optionally selects a device first (--scan-port + --flavor/--row/--col); by
default it measures whatever is currently latched, which is the honest thing
when we suspect selection itself is dead.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from iv_measure.config import load_project_config
from iv_measure.serial_instrument import SerialInstrument
from iv_measure.routines import _measure_current_a, _apply_init_commands, _output_on


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default="instrument_list.yaml")
    ap.add_argument("--vmax", type=float, default=0.1,
                    help="max drain voltage for the trace (V), default 0.1")
    ap.add_argument("--points", type=int, default=11)
    ap.add_argument("--compliance", type=float, default=1e-3,
                    help="current compliance (A), default 1 mA (gentle)")
    ap.add_argument("--settle", type=float, default=0.3)
    # Optional selection before tracing.
    ap.add_argument("--scan-port", help="if given, select a device first")
    ap.add_argument("--flavor", type=int)
    ap.add_argument("--row", type=int)
    ap.add_argument("--col", type=int)
    args = ap.parse_args()

    if args.scan_port:
        from run_device_loop import open_scan_arduino, select_device
        if None in (args.flavor, args.row, args.col):
            ap.error("--scan-port requires --flavor/--row/--col")
        print(f"selecting flavor {args.flavor} r{args.row} c{args.col} ...")
        ser = open_scan_arduino(args.scan_port)
        select_device(ser, args.flavor, args.row, args.col, ignore_readback=True)
        ser.close()  # release the port; the tracer only needs the Keithley
    else:
        print("tracing WHATEVER IS CURRENTLY LATCHED (no selection)")

    config = load_project_config(args.config)
    d = config.drain_source
    # run_first_routine.py resets ports (close lingering handles + 2 s pause)
    # BEFORE opening -- skipping this leaves COM7 in a stale state that returns
    # empty reads. Replicate it here.
    from run_first_routine import reset_serial_ports
    reset_serial_ports([d.port])
    # Reuse the EXACT machinery run_single_routine_from_csv uses: a
    # SerialInstrument on the drain config, its init_commands, and
    # _measure_current_a (the proven read path that produced 180 points today).
    drain = SerialInstrument(d)
    drain.open()
    try:
        drain.send_scpi("*CLS")
    except Exception:  # noqa: BLE001
        pass
    _output_on(drain)
    _apply_init_commands(drain)
    # Tighten compliance for a gentle trace (init set it to 0.01 A).
    drain.send_scpi(f":SENS:CURR:PROT {args.compliance:.6f}")
    print(f"tracing Vd 0..{args.vmax} V @ {args.compliance*1e3:g} mA compliance "
          f"on {d.port}")

    def read_current():
        """First :MEAS:CURR? at 9600 baud can return '' before the 2400 is
        ready; flush and retry a few times."""
        last = None
        for _ in range(4):
            try:
                return _measure_current_a(drain)
            except Exception as exc:  # noqa: BLE001
                last = exc
                try:
                    drain._ser.reset_input_buffer()  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(0.5)
        raise last

    print(f"{'Vset':>8} {'Imeas':>13}")
    vs, is_ = [], []
    try:
        time.sleep(1.5)  # let *RST/config settle before the FIRST query
        for i in range(args.points):
            vset = args.vmax * i / (args.points - 1)
            drain.send_scpi(d.set_voltage_cmd.format(value=vset))
            time.sleep(args.settle)
            cur = read_current()
            vs.append(vset); is_.append(cur)
            print(f"{vset:8.4f} {cur:13.3e}")
    finally:
        drain.send_scpi(d.set_voltage_cmd.format(value=0.0))
        try:
            drain.send_scpi("OUTP OFF")
        finally:
            drain.close()

    # Fit R = dV/dI by least squares (V is the SET drain voltage).
    n = len(vs)
    sx = sum(is_); sy = sum(vs)
    sxx = sum(x * x for x in is_); sxy = sum(x * y for x, y in zip(is_, vs))
    denom = n * sxx - sx * sx
    print()
    if abs(denom) < 1e-30:
        print("cannot fit R (no current spread) -- node may be open/compliant")
        return
    r = (n * sxy - sx * sy) / denom  # slope dV/dI = resistance
    imax = max(abs(x) for x in is_)
    print(f"fit resistance ~ {r:.3g} ohm   (peak |I| = {imax*1e3:.4g} mA)")
    if imax >= args.compliance * 0.98:
        print("  NOTE: hit compliance -- true R may be lower; rerun with lower --vmax")
    if r < 100:
        print("  => HARD SHORT (few-ohm path): fixture bridge or blown device")
    elif r < 1e5:
        print("  => resistive leakage (kohm): soft damage / parasitic")
    else:
        print("  => high resistance: node is ~open; the 10mA runs were likely "
              "forward-biased junction, not an ohmic short")


if __name__ == "__main__":
    main()
