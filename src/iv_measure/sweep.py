from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path

from iv_measure.config import ProjectConfig
from iv_measure.serial_instrument import InstrumentError, SerialInstrument


@dataclass(frozen=True)
class MeasurementPoint:
    gate_v: float
    drain_v: float
    drain_i_a: float


def drain_voltage_points(start_v: float, stop_v: float, step_v: float) -> list[float]:
    points: list[float] = []
    current = start_v
    epsilon = step_v / 1000

    while current <= stop_v + epsilon:
        points.append(round(current, 12))
        current += step_v

    return points


def run_iv_sweep(config: ProjectConfig) -> list[MeasurementPoint]:
    points: list[MeasurementPoint] = []
    drain_points = drain_voltage_points(
        start_v=config.sweep.drain_start_v,
        stop_v=config.sweep.drain_stop_v,
        step_v=config.sweep.drain_step_v,
    )

    with SerialInstrument(config.gate_source) as gate, SerialInstrument(config.drain_source) as drain:
        _output_on(gate)
        _output_on(drain)

        try:
            for gate_v in config.sweep.gate_voltages_v:
                _set_voltage(gate, gate_v)
                time.sleep(config.sweep.settle_s)

                for drain_v in drain_points:
                    _set_voltage(drain, drain_v)
                    time.sleep(config.sweep.settle_s)
                    drain_i = _measure_current_a(drain)
                    points.append(MeasurementPoint(gate_v=gate_v, drain_v=drain_v, drain_i_a=drain_i))
        finally:
            # Always ramp outputs back to 0 V before turning channels off.
            _set_voltage(gate, 0.0)
            _set_voltage(drain, 0.0)
            _output_off(gate)
            _output_off(drain)

    return points


def write_measurements_csv(path: str | Path, points: list[MeasurementPoint]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["gate_v", "drain_v", "drain_i_a"])
        for p in points:
            writer.writerow([p.gate_v, p.drain_v, p.drain_i_a])


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
