from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import serial

try:
    import pyvisa
except ImportError:  # pragma: no cover - optional dependency for GPIB/VISA use
    pyvisa = None

from iv_measure.config import SerialDeviceConfig


class InstrumentError(RuntimeError):
    """Raised when an instrument returns an invalid response."""


# Known native VISA backend locations. PyVISA's auto-discovery is unreliable on
# Windows (it depends on PATH / registry state that varies between terminals),
# so we fall back to these explicit paths. In the Win64 tree the file named
# ``visa32.dll`` is in fact the 64-bit library (IVI/Keysight naming convention).
_VISA_BACKEND_CANDIDATES = (
    r"C:\Program Files\IVI Foundation\VISA\Win64\ktvisa\ktbin\visa32.dll",
    r"C:\Program Files\IVI Foundation\VISA\Win64\agvisa\agbin\visa32.dll",
    r"C:\Windows\System32\visa64.dll",
    r"C:\Windows\System32\visa32.dll",
)

# Directories holding the native implementation DLLs that the thin ``visa32.dll``
# loader depends on (e.g. ioGPIB.dll, instr32.dll, rsrcm32.dll). On Python 3.8+
# DLL dependency resolution no longer uses PATH, so a bare ``visa32.dll`` load
# fails with VI_ERROR_LIBRARY_NFOUND unless these dirs are registered via
# ``os.add_dll_directory``.
_VISA_DEPENDENCY_DIRS = (
    r"C:\Program Files\Keysight\IO Libraries Suite\bin",
    r"C:\Program Files\Keysight\IO Libraries Suite\lib_x64",
    r"C:\Program Files\IVI Foundation\VISA\Win64\Bin",
    r"C:\Program Files\IVI Foundation\VISA\Win64\ktvisa\ktbin",
)

_dll_dirs_registered = False


def _register_visa_dependency_dirs() -> None:
    """Add Keysight/IVI native DLL directories to the DLL search path.

    Required on Python 3.8+ where DLL dependencies are not resolved via PATH.
    Safe to call multiple times; only runs once.
    """
    global _dll_dirs_registered
    if _dll_dirs_registered:
        return
    _dll_dirs_registered = True

    add_dll_directory = getattr(os, "add_dll_directory", None)
    for directory in _VISA_DEPENDENCY_DIRS:
        if not Path(directory).is_dir():
            continue
        # Ensure PATH coverage for older loaders.
        os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
        if add_dll_directory is not None:
            try:
                add_dll_directory(directory)
            except (FileNotFoundError, OSError):
                pass


def open_visa_resource_manager():
    """Return a pyvisa ResourceManager, trying auto-discovery then known paths.

    Raises RuntimeError with actionable guidance if no backend can be loaded.
    """
    if pyvisa is None:
        raise RuntimeError("pyvisa is required for GPIB/VISA instruments but is not installed")

    _register_visa_dependency_dirs()

    errors: list[str] = []

    # 1) Honor an explicit override if the user set one.
    override = os.environ.get("PYVISA_LIBRARY")
    attempts: list[str] = []
    if override:
        attempts.append(override)
    # 2) Auto-discovery (empty string -> pyvisa default search).
    attempts.append("")
    # 3) Known native backend DLLs that exist on disk.
    attempts.extend(path for path in _VISA_BACKEND_CANDIDATES if Path(path).is_file())

    for spec in attempts:
        try:
            return pyvisa.ResourceManager(spec) if spec else pyvisa.ResourceManager()
        except Exception as exc:  # pragma: no cover - backend-specific failure path
            errors.append(f"{spec or '<auto>'}: {exc}")

    detail = "; ".join(errors) if errors else "no attempts made"
    raise RuntimeError(
        "No VISA backend could be loaded. Ensure Keysight IO Libraries (or NI-VISA) "
        "is installed and that Keysight Connection Expert is CLOSED (it can lock the "
        "backend). You can also set PYVISA_LIBRARY to an explicit visa DLL path. "
        f"Tried: {detail}"
    )


@dataclass
class VisaInstrument:
    config: SerialDeviceConfig

    def __post_init__(self) -> None:
        self._rm = None
        self._resource = None

    def _resource_manager(self):
        if self._rm is None:
            self._rm = open_visa_resource_manager()
        return self._rm

    def open(self) -> None:
        if self._resource is not None:
            return
        rm = self._resource_manager()
        self._resource = rm.open_resource(self.config.resource_name)
        if hasattr(self._resource, "timeout"):
            self._resource.timeout = int(self.config.timeout_s * 1000)

    def close(self) -> None:
        if self._resource is not None:
            self._resource.close()
            self._resource = None

    def send_scpi(self, command: str) -> None:
        if self._resource is None:
            raise InstrumentError(f"{self.config.name} is not open")
        self._resource.write(command)

    def read_scpi(self) -> str:
        if self._resource is None:
            raise InstrumentError(f"{self.config.name} is not open")
        return str(self._resource.read()).strip()

    def query_scpi(self, command: str) -> str:
        if self._resource is None:
            raise InstrumentError(f"{self.config.name} is not open")
        return str(self._resource.query(command)).strip()


@dataclass
class SerialInstrument:
    config: SerialDeviceConfig

    def __post_init__(self) -> None:
        self._ser: serial.Serial | None = None
        self._visa: VisaInstrument | None = None
        if self.config.resource_name:
            self._visa = VisaInstrument(self.config)

    def open(self) -> None:
        if self.config.resource_name:
            if self._visa is None:
                self._visa = VisaInstrument(self.config)
            self._visa.open()
            return

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
        if self.config.resource_name:
            if self._visa is not None:
                self._visa.close()
            return

        if self._ser and self._ser.is_open:
            self._ser.close()

    def send_scpi(self, command: str) -> None:
        if self.config.resource_name:
            if self._visa is None:
                raise InstrumentError(f"{self.config.name} is not open")
            self._visa.send_scpi(command)
            return

        if not self._ser or not self._ser.is_open:
            raise InstrumentError(f"{self.config.name} is not open")

        payload = f"{command}{self.config.write_termination}"
        self._ser.write(payload.encode("ascii", errors="ignore"))

    def read_scpi(self) -> str:
        if self.config.resource_name:
            if self._visa is None:
                raise InstrumentError(f"{self.config.name} is not open")
            return self._visa.read_scpi()

        if not self._ser:
            raise InstrumentError(f"{self.config.name} is not open")

        response = self._ser.read_until(self.config.read_termination.encode("ascii", errors="ignore"))
        return response.decode("ascii", errors="ignore").strip()

    def query_scpi(self, command: str) -> str:
        if self.config.resource_name:
            if self._visa is None:
                raise InstrumentError(f"{self.config.name} is not open")
            return self._visa.query_scpi(command)

        self.send_scpi(command)
        return self.read_scpi()

    def __enter__(self) -> "SerialInstrument":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
