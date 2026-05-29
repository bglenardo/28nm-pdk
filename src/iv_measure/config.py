from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
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
    init_commands: tuple[str, ...] = ()
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
    quantity_sources: dict[str, SerialDeviceConfig]
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
    if not isinstance(instruments, dict):
        raise ValueError("Config must contain an 'instruments' mapping")

    quantity_sources = _collect_quantity_sources(instruments)

    assignments = raw.get("assignments")
    if isinstance(assignments, dict):
        gate = _resolve_assigned_instrument("gate_source", assignments, instruments)
        drain = _resolve_assigned_instrument("drain_source", assignments, instruments)
        bulk = _resolve_optional_assigned_instrument("bulk_source", assignments, instruments)
    else:
        gate = quantity_sources.get("Vg")
        drain = quantity_sources.get("Vd")
        bulk = quantity_sources.get("Vb")

    if gate is None:
        raise ValueError("Could not resolve gate source. Add assignments.gate_source or map Vg in instruments")
    if drain is None:
        raise ValueError("Could not resolve drain source. Add assignments.drain_source or map Vd in instruments")

    sweep = raw.get("sweep")
    sweep_cfg = SweepConfig(
        gate_voltages_v=_float_list((sweep or {}).get("gate_voltages_v", [0.0])),
        drain_start_v=float((sweep or {}).get("drain_start_v", 0.0)),
        drain_stop_v=float((sweep or {}).get("drain_stop_v", 0.0)),
        drain_step_v=float((sweep or {}).get("drain_step_v", 0.1)),
        settle_s=float((sweep or {}).get("settle_s", 0.5)),
        output_csv=str((sweep or {}).get("output_csv", "data/iv_curve.csv")),
    )

    if sweep_cfg.drain_step_v <= 0:
        raise ValueError("sweep.drain_step_v must be > 0")

    return ProjectConfig(
        gate_source=gate,
        drain_source=drain,
        bulk_source=bulk,
        quantity_sources=quantity_sources,
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
        init_commands=tuple(_str_list(raw.get("init_commands", []))),
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
    return _parse_serial_for_role(role_name, instrument_key, instruments.get(instrument_key))


def _resolve_optional_assigned_instrument(
    role_name: str,
    assignments: dict[str, Any],
    instruments: dict[str, Any],
) -> SerialDeviceConfig | None:
    instrument_name = assignments.get(role_name)
    if instrument_name is None:
        return None

    instrument_key = str(instrument_name)
    raw = instruments.get(instrument_key)
    try:
        return _parse_serial_for_role(role_name, instrument_key, raw)
    except ValueError as exc:
        if "does not map quantity" in str(exc):
            return None
        raise


def _parse_serial_for_role(role_name: str, instrument_name: str, raw: Any) -> SerialDeviceConfig:
    if not isinstance(raw, dict):
        raise ValueError(f"instruments.{instrument_name} must be a mapping")

    instrument_type = str(raw.get("type", "serial")).strip().upper()
    if instrument_type == "E3631A":
        return _parse_e3631a_for_role(role_name, instrument_name, raw)
    if instrument_type in {"9132C", "BK9132C", "BK_9132C"}:
        return _parse_9132c_for_role(role_name, instrument_name, raw)
    if instrument_type in {"2400", "KEITHLEY2400", "KEITHLEY_2400"}:
        return _parse_keithley2400_for_role(role_name, instrument_name, raw)

    return _parse_serial(instrument_name, raw)


def _collect_typed_quantity_sources(instruments: dict[str, Any]) -> dict[str, SerialDeviceConfig]:
    sources: dict[str, SerialDeviceConfig] = {}
    valid_quantities = {"Vg", "Vd", "Vb", "Vs", "vgxp", "vgxn"}

    for instrument_name, raw in instruments.items():
        if not isinstance(raw, dict):
            continue

        instrument_type = str(raw.get("type", "serial")).strip().upper()
        if instrument_type == "E3631A":
            channel_map = _typed_channel_map(raw, instrument_name)
            command_template = "APPL {channel}, {value:.6f}, {current_limit_a:.6f}"
            current_limit_a = float(raw.get("current_limit_a", 0.1))
            base_cfg = {
                "port": str(raw["port"]),
                "baudrate": int(raw.get("baudrate", 9600)),
                "timeout_s": float(raw.get("timeout_s", 1.0)),
                "bytesize": 8,
                "parity": "N",
                "stopbits": 2.0,
                "read_termination": "\n",
                "write_termination": "\r\n",
                "output_on_cmd": "OUTP ON",
                "output_off_cmd": "OUTP OFF",
            }
            init_commands = _channel_init_commands(
                channel_map=channel_map,
                valid_channels={"P6V", "P25V", "N25V"},
                command_template=command_template,
                current_limit_a=current_limit_a,
                instrument_name=str(instrument_name),
            )
        elif instrument_type in {"9132C", "BK9132C", "BK_9132C"}:
            channel_map = raw.get("channel_map")
            if not isinstance(channel_map, dict):
                continue
            command_template = str(raw.get("set_voltage_cmd", "APPL {channel}, {value:.6f}, {current_limit_a:.6f}"))
            current_limit_a = float(raw.get("current_limit_a", 0.1))
            base_cfg = {
                "port": str(raw["port"]),
                "baudrate": int(raw.get("baudrate", 9600)),
                "timeout_s": float(raw.get("timeout_s", 1.0)),
                "bytesize": int(raw.get("bytesize", 8)),
                "parity": str(raw.get("parity", "N")),
                "stopbits": float(raw.get("stopbits", 1.0)),
                "read_termination": str(raw.get("read_termination", "\n")),
                "write_termination": str(raw.get("write_termination", "\n")),
                "output_on_cmd": "OUTP:STAT ON",
                "output_off_cmd": "OUTP:STAT OFF",
            }
            init_commands = _channel_init_commands(
                channel_map=channel_map,
                valid_channels={"CH1", "CH2", "CH3"},
                command_template=command_template,
                current_limit_a=current_limit_a,
                instrument_name=str(instrument_name),
            )
        elif instrument_type in {"2400", "KEITHLEY2400", "KEITHLEY_2400"}:
            quantity = str(raw.get("quantity", "")).strip()
            if quantity not in valid_quantities:
                continue

            sources[quantity] = _parse_keithley2400(str(instrument_name), raw)
            continue
        else:
            continue

        for channel, mapped_value in channel_map.items():
            mapped_text = str(mapped_value).strip()
            if mapped_text not in valid_quantities:
                continue

            # Manually substitute channel and current_limit_a, preserving {value:.6f} placeholder
            set_cmd = command_template.replace("{channel}", str(channel).strip()).replace(
                "{current_limit_a:.6f}", f"{current_limit_a:.6f}"
            )
            sources[mapped_text] = SerialDeviceConfig(
                name=f"{instrument_name}:{str(channel).strip()}",
                port=base_cfg["port"],
                baudrate=base_cfg["baudrate"],
                timeout_s=base_cfg["timeout_s"],
                bytesize=base_cfg["bytesize"],
                parity=base_cfg["parity"],
                stopbits=base_cfg["stopbits"],
                read_termination=base_cfg["read_termination"],
                write_termination=base_cfg["write_termination"],
                set_voltage_cmd=set_cmd,
                init_commands=init_commands,
                measure_current_cmd=None,
                output_on_cmd=base_cfg["output_on_cmd"],
                output_off_cmd=base_cfg["output_off_cmd"],
            )

    return sources


def _collect_quantity_sources(instruments: dict[str, Any]) -> dict[str, SerialDeviceConfig]:
    sources = _collect_typed_quantity_sources(instruments)
    valid_quantities = {"Vg", "Vd", "Vb", "Vs", "vgxp", "vgxn"}

    for instrument_name, raw in instruments.items():
        if not isinstance(raw, dict):
            continue

        instrument_type = str(raw.get("type", "serial")).strip().upper()
        if instrument_type in {"E3631A", "9132C", "BK9132C", "BK_9132C", "2400", "KEITHLEY2400", "KEITHLEY_2400"}:
            continue

        quantity = str(raw.get("quantity", "")).strip()
        if quantity not in valid_quantities:
            continue

        sources[quantity] = _parse_serial(str(instrument_name), raw)

    return sources


def _typed_channel_map(raw: dict[str, Any], instrument_name: str) -> dict[str, Any]:
    channel_map = raw.get("channel_map")
    if isinstance(channel_map, dict):
        return channel_map
    channel_map = raw.get("channel_quantity_map")
    if isinstance(channel_map, dict):
        return channel_map
    return _invert_quantity_channel_map(raw.get("quantity_channel_map"), instrument_name)


def _parse_keithley2400_for_role(role_name: str, instrument_name: str, raw: dict[str, Any]) -> SerialDeviceConfig:
    quantity = _role_quantity(role_name)
    configured_quantity = str(raw.get("quantity", "")).strip()
    if configured_quantity != quantity:
        raise ValueError(
            f"instruments.{instrument_name}.quantity={configured_quantity!r} does not satisfy assignment {role_name}"
        )
    return _parse_keithley2400(instrument_name, raw)


def _parse_keithley2400(instrument_name: str, raw: dict[str, Any]) -> SerialDeviceConfig:
    if "port" not in raw:
        raise ValueError(f"instruments.{instrument_name}.port is required")

    return SerialDeviceConfig(
        name=instrument_name,
        port=str(raw["port"]),
        baudrate=int(raw.get("baudrate", 9600)),
        timeout_s=float(raw.get("timeout_s", 1.0)),
        bytesize=int(raw.get("bytesize", 8)),
        parity=str(raw.get("parity", "N")),
        stopbits=float(raw.get("stopbits", 1.0)),
        read_termination=str(raw.get("read_termination", "\\r")),
        write_termination=str(raw.get("write_termination", "\\r")),
        set_voltage_cmd=str(raw.get("set_voltage_cmd", ":SOUR:VOLT {value:.6f}")),
        init_commands=tuple(_str_list(raw.get("init_commands", []))),
        measure_current_cmd=str(raw.get("measure_current_cmd", ":MEAS:CURR?")),
        output_on_cmd=str(raw.get("output_on_cmd", "OUTP ON")),
        output_off_cmd=str(raw.get("output_off_cmd", "OUTP OFF")),
    )


def _role_quantity(role_name: str) -> str:
    role_to_quantity = {
        "gate_source": "Vg",
        "drain_source": "Vd",
        "bulk_source": "Vb",
        "source_source": "Vs",
    }
    quantity = role_to_quantity.get(role_name)
    if quantity is None:
        raise ValueError(f"Unsupported role: {role_name}")
    return quantity


def _parse_e3631a_for_role(role_name: str, instrument_name: str, raw: dict[str, Any]) -> SerialDeviceConfig:
    if "port" not in raw:
        raise ValueError(f"instruments.{instrument_name}.port is required")

    role_to_quantity = {
        "gate_source": "Vg",
        "drain_source": "Vd",
        "bulk_source": "Vb",
        "source_source": "Vs",
    }
    quantity = role_to_quantity.get(role_name)
    if quantity is None:
        raise ValueError(f"Unsupported role for E3631A mapping: {role_name}")

    channel_quantity_map = raw.get("channel_map")
    if not isinstance(channel_quantity_map, dict):
        # Backward compatibility for older config shapes.
        channel_quantity_map = raw.get("channel_quantity_map")
    if not isinstance(channel_quantity_map, dict):
        channel_quantity_map = _invert_quantity_channel_map(raw.get("quantity_channel_map"), instrument_name)

    channel_text = _channel_for_quantity(
        channel_quantity_map=channel_quantity_map,
        quantity=quantity,
        instrument_name=instrument_name,
        role_name=role_name,
        valid_channels={"P6V", "P25V", "N25V"},
    )

    current_limit_a = float(raw.get("current_limit_a", 0.1))
    init_commands = _channel_init_commands(
        channel_map=channel_quantity_map,
        valid_channels={"P6V", "P25V", "N25V"},
        command_template="APPL {channel}, {value:.6f}, {current_limit_a:.6f}",
        current_limit_a=current_limit_a,
        instrument_name=instrument_name,
    )
    return SerialDeviceConfig(
        name=f"{instrument_name}:{channel_text}",
        port=str(raw["port"]),
        baudrate=int(raw.get("baudrate", 9600)),
        timeout_s=float(raw.get("timeout_s", 1.0)),
        bytesize=8,
        parity="N",
        stopbits=2.0,
        read_termination="\n",
        write_termination="\r\n",
        set_voltage_cmd=f"APPL {channel_text}, {{value:.6f}}, {current_limit_a:.6f}",
        init_commands=init_commands,
        measure_current_cmd=None,
        output_on_cmd="OUTP ON",
        output_off_cmd="OUTP OFF",
    )


def _parse_9132c_for_role(role_name: str, instrument_name: str, raw: dict[str, Any]) -> SerialDeviceConfig:
    if "port" not in raw:
        raise ValueError(f"instruments.{instrument_name}.port is required")

    role_to_quantity = {
        "gate_source": "Vg",
        "drain_source": "Vd",
        "bulk_source": "Vb",
        "source_source": "Vs",
    }
    quantity = role_to_quantity.get(role_name)
    if quantity is None:
        raise ValueError(f"Unsupported role for 9132C mapping: {role_name}")

    channel_map = raw.get("channel_map")
    if not isinstance(channel_map, dict):
        raise ValueError(f"instruments.{instrument_name}.channel_map must be a mapping")

    channel_text = _channel_for_quantity(
        channel_quantity_map=channel_map,
        quantity=quantity,
        instrument_name=instrument_name,
        role_name=role_name,
        valid_channels={"CH1", "CH2", "CH3"},
    )

    current_limit_a = float(raw.get("current_limit_a", 0.1))
    command_template = str(
        raw.get("set_voltage_cmd", "APPL {channel}, {value:.6f}, {current_limit_a:.6f}")
    )
    set_voltage_cmd = command_template.format(
        channel=channel_text,
        value="{value:.6f}",
        current_limit_a=current_limit_a,
    )
    init_commands = _channel_init_commands(
        channel_map=channel_map,
        valid_channels={"CH1", "CH2", "CH3"},
        command_template=command_template,
        current_limit_a=current_limit_a,
        instrument_name=instrument_name,
    )

    return SerialDeviceConfig(
        name=f"{instrument_name}:{channel_text}",
        port=str(raw["port"]),
        baudrate=int(raw.get("baudrate", 9600)),
        timeout_s=float(raw.get("timeout_s", 1.0)),
        bytesize=int(raw.get("bytesize", 8)),
        parity=str(raw.get("parity", "N")),
        stopbits=float(raw.get("stopbits", 1.0)),
        read_termination=str(raw.get("read_termination", "\\n")),
        write_termination=str(raw.get("write_termination", "\\n")),
        set_voltage_cmd=set_voltage_cmd,
        init_commands=init_commands,
        measure_current_cmd=None,
        output_on_cmd="OUTP:STAT ON",
        output_off_cmd="OUTP:STAT OFF",
    )


def _channel_for_quantity(
    channel_quantity_map: dict[str, Any],
    quantity: str,
    instrument_name: str,
    role_name: str,
    valid_channels: set[str],
) -> str:
    valid_quantities = {"Vg", "Vd", "Vb", "Vs", "vgxp", "vgxn"}

    for channel, mapped_value in channel_quantity_map.items():
        channel_text = str(channel).strip()
        if channel_text not in valid_channels:
            raise ValueError(f"instruments.{instrument_name}.channel_map has invalid channel '{channel_text}'")

        mapped_text = str(mapped_value).strip()
        if mapped_text.lower() in {"none", "null", ""}:
            continue

        if mapped_text in valid_quantities:
            if mapped_text == quantity:
                return channel_text
            continue

        if _is_voltage_literal(mapped_text):
            # Constant setpoint on this channel, independent of role assignment.
            continue

        raise ValueError(
            f"instruments.{instrument_name}.channel_map.{channel_text} must be Vg/Vd/Vb/Vs/None "
            f"or a fixed voltage like 0.9V"
        )

    raise ValueError(
        f"instruments.{instrument_name} does not map quantity {quantity} to any channel for assignment {role_name}"
    )


def _invert_quantity_channel_map(raw: Any, instrument_name: str) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError(
            f"instruments.{instrument_name}.channel_map must be a mapping (or provide quantity_channel_map)"
        )

    inverted: dict[str, str] = {}
    for quantity, channel in raw.items():
        channel_text = str(channel).strip()
        quantity_text = str(quantity).strip()

        if channel_text.lower() in {"none", "null", ""}:
            continue
        inverted[channel_text] = quantity_text

    return inverted


def _is_voltage_literal(value: str) -> bool:
    return re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:[vV])?", value) is not None


def _parse_voltage_literal(value: str) -> float:
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)(?:[vV])?", value.strip())
    if not match:
        raise ValueError(f"Invalid fixed voltage literal: {value}")
    return float(match.group(1))


def _channel_init_commands(
    channel_map: dict[str, Any],
    valid_channels: set[str],
    command_template: str,
    current_limit_a: float,
    instrument_name: str,
) -> tuple[str, ...]:
    commands: list[str] = []
    valid_quantities = {"Vg", "Vd", "Vb", "Vs", "vgxp", "vgxn"}

    for channel, mapped_value in channel_map.items():
        channel_text = str(channel).strip()
        if channel_text not in valid_channels:
            raise ValueError(f"instruments.{instrument_name}.channel_map has invalid channel '{channel_text}'")

        mapped_text = str(mapped_value).strip()
        if mapped_text.lower() in {"none", "null", ""}:
            continue
        if mapped_text in valid_quantities:
            continue
        if not _is_voltage_literal(mapped_text):
            continue

        fixed_v = _parse_voltage_literal(mapped_text)
        commands.append(
            command_template.format(
                channel=channel_text,
                value=fixed_v,
                current_limit_a=current_limit_a,
            )
        )

    return tuple(commands)


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value]


def _none_or_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"none", "null", ""}:
        return None
    return text
