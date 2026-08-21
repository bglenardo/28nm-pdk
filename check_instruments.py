"""check_instruments.py -- can Python talk to the bench instruments?

Read-only connectivity probe. Opens each serial instrument defined in
instrument_list.yaml and asks it to identify itself (*IDN? for SCPI gear).
It does NOT source any voltage, enable any output, or reset anything beyond
what the driver's open() already does -- safe to run without the chip biased.

    python check_instruments.py                       # uses instrument_list.yaml
    python check_instruments.py --config other.yaml
    python check_instruments.py --port COM7            # probe ONE port directly

Exit code 0 = every probed instrument answered; non-zero = at least one didn't.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Same import shim as run_routine.py / run_device_loop.py: run from repo root
# without needing `pip install -e .`.
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import yaml  # PyYAML, already a project dependency

from iv_measure.keithley2400 import Keithley2400
from iv_measure.e3631a import E3631A
from iv_measure.serial_instrument import InstrumentError, SerialInstrument
from iv_measure.config import SerialDeviceConfig


def _idn_over_raw_serial(name: str, spec: dict) -> str:
    """Open a port with the YAML's serial settings and query *IDN? directly.

    Uses SerialInstrument (the same transport the drivers use) so termination
    and encoding match exactly, without running any driver init sequence.
    """
    cfg = SerialDeviceConfig(
        name=name,
        port=spec["port"],
        baudrate=spec.get("baudrate", 9600),
        timeout_s=spec.get("timeout_s", 1.0),
        bytesize=spec.get("bytesize", 8),
        parity=spec.get("parity", "N"),
        stopbits=spec.get("stopbits", 1),
        write_termination=spec.get("write_termination", "\r"),
        read_termination=spec.get("read_termination", "\r"),
        current_compliance_a=spec.get("current_compliance_a", 0.01),
        measure_current_cmd=None,
    )
    with SerialInstrument(cfg) as ser:
        return ser.query_scpi("*IDN?")


def probe_from_yaml(config_path: Path) -> int:
    data = yaml.safe_load(config_path.read_text())
    instruments = data.get("instruments", {})
    if not instruments:
        print(f"No 'instruments:' block in {config_path}")
        return 2

    failures = 0
    for name, spec in instruments.items():
        port = spec.get("port")
        itype = spec.get("type", "?")
        if not port or str(port).lower() == "none":
            print(f"[skip] {name} ({itype}): no port assigned")
            continue
        print(f"[probe] {name} ({itype}) on {port} ...", end=" ", flush=True)
        try:
            idn = _idn_over_raw_serial(name, spec)
            if idn:
                print(f"OK -> {idn!r}")
            else:
                print("OPENED but *IDN? returned nothing "
                      "(wrong baud/termination, or a non-SCPI supply?)")
                failures += 1
        except Exception as exc:  # serial.SerialException, InstrumentError, etc.
            print(f"FAILED: {type(exc).__name__}: {exc}")
            failures += 1
    return 1 if failures else 0


def probe_one_port(port: str) -> int:
    """Probe a single port with Keithley-default serial settings (9600, \\r)."""
    print(f"[probe] {port} with Keithley-2400 defaults (9600 8N1, CR) ...",
          end=" ", flush=True)
    cfg = SerialDeviceConfig(
        name=f"probe:{port}", port=port, baudrate=9600, timeout_s=1.0,
        bytesize=8, parity="N", stopbits=1,
        write_termination="\r", read_termination="\r",
        current_compliance_a=0.01, measure_current_cmd=None,
    )
    try:
        with SerialInstrument(cfg) as ser:
            idn = ser.query_scpi("*IDN?")
        if idn:
            print(f"OK -> {idn!r}")
            return 0
        print("OPENED but no *IDN? response.")
        return 1
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default="instrument_list.yaml",
                    help="instrument YAML to read (default: instrument_list.yaml)")
    ap.add_argument("--port", default=None,
                    help="probe a single COM port directly, ignoring the YAML")
    args = ap.parse_args()

    if args.port:
        return probe_one_port(args.port)
    return probe_from_yaml(Path(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
