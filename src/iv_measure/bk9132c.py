from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from iv_measure.config import SerialDeviceConfig
from iv_measure.serial_instrument import SerialInstrument

BK9132CChannel = Literal["CH1", "CH2", "CH3"]
_VALID_CHANNELS = {"CH1", "CH2", "CH3"}


@dataclass
class BK9132C:
    """Driver for BK Precision 9132C triple-output power supply over RS-232."""

    port: str
    baudrate: int = 9600
    timeout_s: float = 1.0
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1.0
    write_termination: str = "\r\n"
    read_termination: str = "\n"
    apply_cmd_template: str = "APPL {channel}, {voltage:.6f}, {current_limit:.6f}"

    def __post_init__(self) -> None:
        config = SerialDeviceConfig(
            name=f"bk9132c:{self.port}",
            port=self.port,
            baudrate=self.baudrate,
            timeout_s=self.timeout_s,
            bytesize=self.bytesize,
            parity=self.parity,
            stopbits=self.stopbits,
            write_termination=self.write_termination,
            read_termination=self.read_termination,
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

    def channel_output_on(self, channel: BK9132CChannel) -> None:
        """Enable output for a single channel. Must call INST first per the 9132C manual."""
        if channel not in _VALID_CHANNELS:
            raise ValueError(f"Unsupported 9132C channel: {channel}")
        self.send_scpi(f"INST {channel}")
        self.send_scpi("CHAN:OUTP 1")

    def channel_output_off(self, channel: BK9132CChannel) -> None:
        """Disable output for a single channel."""
        if channel not in _VALID_CHANNELS:
            raise ValueError(f"Unsupported 9132C channel: {channel}")
        self.send_scpi(f"INST {channel}")
        self.send_scpi("CHAN:OUTP 0")

    def output_on(self) -> None:
        """Enable output on all three channels."""
        # Global output state per manual.
        self.send_scpi("OUTP:STAT 1")
        # Per-channel output state requires INST selection.
        for ch in ("CH1", "CH2", "CH3"):
            self.channel_output_on(ch)  # type: ignore[arg-type]

    def output_off(self) -> None:
        """Disable output on all three channels."""
        self.send_scpi("OUTP:STAT 0")
        for ch in ("CH1", "CH2", "CH3"):
            self.channel_output_off(ch)  # type: ignore[arg-type]

    def apply(self, channel: BK9132CChannel, voltage_v: float, current_limit_a: float) -> None:
        if channel not in _VALID_CHANNELS:
            raise ValueError(f"Unsupported 9132C channel: {channel}")

        command = self.apply_cmd_template.format(
            channel=channel,
            voltage=voltage_v,
            current_limit=current_limit_a,
        )
        self.send_scpi(command)

    def __enter__(self) -> "BK9132C":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
