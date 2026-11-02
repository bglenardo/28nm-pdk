from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from iv_measure.config import SerialDeviceConfig
from iv_measure.serial_instrument import VisaInstrument
from iv_measure.bench import _is_serial_port_name, _serial_port_names


def test_is_serial_port_name_filters_visa_resources() -> None:
    assert _is_serial_port_name("COM10") is True
    assert _is_serial_port_name("COM14") is True
    assert _is_serial_port_name("GPIB0::5::INSTR") is False
    assert _is_serial_port_name("USB0::0x1234::0x5678::INSTR") is False
    assert _is_serial_port_name("") is False


def test_serial_port_names_skips_visa_addresses() -> None:
    names = [
        "COM10",
        "GPIB0::5::INSTR",
        "",
        "COM14",
        "USB0::0x1AB1::0x0E11::INSTR",
    ]
    assert _serial_port_names(names) == ["COM10", "COM14"]


def test_visa_missing_backend_reports_actionable_error(monkeypatch) -> None:
    import iv_measure.serial_instrument as serial_instrument_module

    def fake_resource_manager(*args, **kwargs):
        raise OSError("missing visa library")

    monkeypatch.setattr(serial_instrument_module.pyvisa, "ResourceManager", fake_resource_manager)

    instrument = VisaInstrument(
        SerialDeviceConfig(
            name="keithley_2401",
            resource_name="GPIB0::24::INSTR",
            timeout_s=1.0,
        )
    )

    with pytest.raises(RuntimeError, match="No VISA backend could be loaded"):
        instrument.open()
