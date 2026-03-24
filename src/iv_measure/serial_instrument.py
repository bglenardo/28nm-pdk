from __future__ import annotations

from dataclasses import dataclass

import serial

from iv_measure.config import SerialDeviceConfig


class InstrumentError(RuntimeError):
    """Raised when an instrument returns an invalid response."""


@dataclass
class SerialInstrument:
    config: SerialDeviceConfig

    def __post_init__(self) -> None:
        self._ser: serial.Serial | None = None

    def open(self) -> None:
        if self._ser and self._ser.is_open:
            return

        self._ser = serial.Serial(
            port=self.config.port,
            baudrate=self.config.baudrate,
            bytesize=self.config.bytesize,
            parity=self.config.parity,
            stopbits=self.config.stopbits,
            timeout=self.config.timeout_s,
        )

    def close(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()

    def send_scpi(self, command: str) -> None:
        if not self._ser or not self._ser.is_open:
            raise InstrumentError(f"{self.config.name} is not open")

        payload = f"{command}{self.config.write_termination}"
        self._ser.write(payload.encode("ascii", errors="ignore"))

    def read_scpi(self) -> str:
        if not self._ser:
            raise InstrumentError(f"{self.config.name} is not open")

        response = self._ser.read_until(self.config.read_termination.encode("ascii", errors="ignore"))
        return response.decode("ascii", errors="ignore").strip()

    def query_scpi(self, command: str) -> str:
        self.send_scpi(command)
        return self.read_scpi()

    def __enter__(self) -> "SerialInstrument":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
