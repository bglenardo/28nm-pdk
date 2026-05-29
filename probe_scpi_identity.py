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
        default=["COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8","COM9", "COM10", "COM11", "COM12"],
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
        default=0.5,
        help="Read timeout in seconds.",
    )
    return parser


def _query_scpi(connection: serial.Serial, command: str, terminator: str) -> str:
    """Send a SCPI query and read the response. Return empty string on timeout or no response."""
    try:
        connection.reset_input_buffer()
        connection.reset_output_buffer()
        connection.write(f"{command}{terminator}".encode("ascii", errors="ignore"))
        response = connection.read_until(terminator.encode("ascii", errors="ignore"))
        return response.decode("ascii", errors="ignore").strip()
    except (serial.SerialException, OSError):
        return ""


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
            idn_text = _query_scpi(connection, "*IDN?", config.write_terminator)
            if not idn_text:
                return False, "no response"
            
            # Query serial number
            # sn_text = _query_scpi(connection, ":SYST:SN?", config.write_terminator)
            
            # Query version/firmware
            vers_text = _query_scpi(connection, "SYST:VERS?", config.write_terminator)
            
            # Query installed options
            # opt_text = _query_scpi(connection, "*OPT?", config.write_terminator)
            
            # Try to query errors; fall back to *ESR? if SYST:ERR? fails
            error_text = _query_scpi(connection, "SYST:ERR?", config.write_terminator)
            
            result = idn_text
            if vers_text:
                result += f" | VERS: {vers_text}"
            # if opt_text:
                # result += f" | OPT: {opt_text}"
            if error_text:
                result += f" | Error: {error_text}"
            return True, result
    except serial.SerialException as exc:
        return False, f"serial error" # : {exc}"
    except OSError as exc:
        return False, f"os error: {exc}"


def main() -> None:
    args = build_parser().parse_args()

    configs = [
        ProbeConfig(label="CR,1 stop bit", stopbits=1.0, write_terminator="\r", read_terminator="\r"),
        ProbeConfig(label="CR,2 stop bits", stopbits=2.0, write_terminator="\r", read_terminator="\r"),
        ProbeConfig(label="CRLF,1 stop bit", stopbits=1.0, write_terminator="\r\n", read_terminator="\n"),
        ProbeConfig(label="CRLF,2 stop bits", stopbits=2.0, write_terminator="\r\n", read_terminator="\n"),
    ]

    for port in args.ports:
        first_match: str | None = None
        last_failure = "no response"

        for config in configs:
            ok, message = probe_port(
                port=port,
                baudrate=args.baudrate,
                timeout=args.timeout,
                config=config,
            )
            if ok:
                first_match = f"{config.label} - {message}"
                break
            else:
                last_failure = f"{config.label} - {message}"

        if first_match is not None:
            print(f"{port}: OK - {first_match}")
        else:
            if "serial error" not in last_failure:
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