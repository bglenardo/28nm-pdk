"""Minimal BK 9132C smoke test: set CH1/CH3, hold 10 s, then turn outputs off."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from iv_measure.bk9132c import BK9132C


PORT = "COM6"
CH1_VOLT = 0.95
CH3_VOLT = 0.05
CURRENT_LIMIT = 0.1
HOLD_SEC = 10


def _enable_channel_output(bk: BK9132C, channel: str) -> None:
    bk.send_scpi(f"INST {channel}")
    bk.send_scpi("CHAN:OUTP 1")


def _disable_channel_output(bk: BK9132C, channel: str) -> None:
    bk.send_scpi(f"INST {channel}")
    bk.send_scpi("CHAN:OUTP 0")


def _readback(bk: BK9132C, channel: str) -> tuple[str, str]:
    bk.send_scpi(f"INST {channel}")
    time.sleep(0.05)
    return bk.query_scpi("MEAS:VOLT?").strip(), bk.query_scpi("MEAS:CURR?").strip()


with BK9132C(port=PORT) as bk:
    print(f"IDN: {bk.identify()!r}")

    # Set target voltages and current limits.
    bk.send_scpi(f"APPL CH1, {CH1_VOLT:.6f}, {CURRENT_LIMIT:.6f}")
    bk.send_scpi(f"APPL CH3, {CH3_VOLT:.6f}, {CURRENT_LIMIT:.6f}")

    # Enable global output and per-channel output.
    bk.send_scpi("OUTP:STAT 1")
    _enable_channel_output(bk, "CH1")
    _enable_channel_output(bk, "CH3")

    v1, i1 = _readback(bk, "CH1")
    v3, i3 = _readback(bk, "CH3")
    print(f"CH1 readback V={v1!r} I={i1!r}")
    print(f"CH3 readback V={v3!r} I={i3!r}")

    print(f"Holding setpoints for {HOLD_SEC} seconds...")
    for t in range(1, HOLD_SEC + 1):
        time.sleep(1)
        if t % 2 == 0:
            v, i = _readback(bk, "CH1")
            print(f"t={t:2d}s CH1 V={v!r} I={i!r}")

    # Clean shutdown.
    _disable_channel_output(bk, "CH1")
    _disable_channel_output(bk, "CH3")
    bk.send_scpi("OUTP:STAT 0")

    print("Done.")
