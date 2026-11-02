"""Shared bench helpers for the routine-runner scripts.

This module holds the plumbing that both ``run_routine_test.py`` (interactive,
single device) and ``run_routine_automated_scan.py`` (fast, multi-device) rely
on: serial-port resets, the Arduino scan-chain selector, auxiliary E3631A rail
enabling, and small CLI index parsing. Keeping it here avoids duplicating the
hardware glue across the two entry-point scripts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import time
from pathlib import Path

import serial
import yaml

from iv_measure.e3631a import E3631A


def _is_serial_port_name(value: str | None) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    upper = text.upper()
    if "::" in text or upper.startswith(("GPIB", "USB", "ASRL", "TCPIP")):
        return False
    return True


def _serial_port_names(values: list[str | None]) -> list[str]:
    return [str(value).strip() for value in values if _is_serial_port_name(value)]


def reset_serial_ports(ports: list[str]) -> None:
    """Attempt to close any open connections on the given ports to reset them."""
    for port in _serial_port_names(ports):
        try:
            ser = serial.Serial(port, timeout=0.1)
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            ser.close()
            print(f"Reset {port}")
        except Exception as e:
            print(f"Reset failed for {port}: {e}")
    time.sleep(2.0)  # Longer pause for Windows to fully release resources


@dataclass
class ArduinoDeviceSelector:
    port: str
    baudrate: int = 115200
    model: str = "Arduino"
    device_select_cmd: str = "SEL,{flavor_idx},{row_idx},{col_idx},{chip_idx}\n"
    ack_timeout_s: float = 2.0
    _serial: serial.Serial | None = field(default=None, init=False, repr=False)

    def open(self) -> None:
        self._serial = serial.Serial(self.port, self.baudrate, timeout=self.ack_timeout_s)
        # The Nano R4 resets when the port opens and prints a boot banner ending
        # in "READY"; wait briefly and drain it so it is not mistaken for an ack.
        time.sleep(2.0)
        if self._serial.in_waiting > 0:
            self._serial.read(self._serial.in_waiting)

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None

    def select_device(self, flavor_idx: int, row_idx: int, col_idx: int, chip_idx: int = 1) -> str:
        if self._serial is None:
            self.open()

        self._serial.reset_input_buffer()
        command = self.device_select_cmd.format(
            flavor_idx=flavor_idx,
            row_idx=row_idx,
            col_idx=col_idx,
            chip_idx=chip_idx,
        )
        self._serial.write(command.encode("ascii"))
        self._serial.flush()

        deadline = time.time() + self.ack_timeout_s
        buffer = b""
        while time.time() < deadline:
            if self._serial.in_waiting > 0:
                buffer += self._serial.read(self._serial.in_waiting)
                # The unified sketch ends a SEL with "SEL_DONE" (or "SEL_FAIL").
                if b"SEL_DONE" in buffer or b"SEL_FAIL" in buffer or b"ERR" in buffer:
                    break
            else:
                time.sleep(0.01)

        ack = buffer.decode(errors="ignore").strip()
        if "SEL_DONE" not in ack:
            raise RuntimeError(f"Arduino did not confirm device selection (expected SEL_DONE), got: {ack!r}")
        return ack

    def verify_device(self, flavor_idx: int, row_idx: int, col_idx: int) -> dict[str, str]:
        """Clock the full scan chain and read SOUT back to confirm the selection.

        Sends ``VERIFY,<flavor>,<row>,<col>`` and parses the report line that the
        unified sketch returns before ``VERIFY_DONE``. Returns the parsed
        key=value fields (e.g. ``passed``, ``best_mismatch``, ``tap``). Raises if
        the board never replies.
        """
        if self._serial is None:
            self.open()

        self._serial.reset_input_buffer()
        command = f"VERIFY,{flavor_idx},{row_idx},{col_idx}\n"
        self._serial.write(command.encode("ascii"))
        self._serial.flush()

        # The full 1032-clock readback takes longer than a plain SEL; give it room.
        deadline = time.time() + max(self.ack_timeout_s, 6.0)
        buffer = b""
        while time.time() < deadline:
            if self._serial.in_waiting > 0:
                buffer += self._serial.read(self._serial.in_waiting)
                if b"VERIFY_DONE" in buffer or b"ERR" in buffer:
                    break
            else:
                time.sleep(0.01)

        text = buffer.decode(errors="ignore").strip()
        report_line = ""
        for line in text.splitlines():
            if line.strip().startswith("VERIFY "):
                report_line = line.strip()
                break
        if not report_line:
            raise RuntimeError(f"Arduino did not return a VERIFY report, got: {text!r}")

        fields: dict[str, str] = {}
        for token in report_line.split():
            if "=" in token:
                key, value = token.split("=", 1)
                fields[key] = value
        return fields


def _load_arduino_switcher(config_path: str | Path) -> ArduinoDeviceSelector | None:
    """Read the optional Arduino device-selection instrument from the YAML config."""
    raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None

    instruments = raw.get("instruments")
    if not isinstance(instruments, dict):
        return None

    for name, cfg in instruments.items():
        if not isinstance(cfg, dict):
            continue

        type_name = str(cfg.get("type", "")).strip().upper()
        model_name = str(cfg.get("model", "")).strip().upper()
        if type_name not in {"ARDUINO", "ARDUINO_NANO", "ARDUINO_NANO_R4", "NANO", "NANO_R4"} and model_name not in {"NANO", "NANO_R4", "ARDUINO"}:
            continue

        port = str(cfg.get("port", "")).strip()
        if not port:
            continue

        return ArduinoDeviceSelector(
            port=port,
            baudrate=int(cfg.get("baudrate", 115200)),
            model=str(cfg.get("model", type_name or "Arduino")).strip() or "Arduino",
            device_select_cmd=str(cfg.get("device_select_cmd", "SEL,{flavor_idx},{row_idx},{col_idx},{chip_idx}\n")),
            ack_timeout_s=float(cfg.get("ack_timeout_s", cfg.get("timeout_s", 2.0))),
        )

    return None


def _parse_voltage_literal(text: str) -> float | None:
    match = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*[vV]?\s*", text)
    if not match:
        return None
    return float(match.group(1))


def _is_manual_supply_rail(voltage_v: float) -> bool:
    return abs(voltage_v - 0.9) <= 1e-6 or abs(voltage_v - 1.8) <= 1e-6


def _parse_index_list(text: str | None) -> list[int] | None:
    """Parse a comma/range index spec into a sorted unique list of ints.

    Accepts forms like ``"4"``, ``"1,2,4"``, ``"1-3"`` and ``"1-3,5,7-8"``.
    Returns ``None`` when ``text`` is ``None`` so callers can distinguish
    "not provided" from an empty selection.
    """
    if text is None:
        return None
    values: set[int] = set()
    for chunk in text.split(","):
        token = chunk.strip()
        if not token:
            continue
        if "-" in token.lstrip("+-"):
            # Range form "A-B" (A and B may be any sign; we require A <= B).
            start_text, _, stop_text = token.partition("-")
            start = int(start_text)
            stop = int(stop_text)
            if stop < start:
                raise ValueError(f"Invalid range '{token}': stop is less than start.")
            values.update(range(start, stop + 1))
        else:
            values.add(int(token))
    if not values:
        raise ValueError(f"No indices parsed from '{text}'.")
    return sorted(values)


def enable_aux_fixed_e3631a(config_path: str | Path, in_use_ports: set[str]) -> list[E3631A]:
    """Enable fixed-voltage channels on E3631As not already opened by routine sources."""
    raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []

    instruments = raw.get("instruments")
    if not isinstance(instruments, dict):
        return []

    opened: list[E3631A] = []
    for name, cfg in instruments.items():
        if not isinstance(cfg, dict):
            continue
        if str(cfg.get("type", "")).strip().upper() != "E3631A":
            continue

        port = str(cfg.get("port", "")).strip()
        if not _is_serial_port_name(port) or port in in_use_ports:
            continue

        channel_map = cfg.get("channel_map")
        if not isinstance(channel_map, dict):
            continue

        current_limit_a = float(cfg.get("current_limit_a", 0.1))
        fixed_channels: list[tuple[str, float]] = []
        for channel, mapped in channel_map.items():
            channel_text = str(channel).strip()
            mapped_text = str(mapped).strip()
            if mapped_text.lower() in {"none", "null", "", "vg", "vd", "vb", "vs", "vgxp", "vgxn"}:
                continue
            fixed_v = _parse_voltage_literal(mapped_text)
            if fixed_v is None:
                continue
            if _is_manual_supply_rail(fixed_v):
                print(f"Skipping manual supply rail {name} {channel_text} = {fixed_v:.3f} V")
                continue
            fixed_channels.append((channel_text, fixed_v))

        if not fixed_channels:
            continue

        supply = E3631A(
            port=port,
            baudrate=int(cfg.get("baudrate", 9600)),
            timeout_s=float(cfg.get("timeout_s", 1.0)),
        )
        supply.open()
        supply.output_on()

        for channel, fixed_v in fixed_channels:
            supply.apply(channel, fixed_v, current_limit_a)
            print(f"Set fixed supply {name} {channel} = {fixed_v:.3f} V")

        print(f"Enabled auxiliary E3631A {name} on {port}")
        opened.append(supply)

    return opened


def select_device_on_arduino(
    arduino_switcher: ArduinoDeviceSelector,
    flavor: int,
    row: int,
    col: int,
    chip: int,
    verify_enabled: bool,
) -> None:
    """VERIFY (optional) then SEL a single device on the scan chain.

    VERIFY must run BEFORE the final SEL: a VERIFY clocks the full 1032-bit chain
    (pattern then trailing zeros) and latches at the end, which would latch
    all-zeros and DESELECT the device. Doing the integrity check first and the
    real SEL last leaves the requested device latched for the sweep.
    """
    if verify_enabled:
        report = arduino_switcher.verify_device(flavor, row, col)
        passed = report.get("passed") == "1"
        print(
            f"Scan-chain VERIFY: passed={report.get('passed', '?')} "
            f"mismatch={report.get('best_mismatch', '?')} "
            f"sout_highs={report.get('sout_highs', '?')} "
            f"raw_max={report.get('raw_max', '?')}"
        )
        if not passed:
            raise RuntimeError(
                "Scan-chain VERIFY failed (readback did not match the driven pattern). "
                f"Report: {report}. Check the Arduino selector board/wiring, or pass "
                "--no-verify-device to bypass this check."
            )

    ack = arduino_switcher.select_device(flavor, row, col, chip)
    print(f"Arduino selector {arduino_switcher.model} on {arduino_switcher.port}: ack={ack!r}")
