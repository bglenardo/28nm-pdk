from __future__ import annotations

import argparse
from dataclasses import dataclass

import serial


@dataclass(frozen=True)
class ProbeConfig:
    label: str
    stopbits: float
    write_terminator: str
    read_terminator: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe serial ports with SCPI *IDN? across common terminator and stop-bit settings.",
    )
    parser.add_argument(
        "--ports",
        nargs="+",
        default=["COM4", "COM5", "COM6", "COM7", "COM8"],
        help="Serial ports to probe.",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=9600,
        help="Serial baud rate to use for all ports.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1.0,
        help="Read timeout in seconds.",
    )
    parser.add_argument(
        "--exhaustive",
        action="store_true",
        help="Keep trying every configuration even after a port responds.",
    )
    return parser


def probe_port(
    port: str,
    baudrate: int,
    timeout: float,
    config: ProbeConfig,
) -> tuple[bool, str]:
    try:
        with serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=_serial_stopbits(config.stopbits),
            timeout=timeout,
        ) as connection:
            connection.reset_input_buffer()
            connection.reset_output_buffer()
            connection.write(f"*IDN?{config.write_terminator}".encode("ascii", errors="ignore"))
            response = connection.read_until(config.read_terminator.encode("ascii", errors="ignore"))
    except serial.SerialException as exc:
        return False, f"serial error: {exc}"
    except OSError as exc:
        return False, f"os error: {exc}"

    text = response.decode("ascii", errors="ignore").strip()
    if not text:
        return False, "no response"
    return True, text


def main() -> None:
    args = build_parser().parse_args()

    configs = [
        ProbeConfig(label="CR,1 stop bit", stopbits=1.0, write_terminator="\r", read_terminator="\r"),
        ProbeConfig(label="CR,2 stop bits", stopbits=2.0, write_terminator="\r", read_terminator="\r"),
        ProbeConfig(label="CRLF,1 stop bit", stopbits=1.0, write_terminator="\r\n", read_terminator="\n"),
        ProbeConfig(label="CRLF,2 stop bits", stopbits=2.0, write_terminator="\r\n", read_terminator="\n"),
    ]

    for port in args.ports:
        matches: list[str] = []
        last_failure = "no response"

        for config in configs:
            ok, message = probe_port(
                port=port,
                baudrate=args.baudrate,
                timeout=args.timeout,
                config=config,
            )
            if ok:
                matches.append(f"{config.label} - {message}")
                if not args.exhaustive:
                    break
            else:
                last_failure = f"{config.label} - {message}"

        if matches:
            for match in matches:
                print(f"{port}: OK - {match}")
        else:
            print(f"{port}: FAIL - {last_failure}")


def _serial_stopbits(value: float) -> float:
    if value == 1.0:
        return serial.STOPBITS_ONE
    if value == 1.5:
        return serial.STOPBITS_ONE_POINT_FIVE
    if value == 2.0:
        return serial.STOPBITS_TWO
    raise ValueError(f"Unsupported stop bits value: {value}")


if __name__ == "__main__":
    main()