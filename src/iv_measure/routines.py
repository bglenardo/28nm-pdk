from __future__ import annotations

import csv
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from iv_measure.config import ProjectConfig, SerialDeviceConfig
from iv_measure.serial_instrument import InstrumentError, SerialInstrument


VALID_TERMINALS = {"Vs", "Vd", "Vg", "Vb", "vgxp", "vgxn"}
_DEBUG_SET_CMDS_MAX = int(os.getenv("IV_DEBUG_SET_CMDS", "0"))
_DEBUG_SET_CMDS_COUNT = 0
_DEBUG_BK_READBACK = os.getenv("IV_DEBUG_BK_READBACK", "0") == "1"


@dataclass(frozen=True)
class RoutineSpec:
    name: str
    sweep_param: str
    sweep_start: float
    sweep_stop: float
    sweep_points: int
    step_param: str
    step_start: float
    step_stop: float
    step_points: int
    vg_init: float
    vb_init: float
    vd_init: float
    vs_init: float
    vgxp_init: float
    vgxn_init: float


@dataclass(frozen=True)
class RoutineMeasurement:
    routine: str
    step_param: str
    step_value_v: float
    sweep_param: str
    sweep_value_v: float
    vg_v: float
    vd_v: float
    vb_v: float
    vs_v: float
    vgxp_v: float
    vgxn_v: float
    drain_i_a: float


PointCallback = Callable[[RoutineMeasurement], None]


def load_routines_csv(path: str | Path) -> list[RoutineSpec]:
    routines: list[RoutineSpec] = []
    csv_path = Path(path)

    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("Measurement") or "").strip()
            if not name:
                continue

            sweep_param = _terminal(row.get("Parameter to sweep"), "Parameter to sweep")
            step_param = _terminal(row.get("Parameter to Step"), "Parameter to Step")

            routines.append(
                RoutineSpec(
                    name=name,
                    sweep_param=sweep_param,
                    sweep_start=_to_float(row, "Sweep Start"),
                    sweep_stop=_to_float(row, "Sweep Stop"),
                    sweep_points=_to_int(row, "Num Sweep Points"),
                    step_param=step_param,
                    step_start=_to_float(row, "Step Start"),
                    step_stop=_to_float(row, "Step Stop"),
                    step_points=_to_int(row, "Num Step Points"),
                    vg_init=_to_float(row, "Vg Init"),
                    vb_init=_to_float(row, "Vb Init"),
                    vd_init=_to_float(row, "Vd Init"),
                    vs_init=_to_float(row, "Vs Init"),
                    vgxp_init=_to_float_optional(row, "vgxp Init", 0.0),
                    vgxn_init=_to_float_optional(row, "vgxn Init", 0.0),
                )
            )

    if not routines:
        raise ValueError("No routines found in CSV")

    return routines


def run_routines_from_csv(
    config: ProjectConfig,
    routines_csv: str | Path,
    point_callback: PointCallback | None = None,
) -> list[RoutineMeasurement]:
    routines = load_routines_csv(routines_csv)
    results: list[RoutineMeasurement] = []

    device_pool, gate, drain, bulk = _open_device_pool(config)
    controls = _build_quantity_controls(config, gate, drain, bulk, device_pool)

    try:
        for routine in routines:
            step_values = linear_points(routine.step_start, routine.step_stop, routine.step_points)
            sweep_values = linear_points(routine.sweep_start, routine.sweep_stop, routine.sweep_points)
            init_biases = {
                "Vg": routine.vg_init,
                "Vd": routine.vd_init,
                "Vb": routine.vb_init,
                "Vs": routine.vs_init,
                "vgxp": routine.vgxp_init,
                "vgxn": routine.vgxn_init,
            }

            for step_value in step_values:
                step_biases = dict(init_biases)
                step_biases[routine.step_param] = step_value
                _apply_biases(controls, step_biases)

                for sweep_value in sweep_values:
                    biases = dict(step_biases)
                    biases[routine.sweep_param] = sweep_value

                    if routine.sweep_param != routine.step_param:
                        _apply_biases(controls, {routine.sweep_param: sweep_value})
                    else:
                        _apply_biases(controls, {routine.step_param: sweep_value})

                    time.sleep(config.sweep.settle_s)
                    drain_i = _measure_current_a(drain)

                    measurement = RoutineMeasurement(
                        routine=routine.name,
                        step_param=routine.step_param,
                        step_value_v=step_value,
                        sweep_param=routine.sweep_param,
                        sweep_value_v=sweep_value,
                        vg_v=biases["Vg"],
                        vd_v=biases["Vd"],
                        vb_v=biases["Vb"],
                        vs_v=biases["Vs"],
                        vgxp_v=biases["vgxp"],
                        vgxn_v=biases["vgxn"],
                        drain_i_a=drain_i,
                    )
                    results.append(measurement)
                    if point_callback is not None:
                        point_callback(measurement)
    finally:
        _ramp_controls_to_zero(controls)
        for device in device_pool.values():
            _stop_measurement(device)
            _output_off(device)
            _force_bk9132c_off(device)
            device.close()

    return results


def run_first_routine_from_csv(
    config: ProjectConfig,
    routines_csv: str | Path,
    routine_index: int = 0,
    point_callback: PointCallback | None = None,
) -> tuple[RoutineSpec, list[RoutineMeasurement]]:
    routines = load_routines_csv(routines_csv)
    if routine_index < 0 or routine_index >= len(routines):
        raise ValueError(f"routine_index {routine_index} out of range [0, {len(routines) - 1}]")

    first_routine = routines[routine_index]
    results: list[RoutineMeasurement] = []

    device_pool, gate, drain, bulk = _open_device_pool(config)
    controls = _build_quantity_controls(config, gate, drain, bulk, device_pool)

    try:
        init_biases = {
            "Vg": first_routine.vg_init,
            "Vd": first_routine.vd_init,
            "Vb": first_routine.vb_init,
            "Vs": first_routine.vs_init,
            "vgxp": first_routine.vgxp_init,
            "vgxn": first_routine.vgxn_init,
        }
        _apply_biases(controls, init_biases)
        time.sleep(config.sweep.settle_s)

        step_values = linear_points(first_routine.step_start, first_routine.step_stop, first_routine.step_points)
        sweep_values = linear_points(first_routine.sweep_start, first_routine.sweep_stop, first_routine.sweep_points)

        for step_value in step_values:
            step_biases = dict(init_biases)
            step_biases[first_routine.step_param] = step_value
            _apply_biases(controls, step_biases)

            for sweep_value in sweep_values:
                biases = dict(step_biases)
                biases[first_routine.sweep_param] = sweep_value

                if first_routine.sweep_param != first_routine.step_param:
                    _apply_biases(controls, {first_routine.sweep_param: sweep_value})
                else:
                    _apply_biases(controls, {first_routine.step_param: sweep_value})

                time.sleep(config.sweep.settle_s)
                drain_i = _measure_current_a(drain)

                measurement = RoutineMeasurement(
                    routine=first_routine.name,
                    step_param=first_routine.step_param,
                    step_value_v=step_value,
                    sweep_param=first_routine.sweep_param,
                    sweep_value_v=sweep_value,
                    vg_v=biases["Vg"],
                    vd_v=biases["Vd"],
                    vb_v=biases["Vb"],
                    vs_v=biases["Vs"],
                    vgxp_v=biases["vgxp"],
                    vgxn_v=biases["vgxn"],
                    drain_i_a=drain_i,
                )
                results.append(measurement)
                if point_callback is not None:
                    point_callback(measurement)
    finally:
        _ramp_controls_to_zero(controls)
        for device in device_pool.values():
            _stop_measurement(device)
            _output_off(device)
            _force_bk9132c_off(device)
            device.close()

    return first_routine, results


def write_routine_measurements_csv(path: str | Path, points: list[RoutineMeasurement]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "routine",
                "step_param",
                "step_value_v",
                "sweep_param",
                "sweep_value_v",
                "vg_v",
                "vd_v",
                "vb_v",
                "vs_v",
                "vgxp_v",
                "vgxn_v",
                "drain_i_a",
            ]
        )
        for p in points:
            writer.writerow(
                [
                    p.routine,
                    p.step_param,
                    p.step_value_v,
                    p.sweep_param,
                    p.sweep_value_v,
                    p.vg_v,
                    p.vd_v,
                    p.vb_v,
                    p.vs_v,
                    p.vgxp_v,
                    p.vgxn_v,
                    p.drain_i_a,
                ]
            )


def linear_points(start: float, stop: float, num_points: int) -> list[float]:
    if num_points < 1:
        raise ValueError("Number of points must be >= 1")
    if num_points == 1:
        return [float(start)]

    step = (stop - start) / (num_points - 1)
    return [round(start + i * step, 12) for i in range(num_points)]


def _terminal(raw: str | None, field_name: str) -> str:
    if raw is None:
        raise ValueError(f"Missing field: {field_name}")

    value = raw.strip()
    if value not in VALID_TERMINALS:
        raise ValueError(f"Unsupported terminal '{value}' in {field_name}")
    return value


def _to_float(row: dict[str, str], key: str) -> float:
    value = row.get(key)
    if value is None or value.strip() == "":
        raise ValueError(f"Missing float field: {key}")
    return float(value)


def _to_float_optional(row: dict[str, str], key: str, default: float) -> float:
    value = row.get(key)
    if value is None or value.strip() == "":
        return default
    return float(value)


def _to_int(row: dict[str, str], key: str) -> int:
    value = row.get(key)
    if value is None or value.strip() == "":
        raise ValueError(f"Missing int field: {key}")
    return int(value)


def _set_voltage(device: SerialInstrument, voltage_v: float) -> None:
    device.send_scpi(device.config.set_voltage_cmd.format(value=voltage_v))


def _bk_channel_from_name(name: str) -> str | None:
    """Extract 'CH1'/'CH2'/'CH3' from a config name like 'bk_9132c:CH1'."""
    import re
    m = re.search(r"\b(CH[123])\b", name, re.IGNORECASE)
    return m.group(1).upper() if m else None


def _output_on(device: SerialInstrument) -> None:
    name = device.config.name.lower()
    if "9132" in name or "bk" in name:
        channel = _bk_channel_from_name(device.config.name)
        for command in ("OUTP:STAT 1",):
            try:
                device.send_scpi(command)
            except InstrumentError:
                continue
        if channel:
            try:
                device.send_scpi(f"INST {channel}")
                device.send_scpi("CHAN:OUTP 1")
            except InstrumentError:
                pass
            return
    command = device.config.output_on_cmd
    if command:
        device.send_scpi(command)


def _output_off(device: SerialInstrument) -> None:
    name = device.config.name.lower()
    if "9132" in name or "bk" in name:
        channel = _bk_channel_from_name(device.config.name)
        for command in ("OUTP:STAT 0",):
            try:
                device.send_scpi(command)
            except InstrumentError:
                continue
        if channel:
            try:
                device.send_scpi(f"INST {channel}")
                device.send_scpi("CHAN:OUTP 0")
            except InstrumentError:
                pass
            return
    command = device.config.output_off_cmd
    if command:
        device.send_scpi(command)


def _stop_measurement(device: SerialInstrument) -> None:
    """Best-effort stop for instruments that can remain in an active trigger state."""
    name = device.config.name.lower()
    if "2400" not in name:
        return

    for command in (":ABOR", ":TRIG:COUN 1"):
        try:
            device.send_scpi(command)
        except InstrumentError:
            # Some firmware variants may not support every stop command.
            continue


def _force_bk9132c_off(device: SerialInstrument) -> None:
    """Per-channel output disable for BK 9132C at teardown."""
    name = device.config.name.lower()
    if "9132" not in name and "bk" not in name:
        return

    for command in ("OUTP:STAT 0", "OUTP OFF", "OUT OFF", "OUTPUT OFF", "OUTP 0"):
        try:
            device.send_scpi(command)
        except InstrumentError:
            continue

    channel = _bk_channel_from_name(device.config.name)
    if channel:
        try:
            device.send_scpi(f"INST {channel}")
            device.send_scpi("CHAN:OUTP 0")
        except InstrumentError:
            pass


def _apply_init_commands(device: SerialInstrument) -> None:
    for command in device.config.init_commands:
        device.send_scpi(command)


def _clear_status(device: SerialInstrument) -> None:
    """Best-effort clear of stale status/error/query state from prior sessions."""
    try:
        device.send_scpi("*CLS")
    except InstrumentError:
        pass


def _measure_current_a(device: SerialInstrument) -> float:
    command = device.config.measure_current_cmd
    if not command:
        raise InstrumentError(f"{device.config.name} has no measure_current_cmd")

    raw = device.query_scpi(command)
    parts = [p.strip() for p in raw.split(",")]
    # With :FORM:ELEM CURR configured, a single value is returned.
    # Fallback: 2400 default 5-element order is VOLT, CURR, RES, TIME, STAT.
    index = 1 if len(parts) >= 2 else 0
    try:
        return float(parts[index])
    except ValueError as exc:
        raise InstrumentError(f"{device.config.name} returned non-numeric current: {raw!r}") from exc


def _apply_biases(
    controls: dict[str, tuple[SerialInstrument, str]],
    biases: dict[str, float],
) -> None:
    global _DEBUG_SET_CMDS_COUNT
    for quantity, (device, set_cmd) in controls.items():
        if quantity not in biases:
            continue
        command = set_cmd.format(value=biases[quantity])
        device.send_scpi(command)
        _apply_bk9132c_set_fallback(device, command)
        if _DEBUG_BK_READBACK and quantity in {"vgxp", "vgxn"}:
            _debug_bk9132c_readback(device, command, quantity)
        if _DEBUG_SET_CMDS_MAX > 0 and _DEBUG_SET_CMDS_COUNT < _DEBUG_SET_CMDS_MAX and quantity in {"Vg", "Vb", "Vd", "vgxp", "vgxn"}:
            print(f"DEBUG_SET {quantity} [{device.config.name}] -> {command}")
            _DEBUG_SET_CMDS_COUNT += 1


def _apply_bk9132c_set_fallback(device: SerialInstrument, applied_command: str) -> None:
    """Fallback for BK 9132C firmware that may ignore APPL despite accepting it."""
    name = device.config.name.lower()
    if "9132" not in name and "bk" not in name:
        return

    match = re.fullmatch(
        r"\s*APPL(?:Y)?\s+(CH[123])\s*,\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*",
        applied_command,
        flags=re.IGNORECASE,
    )
    if not match:
        return

    channel = match.group(1).upper()
    voltage = match.group(2)
    current = match.group(3)

    # This sequence is broadly supported across BK firmware revisions.
    try:
        device.send_scpi("OUTP:STAT 1")
    except InstrumentError:
        pass

    try:
        device.send_scpi(f"INST {channel}")
        device.send_scpi(f"VOLT {voltage}")
        device.send_scpi(f"CURR {current}")
        device.send_scpi("CHAN:OUTP 1")
    except InstrumentError:
        pass


def _debug_bk9132c_readback(device: SerialInstrument, applied_command: str, quantity: str) -> None:
    """Optional BK readback logs to verify that script-applied settings reach the instrument."""
    name = device.config.name.lower()
    if "9132" not in name and "bk" not in name:
        return

    match = re.fullmatch(
        r"\s*APPL(?:Y)?\s+(CH[123])\s*,\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*",
        applied_command,
        flags=re.IGNORECASE,
    )
    if not match:
        return

    channel = match.group(1).upper()
    try:
        device.send_scpi(f"INST {channel}")
        measured_v = device.query_scpi("MEAS:VOLT?")
        measured_i = device.query_scpi("MEAS:CURR?")
        print(
            f"DEBUG_BK {quantity} [{device.config.name}] {channel} "
            f"set={match.group(2)}V lim={match.group(3)}A measV={measured_v} measI={measured_i}"
        )
    except InstrumentError as exc:
        print(f"DEBUG_BK {quantity} [{device.config.name}] readback failed: {exc}")


def _ramp_controls_to_zero(controls: dict[str, tuple[SerialInstrument, str]]) -> None:
    seen: set[tuple[str, str]] = set()
    for _quantity, (device, set_cmd) in controls.items():
        key = (device.config.name, set_cmd)
        if key in seen:
            continue
        seen.add(key)
        device.send_scpi(set_cmd.format(value=0.0))


def _open_device_pool(
    config: ProjectConfig,
) -> tuple[dict[str, SerialInstrument], SerialInstrument, SerialInstrument, SerialInstrument | None]:
    """Open each unique physical port exactly once and return the pool plus gate/drain/bulk references."""
    device_pool: dict[str, SerialInstrument] = {}

    def _get_or_open(cfg: SerialDeviceConfig) -> SerialInstrument:
        key = _device_key(cfg)
        if key not in device_pool:
            device = SerialInstrument(cfg)
            device.open()
            _clear_status(device)
            _output_on(device)
            _apply_init_commands(device)
            device_pool[key] = device
        return device_pool[key]

    gate = _get_or_open(config.gate_source)
    drain = _get_or_open(config.drain_source)
    bulk = _get_or_open(config.bulk_source) if config.bulk_source else None

    # Pre-open any additional quantity sources so the pool is complete.
    for source_cfg in config.quantity_sources.values():
        _get_or_open(source_cfg)

    return device_pool, gate, drain, bulk


def _build_quantity_controls(
    config: ProjectConfig,
    gate: SerialInstrument,
    drain: SerialInstrument,
    bulk: SerialInstrument | None,
    device_pool: dict[str, SerialInstrument],
) -> dict[str, tuple[SerialInstrument, str]]:
    controls: dict[str, tuple[SerialInstrument, str]] = {}

    # Use quantity_sources first so each quantity keeps its own channel-specific set command.
    # This is critical when multiple quantities share one physical instrument/port.
    for quantity, source_cfg in config.quantity_sources.items():
        key = _device_key(source_cfg)
        device = device_pool.get(key)
        if device is None:
            continue
        controls[quantity] = (device, source_cfg.set_voltage_cmd)

    # Backward-compatible fallback if a quantity was not present in quantity_sources.
    if "Vg" not in controls:
        controls["Vg"] = (gate, gate.config.set_voltage_cmd)
    if "Vd" not in controls:
        controls["Vd"] = (drain, drain.config.set_voltage_cmd)
    if bulk and "Vb" not in controls:
        controls["Vb"] = (bulk, bulk.config.set_voltage_cmd)

    return controls


def _device_key(config: SerialDeviceConfig) -> str:
    return "|".join(
        [
            config.port,
            str(config.baudrate),
            str(config.bytesize),
            config.parity,
            str(config.stopbits),
            config.read_termination,
            config.write_termination,
        ]
    )
