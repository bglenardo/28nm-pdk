from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from probe_scpi_identity import ProbeConfig, probe_port


DEFAULT_CONFIG = Path(__file__).with_name("instrument_list.yaml")


def _configured_ports(config_path: Path) -> list[str]:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{config_path} does not contain a YAML mapping at the root")

    instruments = raw.get("instruments", {})
    if not isinstance(instruments, dict):
        raise ValueError(f"{config_path} is missing an 'instruments' mapping")

    ports: list[str] = []
    for _, spec in instruments.items():
        if isinstance(spec, dict) and "port" in spec:
            ports.append(str(spec["port"]))
    return sorted(set(ports))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe only the serial ports configured in instrument_list.yaml.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="YAML config file that defines the instrument ports.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.5,
        help="Read timeout in seconds for each probe attempt.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    ports = _configured_ports(args.config)

    if not ports:
        print(f"No configured ports found in {args.config}")
        return

    configs = [
        ProbeConfig(label="Keithley/HP 8N1 CR", baudrate=9600, bytesize=8, parity="N", stopbits=1.0, write_terminator="\r", read_terminator="\r"),
        ProbeConfig(label="Keithley/HP 8N1 LF", baudrate=9600, bytesize=8, parity="N", stopbits=1.0, write_terminator="\n", read_terminator="\n"),
        ProbeConfig(label="BK 9132C 8N1 CRLF", baudrate=9600, bytesize=8, parity="N", stopbits=1.0, write_terminator="\r\n", read_terminator="\n"),
        ProbeConfig(label="E3631A 8N2 CRLF", baudrate=9600, bytesize=8, parity="N", stopbits=2.0, write_terminator="\r\n", read_terminator="\n"),
        ProbeConfig(label="legacy 8N1 CRLF", baudrate=9600, bytesize=8, parity="N", stopbits=1.0, write_terminator="\r\n", read_terminator="\n"),
    ]

    print(f"Probing configured ports from {args.config}: {ports}")
    for port in ports:
        first_match: str | None = None
        last_failure = "no response"

        for config in configs:
            ok, message = probe_port(port=port, baudrate=config.baudrate, timeout=args.timeout, config=config)
            if ok:
                first_match = f"{config.label} - {message}"
                break
            last_failure = f"{config.label} - {message}"

        if first_match is not None:
            print(f"{port}: OK - {first_match}")
        else:
            print(f"{port}: FAIL - {last_failure}")


if __name__ == "__main__":
    main()
