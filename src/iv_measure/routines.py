from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path

from iv_measure.config import ProjectConfig
from iv_measure.serial_instrument import InstrumentError, SerialInstrument


VALID_TERMINALS = {"Vs", "Vd", "Vg", "Vb"}


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
    drain_i_a: float


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
                )
            )

    if not routines:
        raise ValueError("No routines found in CSV")

    return routines


def run_routines_from_csv(
    config: ProjectConfig,
    routines_csv: str | Path,
) -> list[RoutineMeasurement]:
    routines = load_routines_csv(routines_csv)
    results: list[RoutineMeasurement] = []

    with SerialInstrument(config.gate_source) as gate, SerialInstrument(config.drain_source) as drain:
        bulk = SerialInstrument(config.bulk_source) if config.bulk_source else None

        if bulk:
            bulk.open()

        _output_on(gate)
        _output_on(drain)
        if bulk:
            _output_on(bulk)

        try:
            for routine in routines:
                step_values = linear_points(routine.step_start, routine.step_stop, routine.step_points)
                sweep_values = linear_points(routine.sweep_start, routine.sweep_stop, routine.sweep_points)

                for step_value in step_values:
                    for sweep_value in sweep_values:
                        biases = {
                            "Vg": routine.vg_init,
                            "Vd": routine.vd_init,
                            "Vb": routine.vb_init,
                            "Vs": 0.0,
                        }
                        biases[routine.step_param] = step_value
                        biases[routine.sweep_param] = sweep_value
                        biases["Vs"] = 0.0

                        _set_voltage(gate, biases["Vg"])
                        _set_voltage(drain, biases["Vd"])

                        if bulk:
                            _set_voltage(bulk, biases["Vb"])
                        elif abs(biases["Vb"]) > 1e-12:
                            raise InstrumentError(
                                "Routine needs non-zero Vb but instruments.bulk_source is not configured"
                            )

                        time.sleep(config.sweep.settle_s)
                        drain_i = _measure_current_a(drain)

                        results.append(
                            RoutineMeasurement(
                                routine=routine.name,
                                step_param=routine.step_param,
                                step_value_v=step_value,
                                sweep_param=routine.sweep_param,
                                sweep_value_v=sweep_value,
                                vg_v=biases["Vg"],
                                vd_v=biases["Vd"],
                                vb_v=biases["Vb"],
                                vs_v=0.0,
                                drain_i_a=drain_i,
                            )
                        )
        finally:
            _set_voltage(gate, 0.0)
            _set_voltage(drain, 0.0)
            if bulk:
                _set_voltage(bulk, 0.0)

            _output_off(gate)
            _output_off(drain)
            if bulk:
                _output_off(bulk)
                bulk.close()

    return results


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


def _to_int(row: dict[str, str], key: str) -> int:
    value = row.get(key)
    if value is None or value.strip() == "":
        raise ValueError(f"Missing int field: {key}")
    return int(value)


def _set_voltage(device: SerialInstrument, voltage_v: float) -> None:
    device.send_scpi(device.config.set_voltage_cmd.format(value=voltage_v))


def _output_on(device: SerialInstrument) -> None:
    command = device.config.output_on_cmd
    if command:
        device.send_scpi(command)


def _output_off(device: SerialInstrument) -> None:
    command = device.config.output_off_cmd
    if command:
        device.send_scpi(command)


def _measure_current_a(device: SerialInstrument) -> float:
    command = device.config.measure_current_cmd
    if not command:
        raise InstrumentError(f"{device.config.name} has no measure_current_cmd")

    raw = device.query_scpi(command)
    try:
        return float(raw)
    except ValueError as exc:
        raise InstrumentError(f"{device.config.name} returned non-numeric current: {raw!r}") from exc
