"""Lightweight Arduino connection tester.

Opens the Arduino device-selector serial port, waits for its boot banner,
sends a single command, and prints every line the board sends back. Use this
to confirm two-way communication before running a full measurement routine.

Firmware protocol (see Arduino/unified_scan_select/unified_scan_select.ino):
  * On boot the board prints a banner ending in ``READY`` (after the USB host
    opens the port and the Nano R4 resets).
  * ``SEL,<flavor>,<row>,<col>,<chip>`` selects a device (chip=1 -> 344 clocks,
    chip=2 -> 688 clocks) and replies ``SEL_DONE`` (or ``SEL_FAIL`` on a bad
    address). Commas or spaces are accepted as separators.
  * ``VERIFY,<flavor>,<row>,<col>`` clocks the full chain, reads SOUT, prints a
    mismatch/alignment report, then ``VERIFY_DONE``.
  * ``PING`` replies ``PONG``.

A healthy round-trip prints ``SEL_DONE`` / ``VERIFY_DONE`` / ``PONG``. An
``ERR``/``SEL_FAIL`` reply means the command was rejected (bad args or an
out-of-range flavor/row/col). No reply at all means no communication.

Examples:
  python test_arduino_connection.py                       # YAML port, send SEL,1,1,6,1
  python test_arduino_connection.py --flavor 1 --row 1 --col 6 --chip 2
  python test_arduino_connection.py --verify --flavor 1 --row 1 --col 6
  python test_arduino_connection.py --port COM14 --cmd "PING"
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import serial
import yaml

DEFAULT_CONFIG = Path(__file__).with_name("instrument_list.yaml")

_ARDUINO_TYPES = {"ARDUINO", "ARDUINO_NANO", "ARDUINO_NANO_R4", "NANO", "NANO_R4"}
_ARDUINO_MODELS = {"NANO", "NANO_R4", "ARDUINO"}


def _find_arduino_entry(config_path: Path) -> dict:
    """Return the Arduino instrument mapping from the YAML config (or {})."""
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(raw, dict):
        return {}
    instruments = raw.get("instruments")
    if not isinstance(instruments, dict):
        return {}

    for cfg in instruments.values():
        if not isinstance(cfg, dict):
            continue
        type_name = str(cfg.get("type", "")).strip().upper()
        model_name = str(cfg.get("model", "")).strip().upper()
        if type_name in _ARDUINO_TYPES or model_name in _ARDUINO_MODELS:
            return cfg
    return {}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test the Arduino device-selector serial link.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="YAML config to read the Arduino port from.")
    parser.add_argument("--port", default=None, help="Serial port override (e.g. COM14). Defaults to the YAML Arduino port.")
    parser.add_argument("--baudrate", type=int, default=None, help="Baud rate override. Defaults to the YAML value or 9600.")
    parser.add_argument("--flavor", type=int, default=1, help="Flavor index for the default SEL command (default: 1).")
    parser.add_argument("--row", type=int, default=1, help="Row index for the default SEL command (default: 1).")
    parser.add_argument("--col", type=int, default=6, help="Column index for the default SEL command (default: 6).")
    parser.add_argument("--chip", type=int, default=1, help="Chip index for the default SEL command (1 or 2, default: 1).")
    parser.add_argument("--verify", action="store_true", help="Send VERIFY,<flavor>,<row>,<col> instead of SEL (full-chain readback report).")
    parser.add_argument("--raw", action="store_true", help="Send SOUTRAW,<flavor>,<row>,<col> to dump the raw A1 ADC envelope (dead-line vs under-threshold).")
    parser.add_argument("--cmd", default=None, help="Raw command to send instead of the default SEL/VERIFY command.")
    parser.add_argument("--banner-timeout", type=float, default=4.0, help="Seconds to wait for the boot banner after opening the port.")
    parser.add_argument("--reply-timeout", type=float, default=6.0, help="Seconds to wait for the command reply.")
    return parser


def _read_lines_until(ser: serial.Serial, deadline: float, stop_tokens: tuple[str, ...]) -> list[str]:
    """Read newline-delimited lines until a stop token appears or time runs out."""
    lines: list[str] = []
    buffer = b""
    while time.time() < deadline:
        waiting = ser.in_waiting
        chunk = ser.read(waiting if waiting > 0 else 1)
        if not chunk:
            continue
        buffer += chunk
        while b"\n" in buffer:
            raw_line, buffer = buffer.split(b"\n", 1)
            text = raw_line.decode(errors="ignore").strip()
            if text:
                lines.append(text)
                if any(token in text for token in stop_tokens):
                    return lines
    # Flush any trailing partial line.
    tail = buffer.decode(errors="ignore").strip()
    if tail:
        lines.append(tail)
    return lines


def main() -> int:
    args = build_parser().parse_args()
    entry = _find_arduino_entry(args.config)

    port = args.port or str(entry.get("port", "")).strip()
    if not port:
        print("ERROR: no Arduino port found. Pass --port COMx or add an Arduino entry to the YAML.", file=sys.stderr)
        return 2
    baudrate = args.baudrate or int(entry.get("baudrate", 115200))

    if args.cmd is not None:
        command = args.cmd
    elif args.raw:
        command = f"SOUTRAW,{args.flavor},{args.row},{args.col}"
    elif args.verify:
        command = f"VERIFY,{args.flavor},{args.row},{args.col}"
    else:
        command = f"SEL,{args.flavor},{args.row},{args.col},{args.chip}"

    print(f"Opening {port} @ {baudrate} baud ...")
    try:
        ser = serial.Serial(port, baudrate, timeout=0.2)
    except serial.SerialException as exc:
        print(f"ERROR: could not open {port}: {exc}", file=sys.stderr)
        return 2

    try:
        # The Nano R4 resets when the port is opened; wait for the READY banner.
        banner = _read_lines_until(ser, time.time() + args.banner_timeout, stop_tokens=("READY",))
        if banner:
            print("Boot banner:")
            for line in banner:
                print(f"  < {line}")
            saw_ready = any("READY" in line for line in banner)
        else:
            saw_ready = False
            print("No boot banner received (board may already be running from a prior session).")

        # Clear anything left over, then send the command.
        ser.reset_input_buffer()
        print(f"Sending: {command!r}")
        ser.write((command + "\n").encode("ascii"))
        ser.flush()

        reply = _read_lines_until(
            ser,
            time.time() + args.reply_timeout,
            stop_tokens=("SEL_DONE", "SEL_FAIL", "VERIFY_DONE", "SOUTRAW_DONE", "PONG", "ERR"),
        )
        print("Reply:")
        if reply:
            for line in reply:
                print(f"  < {line}")
        else:
            print("  <no reply>")
    finally:
        ser.close()

    # Verdict.
    reply_text = "\n".join(reply)
    saw_err = ("ERR" in reply_text) or any(line.strip() == "SEL_FAIL" for line in reply)
    saw_ack = any(tok in reply_text for tok in ("SEL_DONE", "VERIFY_DONE", "SOUTRAW_DONE", "PONG"))
    print("\n--- Verdict ---")
    print(f"Boot banner (READY): {'yes' if saw_ready else 'no'}")
    print(f"Got any reply:       {'yes' if reply else 'no'}")
    if not reply:
        print("RESULT: NO COMMUNICATION. Check the port, cable, and that no other program holds the port.")
        return 1
    if saw_ack and not saw_err:
        print("RESULT: OK. The Arduino accepted the command (SEL_DONE/VERIFY_DONE/PONG).")
        return 0
    if saw_err:
        print("RESULT: TWO-WAY COMMS OK, but the command was REJECTED (ERR/SEL_FAIL).")
        print("        Usually an out-of-range flavor/row/col or malformed args.")
        print("        The firmware expects SEL,<flavor>,<row>,<col>,<chip> or VERIFY,<flavor>,<row>,<col>.")
        return 1
    print("RESULT: Reply received but no recognized ack token. Inspect the lines above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
