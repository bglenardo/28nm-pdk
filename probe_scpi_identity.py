from __future__ import annotations

import argparse
import threading
import time
from dataclasses import dataclass

import serial
import serial.tools.list_ports as list_ports


# Known SCPI instrument vendor tokens. A reply that contains one of these (or a
# comma, as in the IDN "vendor,model,serial,fw" format) is treated as a genuine
# clean response rather than line-noise garble from the wrong framing.
VENDOR_TOKENS = (
    "HEWLETT",
    "PACKARD",
    "AGILENT",
    "KEYSIGHT",
    "KEITHLEY",
    "RIGOL",
    "TEKTRONIX",
    "B&K",
    "BK PRECISION",
    "34401",
    "2400",
    "2401",
    "9132",
    "DP8",
    "E3631",
)


@dataclass(frozen=True)
class LineSetting:
    """One RS-232 framing candidate: data bits / parity / stop bits."""

    bytesize: int
    parity: str
    stopbits: float

    @property
    def label(self) -> str:
        return f"{self.bytesize}{self.parity}{int(self.stopbits)}"


@dataclass(frozen=True)
class ProbeConfig:
    """A full framing + terminator candidate to try on a port."""

    baudrate: int
    line: LineSetting
    write_terminator: str
    read_terminator: str

    @property
    def term_label(self) -> str:
        names = {"\r": "CR", "\n": "LF", "\r\n": "CRLF"}
        return names.get(self.write_terminator, repr(self.write_terminator))

    @property
    def label(self) -> str:
        return f"{self.baudrate} {self.line.label} {self.term_label}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Probe serial ports with SCPI *IDN?, sweeping baud / data-bit / "
            "parity / stop-bit / terminator combinations until a CLEAN reply is "
            "found. Prints the exact settings (and a ready-to-paste YAML block) "
            "so you can update instrument_list.yaml."
        ),
    )
    parser.add_argument(
        "--ports",
        nargs="+",
        default=["AUTO"],
        help="Serial ports to probe. Use 'AUTO' to detect available ports automatically.",
    )
    parser.add_argument(
        "--baudrates",
        nargs="+",
        type=int,
        default=[9600, 19200, 4800, 38400],
        help="Baud rates to sweep (in order).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.5,
        help="Per-query read timeout in seconds.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Report EVERY clean combination per port instead of stopping at the first.",
    )
    return parser


def _discover_ports() -> list[str]:
    ports = [info.device for info in list_ports.comports()]
    return sorted(set(ports))


def resolve_ports(raw_ports: list[str] | None) -> list[str]:
    if not raw_ports or raw_ports == ["AUTO"]:
        return _discover_ports()
    ports = []
    for entry in raw_ports:
        if entry.upper() == "AUTO":
            ports.extend(_discover_ports())
        else:
            ports.append(entry)
    return sorted(set(ports))


def build_line_settings() -> list[LineSetting]:
    """All data-bit / parity / stop-bit combinations worth trying.

    8N1 is first because it is the most common; 7E2 is included because some
    older HP/Agilent meters (e.g. the HP 34401A on this bench) default to 7 data
    bits + even parity + 2 stop bits, and anything else returns garbled bytes.
    """
    settings: list[LineSetting] = []
    # 8-bit framings (no parity bit -> 1 or 2 stop bits).
    for stop in (1.0, 2.0):
        settings.append(LineSetting(8, "N", stop))
    # 8-bit with parity.
    for parity in ("E", "O"):
        for stop in (1.0, 2.0):
            settings.append(LineSetting(8, parity, stop))
    # 7-bit framings always need a parity bit; sweep parity and stop bits.
    for parity in ("E", "O"):
        for stop in (1.0, 2.0):
            settings.append(LineSetting(7, parity, stop))
    return settings


def build_configs(baudrates: list[int]) -> list[ProbeConfig]:
    """Full sweep: baud x framing x terminator."""
    terminators = (
        ("\n", "\n"),    # LF  (most SCPI-over-serial instruments)
        ("\r\n", "\n"),  # CRLF
        ("\r", "\r"),    # CR  (legacy Keithley)
    )
    configs: list[ProbeConfig] = []
    for baud in baudrates:
        for line in build_line_settings():
            for write_term, read_term in terminators:
                configs.append(
                    ProbeConfig(
                        baudrate=baud,
                        line=line,
                        write_terminator=write_term,
                        read_terminator=read_term,
                    )
                )
    return configs


def _is_clean_ascii(text: str) -> bool:
    """Return True if ``text`` decoded as clean, printable ASCII.

    Garbled framing (wrong data bits / parity / stop bits) produces bytes that
    decode to replacement characters or control codes. A clean-ASCII reply means
    the LINE SETTINGS are correct, even if the device does not speak SCPI *IDN?.
    A non-empty response is NOT enough -- the original bug accepted corrupted
    bytes as a match.
    """
    if not text:
        return False
    # Replacement char => undecodable bytes => wrong framing.
    if "\ufffd" in text:
        return False
    # Reject if there are non-printable control characters (besides whitespace).
    control = sum(1 for ch in text if ord(ch) < 32 and ch not in "\r\n\t")
    if control:
        return False
    printable = sum(1 for ch in text if 32 <= ord(ch) < 127)
    return printable / max(len(text), 1) >= 0.9


def _looks_like_idn(text: str) -> bool:
    """Return True if a clean reply looks like a genuine SCPI *IDN? identity.

    SCPI identities are "vendor,model,serial,fw" (comma-separated) or contain a
    known vendor token. A clean reply that matches neither (e.g. the Arduino's
    "ERR unknown cmd: *IDN?") still proves the framing is right, but is not an
    instrument identity.
    """
    if not _is_clean_ascii(text):
        return False
    if "," in text:
        return True
    upper = text.upper()
    return any(token in upper for token in VENDOR_TOKENS)



def _query_scpi(connection: serial.Serial, command: str, terminator: str, timeout_s: float = 0.5) -> str:
    """Send a SCPI query and read the response. Return '' on timeout/no data."""
    try:
        window = min(max(timeout_s, 0.1), 0.6)
        connection.timeout = window
        connection.reset_input_buffer()
        connection.write(f"{command}{terminator}".encode("ascii", errors="ignore"))
        connection.flush()
        time.sleep(0.05)
        deadline = time.monotonic() + window
        chunks: list[bytes] = []
        while time.monotonic() < deadline:
            if connection.in_waiting > 0:
                chunk = connection.read(connection.in_waiting)
                if not chunk:
                    break
                chunks.append(chunk)
                if terminator.encode("ascii", errors="ignore") in b"".join(chunks):
                    break
            time.sleep(0.02)
        raw = b"".join(chunks)
        if not raw:
            return ""
        # Decode with 'replace' so corrupted framing shows up as U+FFFD and is
        # rejected by _is_clean_ascii (decoding with 'ignore' would hide it).
        return raw.decode("ascii", errors="replace").strip()
    except (serial.SerialException, OSError, ValueError):
        return ""


def _clear_status(connection: serial.Serial) -> None:
    """Send *CLS to clear stale error and status conditions before/after probing."""
    try:
        connection.reset_input_buffer()
        connection.write(b"*CLS\r\n")
        connection.flush()
        time.sleep(0.05)
    except (serial.SerialException, OSError, ValueError):
        pass


def probe_port(
    port: str,
    timeout: float,
    config: ProbeConfig,
) -> tuple[str, str]:
    """Probe one port/framing. Returns (status, message).

    status is one of:
      "idn"      -> clean reply that looks like a SCPI *IDN? identity (best).
      "responds" -> clean ASCII reply, framing is correct, but not a SCPI IDN
                    (e.g. the Arduino's "ERR unknown cmd: *IDN?").
      "garbled"  -> bytes came back but decode dirty => wrong framing.
      "none"     -> no response at all.
      "error"    -> the port could not be opened / OS error.
    """
    try:
        with serial.Serial(
            port=port,
            baudrate=config.baudrate,
            bytesize=_serial_bytesize(config.line.bytesize),
            parity=_serial_parity(config.line.parity),
            stopbits=_serial_stopbits(config.line.stopbits),
            timeout=min(max(timeout, 0.1), 0.6),
        ) as connection:
            # Opening the port asserts DTR; instruments with DTR/DSR handshaking
            # (e.g. the HP 34401A) need a brief settle before they will answer,
            # and any power-up/stale bytes must be flushed. Without this, rapid
            # back-to-back probes race the meter and it looks unresponsive.
            #
            # IMPORTANT: do NOT send *CLS (or any command) before *IDN?. The
            # Agilent E3631A asserts a DTR hold-off after processing *CLS and
            # drops the immediately-following *IDN? bytes, so it never replies.
            # Flushing the buffers is enough to clear stale bytes; *IDN? does not
            # need a prior *CLS. (Empirically verified: *CLS-first => no reply.)
            time.sleep(0.2)
            connection.reset_input_buffer()
            connection.reset_output_buffer()
            idn_text = _query_scpi(connection, "*IDN?", config.write_terminator, timeout_s=max(timeout, 0.5))

            if not idn_text:
                return "none", "no response"
            if not _is_clean_ascii(idn_text):
                return "garbled", f"garbled: {idn_text!r}"

            if _looks_like_idn(idn_text):
                error_text = _query_scpi(connection, "SYST:ERR?", config.write_terminator, timeout_s=max(timeout, 0.5))
                result = idn_text
                if error_text and _is_clean_ascii(error_text):
                    result += f" | Error: {error_text}"
                _clear_status(connection)
                return "idn", result

            # Clean, readable reply but not a SCPI identity: framing is correct,
            # device just doesn't answer *IDN? (e.g. the Arduino scan selector).
            return "responds", f"clean reply, not a SCPI *IDN?: {idn_text!r}"
    except serial.SerialException as exc:
        return "error", f"serial error: {exc}"
    except OSError as exc:
        return "error", f"os error: {exc}"
    except Exception as exc:  # noqa: BLE001 - report anything unexpected to the user
        return "error", f"unexpected error: {exc}"


def _probe_port_with_timeout(port: str, timeout: float, config: ProbeConfig, per_port_timeout_s: float = 3.0) -> tuple[str, str]:
    """Run ``probe_port`` in a daemon thread with a hard wall-clock cap.

    The serial read timeouts already bound each query, but opening a busy or
    missing port can block, so we guard with a watchdog thread. A thread is used
    (not a process) because on Windows the ``spawn`` start method re-imports this
    module for every probe, which is ruinously slow across hundreds of
    combinations. If the thread overruns, it is abandoned (daemon) and we move on.
    """
    result: list[tuple[str, str]] = []

    def _worker() -> None:
        result.append(probe_port(port=port, timeout=timeout, config=config))

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=per_port_timeout_s)
    if thread.is_alive():
        return "timeout", "timed out"
    if not result:
        return "none", "no result"
    return result[0]


def _yaml_snippet(port: str, config: ProbeConfig) -> str:
    write_term = config.write_terminator.replace("\r", "\\r").replace("\n", "\\n")
    read_term = config.read_terminator.replace("\r", "\\r").replace("\n", "\\n")
    return (
        "    # Verified clean by probe_scpi_identity.py\n"
        f"    port: {port}\n"
        f"    baudrate: {config.baudrate}\n"
        f"    bytesize: {config.line.bytesize}\n"
        f'    parity: "{config.line.parity}"\n'
        f"    stopbits: {int(config.line.stopbits)}\n"
        f'    write_termination: "{write_term}"\n'
        f'    read_termination: "{read_term}"'
    )


def main() -> None:
    args = build_parser().parse_args()

    configs = build_configs(args.baudrates)
    ports = resolve_ports(args.ports)
    if not ports:
        print("No serial ports found.")
        return

    print(
        f"Probing {len(ports)} port(s) with up to {len(configs)} framing "
        f"combinations each (baud x data-bits x parity x stop-bits x terminator)."
    )
    print(
        "A match requires a CLEAN, printable reply -- garbled bytes are rejected. "
        "A device that answers cleanly but not to *IDN? (e.g. the Arduino) is "
        "still reported, since its framing is confirmed.\n"
    )

    for port in ports:
        # Prefer a true SCPI IDN; fall back to a clean non-IDN responder.
        idn_match: tuple[ProbeConfig, str] | None = None
        responder: tuple[ProbeConfig, str] | None = None
        last_failure = "no response"
        print(f"{port}: scanning {len(configs)} combinations...", flush=True)

        for index, config in enumerate(configs, start=1):
            status, message = _probe_port_with_timeout(port=port, timeout=args.timeout, config=config)
            if status == "idn":
                idn_match = (config, message)
                print(f"{port}: CLEAN *IDN? at {config.label} -> {message}", flush=True)
                if not args.all:
                    break
            elif status == "responds":
                if responder is None:
                    responder = (config, message)
                    print(f"{port}: RESPONDS at {config.label} -> {message}", flush=True)
                # Keep scanning: a true SCPI *IDN? framing is preferred if one
                # exists, but this confirmed-framing responder is a useful result.
            else:
                last_failure = f"{config.label} - {message}"
                # Lightweight progress so a long sweep does not look hung.
                if index % 10 == 0:
                    print(f"{port}:   ...{index}/{len(configs)} tried (last: {last_failure})", flush=True)

        chosen = idn_match or responder
        if chosen is not None:
            config, _ = chosen
            kind = "SCPI *IDN?" if idn_match is not None else "clean responder (no *IDN?)"
            print(f"\n{port}: {kind} -- use these settings in instrument_list.yaml:")
            print(_yaml_snippet(port, config))
            print()
        else:
            print(f"{port}: FAIL - no clean reply found (last: {last_failure})\n")


def _serial_bytesize(value: int) -> int:
    if value == 7:
        return serial.SEVENBITS
    if value == 8:
        return serial.EIGHTBITS
    raise ValueError(f"Unsupported byte size: {value}")


def _serial_parity(value: str) -> str:
    normalized = str(value).upper()
    if normalized in {"N", "NONE"}:
        return serial.PARITY_NONE
    if normalized in {"E", "EVEN"}:
        return serial.PARITY_EVEN
    if normalized in {"O", "ODD"}:
        return serial.PARITY_ODD
    raise ValueError(f"Unsupported parity setting: {value}")


def _serial_stopbits(value: float) -> float:
    if value == 1.0:
        return serial.STOPBITS_ONE
    if value == 1.5:
        return serial.STOPBITS_ONE_POINT_FIVE
    if value == 2.0:
        return serial.STOPBITS_TWO
    raise ValueError(f"Unsupported stop bits value: {value}")


if __name__ == "__main__":
    main()