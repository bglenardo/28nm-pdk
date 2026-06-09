from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from iv_measure.config import SerialDeviceConfig
from iv_measure.serial_instrument import InstrumentError, SerialInstrument

SourceMode = Literal["VOLT", "CURR"]
_VALID_SOURCE_MODES = {"VOLT", "CURR"}


def build_voltage_source_init_commands(
    current_compliance_a: float,
    remote_sense: bool = False,
    source_voltage_range_v: float = 2.0,
) -> tuple[str, ...]:
    return (
        "*RST",
        ":SOUR:FUNC VOLT",
        ":SENS:FUNC \"CURR\"",
        f":SENS:CURR:PROT {current_compliance_a:.6f}",
        ":SENS:CURR:RANG:AUTO ON",
        f":SYST:RSEN {'ON' if remote_sense else 'OFF'}",
        f":SOUR:VOLT:RANG {source_voltage_range_v:.6f}",
        ":TRIG:COUN 1",
        ":FORM:ELEM CURR",
    )


@dataclass
class Keithley2400:
    """Driver for Keithley 2400 SourceMeter over SCPI/serial."""

    port: str
    baudrate: int = 9600
    timeout_s: float = 1.0
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1.0
    write_termination: str = "\r"
    read_termination: str = "\r"
    current_compliance_a: float = 0.01
    remote_sense: bool = False
    source_voltage_range_v: float = 2.0

    def __post_init__(self) -> None:
        config = SerialDeviceConfig(
            name=f"keithley2400:{self.port}",
            port=self.port,
            baudrate=self.baudrate,
            timeout_s=self.timeout_s,
            bytesize=self.bytesize,
            parity=self.parity,
            stopbits=self.stopbits,
            write_termination=self.write_termination,
            read_termination=self.read_termination,
            current_compliance_a=self.current_compliance_a,
            measure_current_cmd=None,
        )
        self._transport = SerialInstrument(config)

    def open(self) -> None:
        self._transport.open()
        for command in build_voltage_source_init_commands(
            current_compliance_a=self.current_compliance_a,
            remote_sense=self.remote_sense,
            source_voltage_range_v=self.source_voltage_range_v,
        ):
            self.send_scpi(command)

    def close(self) -> None:
        self._transport.close()

    def send_scpi(self, command: str) -> None:
        self._transport.send_scpi(command)

    def query_scpi(self, command: str) -> str:
        return self._transport.query_scpi(command)

    def identify(self) -> str:
        return self.query_scpi("*IDN?")

    def reset(self) -> None:
        self.send_scpi("*RST")

    def output_on(self) -> None:
        self.send_scpi("OUTP ON")

    def output_off(self) -> None:
        self.send_scpi("OUTP OFF")

    def set_source_mode(self, mode: SourceMode) -> None:
        if mode not in _VALID_SOURCE_MODES:
            raise ValueError(f"Unsupported Keithley 2400 source mode: {mode}")
        self.send_scpi(f":SOUR:FUNC {mode}")

    def source_voltage(self, voltage_v: float, current_compliance_a: float) -> None:
        self.set_source_mode("VOLT")
        self.send_scpi(":SENS:FUNC \"CURR\"")
        self.send_scpi(f":SENS:CURR:PROT {current_compliance_a:.6f}")
        self.send_scpi(f":SOUR:VOLT {voltage_v:.6f}")

    def source_current(self, current_a: float, voltage_compliance_v: float) -> None:
        self.set_source_mode("CURR")
        self.send_scpi(":SENS:FUNC \"VOLT\"")
        self.send_scpi(f":SENS:VOLT:PROT {voltage_compliance_v:.6f}")
        self.send_scpi(f":SOUR:CURR {current_a:.6f}")

    def measure_source_current(self) -> float:
        return _parse_float_response(self.query_scpi(":MEAS:CURR?"), "source current")

    def measure_sense_voltage(self) -> float:
        return _parse_float_response(self.query_scpi(":MEAS:VOLT?"), "sense voltage")

    def measure_current_and_voltage(self) -> tuple[float, float]:
        current_a = self.measure_source_current()
        voltage_v = self.measure_sense_voltage()
        return current_a, voltage_v

    def __enter__(self) -> "Keithley2400":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _parse_float_response(raw: str, quantity_name: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise InstrumentError(f"Keithley 2400 returned non-numeric {quantity_name}: {raw!r}") from exc