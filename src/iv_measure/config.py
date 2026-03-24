from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SerialDeviceConfig:
    name: str
    port: str
    baudrate: int = 9600
    timeout_s: float = 1.0
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1.0
    read_termination: str = "\r"
    write_termination: str = "\r"
    set_voltage_cmd: str = "SOUR:VOLT {value:.6f}"
    measure_current_cmd: str | None = "MEAS:CURR?"
    output_on_cmd: str | None = "OUTP ON"
    output_off_cmd: str | None = "OUTP OFF"


@dataclass(frozen=True)
class SweepConfig:
    gate_voltages_v: list[float]
    drain_start_v: float
    drain_stop_v: float
    drain_step_v: float
    settle_s: float
    output_csv: str


@dataclass(frozen=True)
class ProjectConfig:
    gate_source: SerialDeviceConfig
    drain_source: SerialDeviceConfig
    bulk_source: SerialDeviceConfig | None
    sweep: SweepConfig


def _float_list(values: Any) -> list[float]:
    if not isinstance(values, list) or not values:
        raise ValueError("sweep.gate_voltages_v must be a non-empty list")
    return [float(v) for v in values]


def load_project_config(path: str | Path) -> ProjectConfig:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Config root must be a mapping")

    instruments = raw.get("instruments")
    sweep = raw.get("sweep")
    if not isinstance(instruments, dict) or not isinstance(sweep, dict):
        raise ValueError("Config must contain 'instruments' and 'sweep' mappings")

    assignments = raw.get("assignments")
    if isinstance(assignments, dict):
        gate = _resolve_assigned_instrument("gate_source", assignments, instruments)
        drain = _resolve_assigned_instrument("drain_source", assignments, instruments)
        bulk = _resolve_optional_assigned_instrument("bulk_source", assignments, instruments)
    else:
        gate = _parse_serial("gate_source", instruments.get("gate_source"))
        drain = _parse_serial("drain_source", instruments.get("drain_source"))
        bulk = _parse_optional_serial("bulk_source", instruments.get("bulk_source"))

    sweep_cfg = SweepConfig(
        gate_voltages_v=_float_list(sweep.get("gate_voltages_v")),
        drain_start_v=float(sweep.get("drain_start_v")),
        drain_stop_v=float(sweep.get("drain_stop_v")),
        drain_step_v=float(sweep.get("drain_step_v")),
        settle_s=float(sweep.get("settle_s", 0.1)),
        output_csv=str(sweep.get("output_csv", "data/iv_curve.csv")),
    )

    if sweep_cfg.drain_step_v <= 0:
        raise ValueError("sweep.drain_step_v must be > 0")

    return ProjectConfig(
        gate_source=gate,
        drain_source=drain,
        bulk_source=bulk,
        sweep=sweep_cfg,
    )


def _parse_serial(name: str, raw: Any) -> SerialDeviceConfig:
    if not isinstance(raw, dict):
        raise ValueError(f"instruments.{name} must be a mapping")

    if "port" not in raw:
        raise ValueError(f"instruments.{name}.port is required")

    return SerialDeviceConfig(
        name=name,
        port=str(raw["port"]),
        baudrate=int(raw.get("baudrate", 9600)),
        timeout_s=float(raw.get("timeout_s", 1.0)),
        bytesize=int(raw.get("bytesize", 8)),
        parity=str(raw.get("parity", "N")),
        stopbits=float(raw.get("stopbits", 1.0)),
        read_termination=str(raw.get("read_termination", "\\r")),
        write_termination=str(raw.get("write_termination", "\\r")),
        set_voltage_cmd=str(raw.get("set_voltage_cmd", "SOUR:VOLT {value:.6f}")),
        measure_current_cmd=_none_or_str(raw.get("measure_current_cmd", "MEAS:CURR?")),
        output_on_cmd=_none_or_str(raw.get("output_on_cmd", "OUTP ON")),
        output_off_cmd=_none_or_str(raw.get("output_off_cmd", "OUTP OFF")),
    )


def _parse_optional_serial(name: str, raw: Any) -> SerialDeviceConfig | None:
    if raw is None:
        return None
    return _parse_serial(name, raw)


def _resolve_assigned_instrument(
    role_name: str,
    assignments: dict[str, Any],
    instruments: dict[str, Any],
) -> SerialDeviceConfig:
    instrument_name = assignments.get(role_name)
    if instrument_name is None:
        raise ValueError(f"assignments.{role_name} is required")

    instrument_key = str(instrument_name)
    return _parse_serial(instrument_key, instruments.get(instrument_key))


def _resolve_optional_assigned_instrument(
    role_name: str,
    assignments: dict[str, Any],
    instruments: dict[str, Any],
) -> SerialDeviceConfig | None:
    instrument_name = assignments.get(role_name)
    if instrument_name is None:
        return None

    instrument_key = str(instrument_name)
    return _parse_serial(instrument_key, instruments.get(instrument_key))


def _none_or_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"none", "null", ""}:
        return None
    return text
