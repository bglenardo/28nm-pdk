from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from iv_measure.config import SerialDeviceConfig
from iv_measure.serial_instrument import SerialInstrument

E3631AChannel = Literal["P6V", "P25V", "N25V"]
_VALID_CHANNELS = {"P6V", "P25V", "N25V"}


@dataclass
class E3631A:
    """Driver for Keithley/HP E3631A triple-output power supply over RS-232."""

    port: str
    baudrate: int = 9600
    timeout_s: float = 1.0

    def __post_init__(self) -> None:
        config = SerialDeviceConfig(
            name=f"e3631a:{self.port}",
            port=self.port,
            baudrate=self.baudrate,
            timeout_s=self.timeout_s,
            bytesize=8,
            parity="N",
            stopbits=2.0,
            write_termination="\r\n",
            read_termination="\n",
            measure_current_cmd=None,
        )
        self._transport = SerialInstrument(config)

    def open(self) -> None:
        self._transport.open()

    def close(self) -> None:
        self._transport.close()

    def send_scpi(self, command: str) -> None:
        self._transport.send_scpi(command)

    def query_scpi(self, command: str) -> str:
        return self._transport.query_scpi(command)

    def identify(self) -> str:
        return self.query_scpi("*IDN?")

    def output_on(self) -> None:
        self.send_scpi("OUTP ON")

    def output_off(self) -> None:
        self.send_scpi("OUTP OFF")

    def apply(self, channel: E3631AChannel, voltage_v: float, current_limit_a: float) -> None:
        if channel not in _VALID_CHANNELS:
            raise ValueError(f"Unsupported E3631A channel: {channel}")

        self.send_scpi(f"APPL {channel}, {voltage_v:.6f}, {current_limit_a:.6f}")

    def __enter__(self) -> "E3631A":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()