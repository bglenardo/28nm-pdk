from __future__ import annotations

import argparse
import re
import time
from contextlib import ExitStack
from pathlib import Path

import yaml

# Allow running from repo root without editable install.
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from iv_measure.e3631a import E3631A

_VALID_CHANNELS = {"P6V", "P25V", "N25V"}
_VALID_QUANTITIES = {"Vb", "Vg", "Vd", "Vs"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create two E3631A objects from YAML, apply any fixed channel voltages, "
            "then sweep Vb and Vg from 0 to 1 V in 5 steps."
        )
    )
    parser.add_argument("--config", default="instrument_list.yaml", help="Path to YAML config.")
    parser.add_argument("--settle-s", type=float, default=None, help="Override settle time in seconds.")
    return parser


def linear_points(start: float, stop: float, count: int) -> list[float]:
    if count < 1:
        raise ValueError("count must be >= 1")
    if count == 1:
        return [float(start)]

    step = (stop - start) / (count - 1)
    return [round(start + i * step, 12) for i in range(count)]


def parse_voltage_literal(text: str) -> float:
    match = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*[vV]?\s*", text)
    if not match:
        raise ValueError(f"Invalid voltage literal: {text!r}")
    return float(match.group(1))


def load_dual_e3631a_config(path: str | Path) -> tuple[list[tuple[str, dict]], float]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Config root must be a mapping")

    instruments = raw.get("instruments")
    if not isinstance(instruments, dict):
        raise ValueError("Config must contain an instruments mapping")

    e3631a_entries: list[tuple[str, dict]] = []
    for name, value in instruments.items():
        if not isinstance(value, dict):
            continue
        instrument_type = str(value.get("type", "")).strip().upper()
        if instrument_type == "E3631A":
            e3631a_entries.append((str(name), value))

    if len(e3631a_entries) < 2:
        raise ValueError("Need at least two instruments of type E3631A in config")

    settle_s = 0.5
    sweep = raw.get("sweep")
    if isinstance(sweep, dict):
        settle_s = float(sweep.get("settle_s", settle_s))

    return e3631a_entries[:2], settle_s


def main() -> None:
    args = build_parser().parse_args()
    entries, default_settle_s = load_dual_e3631a_config(args.config)
    settle_s = default_settle_s if args.settle_s is None else float(args.settle_s)

    vb_binding: tuple[str, str] | None = None
    vg_binding: tuple[str, str] | None = None
    fixed_actions: list[tuple[str, str, float, float]] = []

    for name, cfg in entries:
        channel_map = cfg.get("channel_map")
        if not isinstance(channel_map, dict):
            raise ValueError(f"instruments.{name}.channel_map must be a mapping")

        current_limit_a = float(cfg.get("current_limit_a", 0.1))
        for channel, mapped in channel_map.items():
            channel_text = str(channel).strip()
            if channel_text not in _VALID_CHANNELS:
                raise ValueError(f"instruments.{name}.channel_map has invalid channel {channel_text!r}")

            mapped_text = str(mapped).strip()
            lowered = mapped_text.lower()
            if lowered in {"none", "null", ""}:
                continue

            if mapped_text in _VALID_QUANTITIES:
                if mapped_text == "Vb" and vb_binding is None:
                    vb_binding = (name, channel_text)
                elif mapped_text == "Vg" and vg_binding is None:
                    vg_binding = (name, channel_text)
                continue

            fixed_v = parse_voltage_literal(mapped_text)
            fixed_actions.append((name, channel_text, fixed_v, current_limit_a))

    if vb_binding is None or vg_binding is None:
        raise ValueError("Could not find both Vb and Vg mappings in the first two E3631A channel_map entries")

    device_by_name: dict[str, E3631A] = {}

    with ExitStack() as stack:
        for name, cfg in entries:
            device = E3631A(
                port=str(cfg["port"]),
                baudrate=int(cfg.get("baudrate", 9600)),
                timeout_s=float(cfg.get("timeout_s", 1.0)),
            )
            stack.enter_context(device)
            device.output_on()
            device_by_name[name] = device
            print(f"Opened {name} on {cfg['port']}")

        try:
            for name, channel, voltage_v, current_limit_a in fixed_actions:
                device_by_name[name].apply(channel, voltage_v, current_limit_a)
                print(f"Set fixed: {name} {channel} -> {voltage_v:.3f} V @ {current_limit_a:.3f} A")

            vb_values = linear_points(0.0, 1.0, 5)
            vg_values = linear_points(0.0, 1.0, 5)

            vb_name, vb_channel = vb_binding
            vg_name, vg_channel = vg_binding

            vb_limit = float(dict(entries)[vb_name].get("current_limit_a", 0.1))
            vg_limit = float(dict(entries)[vg_name].get("current_limit_a", 0.1))

            for vb_v in vb_values:
                device_by_name[vb_name].apply(vb_channel, vb_v, vb_limit)
                time.sleep(settle_s)

                for vg_v in vg_values:
                    device_by_name[vg_name].apply(vg_channel, vg_v, vg_limit)
                    time.sleep(settle_s)
                    print(f"Sweep point: Vb={vb_v:.3f} V, Vg={vg_v:.3f} V")
        finally:
            # Safe shutdown for swept channels.
            device_by_name[vb_name].apply(vb_channel, 0.0, vb_limit)
            device_by_name[vg_name].apply(vg_channel, 0.0, vg_limit)
            for name, _cfg in entries:
                device_by_name[name].output_off()

    print("Completed E3631A dual test sweep.")


if __name__ == "__main__":
    main()
