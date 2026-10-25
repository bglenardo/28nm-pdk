from __future__ import annotations

import argparse
import multiprocessing as mp
import time
from dataclasses import dataclass

import serial
import serial.tools.list_ports as list_ports


@dataclass(frozen=True)
class ProbeConfig:
    label: str
    baudrate: int
    bytesize: int
    parity: str
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
        default=["AUTO"],
        help="Serial ports to probe. Use 'AUTO' to detect available ports automatically.",
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


def _discover_ports() -> list[str]:
    ports = [info.device for info in list_ports.comports()]
    return sorted(set(ports))


def resolve_ports(raw_ports: list[str] | None) -> list[str]:
    if not raw_ports or raw_ports == ["AUTO"]:
        return _discover_ports()
    ports = []
    for entry in raw_ports:
        if entry.upper() == "AUTO":
            ports.extend(_discover_ports())
        else:
            ports.append(entry)
    return sorted(set(ports))


def _query_scpi(connection: serial.Serial, command: str, terminator: str, timeout_s: float = 0.25) -> str:
    """Send a SCPI query and read the response. Return empty string on timeout or no response."""
    try:
        connection.timeout = min(max(timeout_s, 0.05), 0.25)
        connection.reset_input_buffer()
        connection.write(f"{command}{terminator}".encode("ascii", errors="ignore"))
        connection.flush()
        time.sleep(0.05)
        deadline = time.monotonic() + min(max(timeout_s, 0.05), 0.25)
        chunks: list[str] = []
        while time.monotonic() < deadline:
            if connection.in_waiting > 0:
                chunk = connection.read(connection.in_waiting)
                if not chunk:
                    break
                decoded = chunk.decode("ascii", errors="ignore")
                chunks.append(decoded)
                if terminator in decoded:
                    break
            time.sleep(0.02)
        text = "".join(chunks).strip()
        if not text:
            return ""
        return text
    except (serial.SerialException, OSError, ValueError):
        return ""


def _clear_status(connection: serial.Serial) -> None:
    """Send *CLS to clear stale error and status conditions before/after probing."""
    try:
        connection.reset_input_buffer()
        connection.write(b"*CLS\r\n")
        connection.flush()
        time.sleep(0.05)
    except (serial.SerialException, OSError, ValueError):
        pass


def probe_port(
    port: str,
    baudrate: int,
    timeout: float,
    config: ProbeConfig,
) -> tuple[bool, str]:
    try:
        with serial.Serial(
            port=port,
            baudrate=config.baudrate,
            bytesize=_serial_bytesize(config.bytesize),
            parity=_serial_parity(config.parity),
            stopbits=_serial_stopbits(config.stopbits),
            timeout=min(max(timeout, 0.05), 0.25),
        ) as connection:
            _clear_status(connection)
            idn_text = _query_scpi(connection, "*IDN?", config.write_terminator, timeout_s=max(timeout, 0.25))
            if not idn_text:
                _clear_status(connection)
                return False, "no response"

            vers_text = _query_scpi(connection, "SYST:VERS?", config.write_terminator, timeout_s=max(timeout, 0.25))
            error_text = _query_scpi(connection, "SYST:ERR?", config.write_terminator, timeout_s=max(timeout, 0.25))

            result = idn_text
            if vers_text:
                result += f" | VERS: {vers_text}"
            if error_text:
                result += f" | Error: {error_text}"

            _clear_status(connection)
            return True, result
    except serial.SerialException as exc:
        return False, f"serial error: {exc}"
    except OSError as exc:
        return False, f"os error: {exc}"
    except Exception as exc:
        return False, f"unexpected error: {exc}"


def _probe_port_worker(port: str, baudrate: int, timeout: float, config: ProbeConfig, q: mp.Queue) -> None:
    q.put(probe_port(port=port, baudrate=baudrate, timeout=timeout, config=config))


def _probe_port_with_timeout(port: str, baudrate: int, timeout: float, config: ProbeConfig, per_port_timeout_s: float = 2.5) -> tuple[bool, str]:
    q: mp.Queue[tuple[bool, str]] = mp.Queue()
    proc = mp.Process(target=_probe_port_worker, args=(port, baudrate, timeout, config, q), daemon=True)
    proc.start()
    proc.join(timeout=per_port_timeout_s)
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=1.0)
        return False, "timed out"
    if q.empty():
        return False, "no result"
    return q.get()


def main() -> None:
    args = build_parser().parse_args()

    configs = [
        ProbeConfig(label="Keithley/HP 8N1 CR", baudrate=9600, bytesize=8, parity="N", stopbits=1.0, write_terminator="\r", read_terminator="\r"),
        ProbeConfig(label="Keithley/HP 8N1 LF", baudrate=9600, bytesize=8, parity="N", stopbits=1.0, write_terminator="\n", read_terminator="\n"),
        ProbeConfig(label="BK 9132C 8N1 CRLF", baudrate=9600, bytesize=8, parity="N", stopbits=1.0, write_terminator="\r\n", read_terminator="\n"),
        ProbeConfig(label="E3631A 8N2 CRLF", baudrate=9600, bytesize=8, parity="N", stopbits=2.0, write_terminator="\r\n", read_terminator="\n"),
        ProbeConfig(label="legacy 8N1 CRLF", baudrate=9600, bytesize=8, parity="N", stopbits=1.0, write_terminator="\r\n", read_terminator="\n"),
    ]

    for port in resolve_ports(args.ports):
        first_match: str | None = None
        last_failure = "no response"

        for config in configs:
            ok, message = _probe_port_with_timeout(
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
            print(f"{port}: FAIL - {last_failure}")


def _serial_bytesize(value: int) -> int:
    if value == 7:
        return serial.SEVENBITS
    if value == 8:
        return serial.EIGHTBITS
    raise ValueError(f"Unsupported byte size: {value}")


def _serial_parity(value: str) -> str:
    normalized = str(value).upper()
    if normalized in {"N", "NONE"}:
        return serial.PARITY_NONE
    if normalized in {"E", "EVEN"}:
        return serial.PARITY_EVEN
    if normalized in {"O", "ODD"}:
        return serial.PARITY_ODD
    raise ValueError(f"Unsupported parity setting: {value}")


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