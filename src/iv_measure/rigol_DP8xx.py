from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pyvisa

RigolChannel = Literal["CH1", "CH2", "CH3"]
_VALID_CHANNELS = {"CH1", "CH2", "CH3"}


@dataclass
class RigolDP8xx:
    """
    Driver for Rigol DP800-series triple-output power supply over USB/VISA.

    Unlike the E3631A (which addresses channels implicitly via APPL), the
    Rigol DP800 series requires explicitly selecting the active channel with
    ':INST CHx' before most commands (voltage, current, protection, output)
    take effect on that channel.
    """

    resource_name: str  # e.g. "USB0::0x1AB1::0x0E11::DP8F262800251::INSTR"
    timeout_ms: int = 5000
    resource_manager: pyvisa.ResourceManager | None = None

    def __post_init__(self) -> None:
        # Allow an external ResourceManager to be shared/injected (e.g. so a
        # caller can list/reuse one instance across multiple instruments);
        # otherwise create our own.
        self._rm = self.resource_manager or pyvisa.ResourceManager()
        self._instrument: pyvisa.resources.MessageBasedResource | None = None

    def open(self) -> None:
        self._instrument = self._rm.open_resource(self.resource_name)
        self._instrument.timeout = self.timeout_ms

    def close(self) -> None:
        if self._instrument is not None:
            self._instrument.close()
            self._instrument = None

    def send_scpi(self, command: str) -> None:
        if self._instrument is None:
            raise RuntimeError("Instrument not open. Call open() first.")
        self._instrument.write(command)

    def query_scpi(self, command: str) -> str:
        if self._instrument is None:
            raise RuntimeError("Instrument not open. Call open() first.")
        return self._instrument.query(command).strip()

    def identify(self) -> str:
        return self.query_scpi("*IDN?")

    def _select_channel(self, channel: RigolChannel) -> None:
        """Rigol DP800 requires the target channel to be selected before
        most voltage/current/output commands will apply to it."""
        if channel not in _VALID_CHANNELS:
            raise ValueError(f"Unsupported Rigol channel: {channel}")
        self.send_scpi(f":INST {channel}")

    def output_on(self, channel: RigolChannel) -> None:
        self._select_channel(channel)
        self.send_scpi(f":OUTP {channel}, ON")

    def output_off(self, channel: RigolChannel) -> None:
        self._select_channel(channel)
        self.send_scpi(f":OUTP {channel}, OFF")

    def apply(
        self,
        channel: RigolChannel,
        voltage_v: float,
        current_limit_a: float,
        voltage_protection_v: float | None = None,
        current_protection_a: float | None = None,
    ) -> None:
        """
        Set voltage/current on a channel and turn its output on, mirroring
        the E3631A's single-call `apply()` convenience method. Optionally
        also configures and enables over-voltage/over-current protection,
        matching the manual sequence seen in the original Rigol script
        (:VOLT:PROT, :VOLT:PROT:STAT ON, :CURR:PROT, :CURR:PROT:STAT ON).
        """
        self._select_channel(channel)
        self.send_scpi(f":VOLT {voltage_v:.6f}")
        self.send_scpi(f":CURR {current_limit_a:.6f}")

        if voltage_protection_v is not None:
            self.send_scpi(f":VOLT:PROT {voltage_protection_v:.6f}")
            self.send_scpi(":VOLT:PROT:STAT ON")

        if current_protection_a is not None:
            self.send_scpi(f":CURR:PROT {current_protection_a:.6f}")
            self.send_scpi(":CURR:PROT:STAT ON")

        self.send_scpi(f":OUTP {channel}, ON")

    def measure_voltage(self, channel: RigolChannel) -> float:
        return float(self.query_scpi(f":MEAS:VOLT? {channel}"))

    def measure_current(self, channel: RigolChannel) -> float:
        return float(self.query_scpi(f":MEAS:CURR? {channel}"))

    def __enter__(self) -> "RigolDP8xx":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
