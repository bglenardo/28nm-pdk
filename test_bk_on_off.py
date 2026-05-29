from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

import serial


@dataclass(frozen=True)
class SerialMode:
    label: str
    stopbits: float
    write_terminator: str
    read_terminator: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Minimal BK 9132C power toggle test. "
            "Auto-detects serial mode with *IDN?, then toggles outputs ON/OFF."
        )
    )
    parser.add_argument("--port", default="COM6", help="Serial port (example: COM6)")
    parser.add_argument("--baudrate", type=int, default=9600, help="Baud rate")
    parser.add_argument("--timeout", type=float, default=0.5, help="Serial timeout in seconds")
    parser.add_argument("--hold-s", type=float, default=3.0, help="Seconds to hold outputs ON")
    parser.add_argument(
        "--channels",
        nargs="*",
        default=["CH1", "CH3"],
        help="Channels to toggle (default: CH1 CH3)",
    )
    return parser


def _serial_stopbits(value: float) -> float:
    if value == 1.0:
        return serial.STOPBITS_ONE
    if value == 1.5:
        return serial.STOPBITS_ONE_POINT_FIVE
    if value == 2.0:
        return serial.STOPBITS_TWO
    raise ValueError(f"Unsupported stop bits value: {value}")


def _send(connection: serial.Serial, command: str, terminator: str) -> None:
    connection.write(f"{command}{terminator}".encode("ascii", errors="ignore"))


def _query(connection: serial.Serial, command: str, write_terminator: str, read_terminator: str) -> str:
    connection.reset_input_buffer()
    connection.reset_output_buffer()
    _send(connection, command, write_terminator)
    response = connection.read_until(read_terminator.encode("ascii", errors="ignore"))
    return response.decode("ascii", errors="ignore").strip()


def _detect_mode(port: str, baudrate: int, timeout: float) -> tuple[SerialMode, str]:
    modes = [
        SerialMode(label="CR,1 stop bit", stopbits=1.0, write_terminator="\r", read_terminator="\r"),
        SerialMode(label="CR,2 stop bits", stopbits=2.0, write_terminator="\r", read_terminator="\r"),
        SerialMode(label="CRLF,1 stop bit", stopbits=1.0, write_terminator="\r\n", read_terminator="\n"),
        SerialMode(label="CRLF,2 stop bits", stopbits=2.0, write_terminator="\r\n", read_terminator="\n"),
    ]

    last_error = "no response"
    for mode in modes:
        try:
            with serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=_serial_stopbits(mode.stopbits),
                timeout=timeout,
            ) as connection:
                idn = _query(connection, "*IDN?", mode.write_terminator, mode.read_terminator)
                if idn:
                    return mode, idn
                last_error = f"{mode.label}: no response"
        except (serial.SerialException, OSError) as exc:
            last_error = f"{mode.label}: {exc}"

    raise RuntimeError(f"Could not identify instrument on {port}. Last error: {last_error}")


def _best_effort_error_query(connection: serial.Serial, mode: SerialMode) -> str:
    try:
        return _query(connection, "SYST:ERR?", mode.write_terminator, mode.read_terminator)
    except (serial.SerialException, OSError):
        return ""


def main() -> None:
    args = build_parser().parse_args()

    mode, idn = _detect_mode(args.port, args.baudrate, args.timeout)
    print(f"Connected: {idn}")
    print(f"Using serial mode: {mode.label}")

    with serial.Serial(
        port=args.port,
        baudrate=args.baudrate,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=_serial_stopbits(mode.stopbits),
        timeout=args.timeout,
    ) as connection:
        print("Turning outputs ON...")
        _send(connection, "OUTP:STAT 1", mode.write_terminator)
        _send(connection, "OUTP ON", mode.write_terminator)

        for channel in args.channels:
            ch = channel.upper().strip()
            _send(connection, f"INST {ch}", mode.write_terminator)
            _send(connection, "CHAN:OUTP 1", mode.write_terminator)

        err = _best_effort_error_query(connection, mode)
        if err:
            print(f"Error status after ON: {err}")

        print(f"Holding ON for {args.hold_s:.1f} s")
        time.sleep(max(args.hold_s, 0.0))

        print("Turning outputs OFF...")
        for channel in args.channels:
            ch = channel.upper().strip()
            _send(connection, f"INST {ch}", mode.write_terminator)
            _send(connection, "CHAN:OUTP 0", mode.write_terminator)

        _send(connection, "OUTP:STAT 0", mode.write_terminator)
        _send(connection, "OUTP OFF", mode.write_terminator)

        err = _best_effort_error_query(connection, mode)
        if err:
            print(f"Error status after OFF: {err}")

    print("Done.")


if __name__ == "__main__":
    main()
