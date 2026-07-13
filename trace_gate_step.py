"""trace_gate_step.py -- gentle output trace that STEPS Vg, to prove the device
is a working transistor (channel current responds to the gate) rather than a
fixed ~6 kohm path.

The 10 mA / 0.85 V routine saturates these small devices instantly, hiding any
gate control. This drives Vd over a SMALL range at LOW compliance for each of
several Vg values and reports how much the current MOVES with Vg. If Id at a
fixed Vd changes strongly across Vg -> real transistor. If it doesn't -> gate
truly isn't reaching the channel.

Uses raw pyserial (the approach that read the Keithley cleanly during
short-tracing), driving:
  drain  = Keithley 2400 on COM7  (:SOUR:VOLT / :READ?)
  gate   = E3631A P25V on COM5    (APPL P25V, <v>, <ilim>)
Ports/commands are read from instrument_list.yaml so nothing is hardcoded.
vgxp/vgxn are on the manual supply (unchanged), as in every routine run.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import serial

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from iv_measure.config import load_project_config


def open_raw(port, baud, timeout=2.0):
    s = serial.Serial(port, baud, timeout=timeout, bytesize=8, parity="N",
                       stopbits=1)
    time.sleep(1.0)
    return s


def send(s, cmd):
    s.reset_input_buffer()
    s.write((cmd + "\r").encode())
    time.sleep(0.3)


def query(s, cmd, wait=0.6):
    s.reset_input_buffer()
    s.write((cmd + "\r").encode())
    time.sleep(wait)
    return s.read_until(b"\r").decode(errors="ignore").strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default="instrument_list.yaml")
    ap.add_argument("--vmax", type=float, default=0.2, help="max Vd (V)")
    ap.add_argument("--points", type=int, default=9)
    ap.add_argument("--compliance", type=float, default=1e-3)
    ap.add_argument("--vg", type=float, nargs="+",
                    default=[0.0, 0.2, 0.4, 0.6, 0.8],
                    help="gate voltages to step through")
    ap.add_argument("--settle", type=float, default=0.4)
    ap.add_argument("--scan-port", help="select a device first")
    ap.add_argument("--flavor", type=int)
    ap.add_argument("--row", type=int)
    ap.add_argument("--col", type=int)
    args = ap.parse_args()

    config = load_project_config(args.config)
    drain_cfg = config.drain_source
    gate_cfg = config.gate_source

    if args.scan_port:
        from run_device_loop import open_scan_arduino, select_device
        if None in (args.flavor, args.row, args.col):
            ap.error("--scan-port requires --flavor/--row/--col")
        print(f"selecting flavor {args.flavor} r{args.row} c{args.col} ...")
        ser = open_scan_arduino(args.scan_port)
        select_device(ser, args.flavor, args.row, args.col, ignore_readback=True)
        ser.close()

    # Reset drain port (stale-handle guard) then open both instruments raw.
    from run_first_routine import reset_serial_ports
    reset_serial_ports([drain_cfg.port, gate_cfg.port])

    gate = open_raw(gate_cfg.port, gate_cfg.baudrate)
    drain = open_raw(drain_cfg.port, drain_cfg.baudrate)
    try:
        # Drain as gentle voltage source / current meter.
        for c in ("*RST", ":SOUR:FUNC VOLT", ':SENS:FUNC "CURR"',
                  f":SENS:CURR:PROT {args.compliance:.6f}",
                  ":SENS:CURR:RANG:AUTO ON", ":SYST:RSEN OFF", "OUTP ON"):
            send(drain, c)
        time.sleep(0.8)
        # Gate output on.
        send(gate, "OUTP ON")

        print(f"gate-stepped trace: Vd 0..{args.vmax} V @ "
              f"{args.compliance*1e3:g} mA, Vg in {args.vg}")
        vds = [args.vmax * i / (args.points - 1) for i in range(args.points)]

        # results[vg] = list of I aligned with vds
        results: dict[float, list[float]] = {}
        for vg in args.vg:
            send(gate, gate_cfg.set_voltage_cmd.format(value=vg))
            time.sleep(1.0)  # let gate settle
            row = []
            for vd in vds:
                send(drain, drain_cfg.set_voltage_cmd.format(value=vd))
                time.sleep(args.settle)
                raw = query(drain, ":READ?")
                parts = raw.split(",")
                try:
                    cur = float(parts[1]) if len(parts) > 1 else float(parts[0])
                except (ValueError, IndexError):
                    cur = float("nan")
                row.append(cur)
            results[vg] = row
            print(f"  Vg={vg:.2f} V: I@Vd={args.vmax:.2f} = {row[-1]*1e6:8.2f} uA")
    finally:
        send(drain, drain_cfg.set_voltage_cmd.format(value=0.0))
        send(drain, "OUTP OFF")
        send(gate, gate_cfg.set_voltage_cmd.format(value=0.0))
        send(gate, "OUTP OFF")
        drain.close(); gate.close()

    # Verdict: does Id at the top Vd move with Vg?
    print()
    print(f"{'Vd':>7}", *[f"Vg={v:.1f}" for v in args.vg])
    for i, vd in enumerate(vds):
        print(f"{vd:7.3f}", *[f"{results[v][i]*1e6:8.2f}" for v in args.vg])

    top = [results[v][-1] for v in args.vg]
    span = max(top) - min(top)
    peak = max(abs(x) for x in top) or 1e-15
    print()
    print(f"Id spread across Vg at Vd={args.vmax:.2f} V: {span*1e6:.2f} uA "
          f"({span/peak:.0%} of peak)")
    if span / peak > 0.2:
        print("  => GATE CONTROLS THE CHANNEL: this is a working transistor.")
    else:
        print("  => little/no gate response: gate not reaching the channel "
              "(selection or gate-rail issue), NOT device geometry.")


if __name__ == "__main__":
    main()
