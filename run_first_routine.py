from __future__ import annotations

import argparse
import math
import re
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import serial
import yaml

# Allow running this script directly from repository root without pip install -e .
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from iv_measure.config import load_project_config
from iv_measure.e3631a import E3631A
from iv_measure.routines import load_routines_csv, RoutineMeasurement, run_single_routine_from_csv, write_routine_measurements_csv


class LiveRoutinePlot:
     """
    Manages a live-updating matplotlib figure with two subplots
    (linear-scale and log-scale Ids vs Vds) that get redrawn as new
    measurement points arrive during a routine. Object with functions to add lines and x/y data
    """
    def __init__(self, routine_name: str, step_param: str, sweep_param: str) -> None:
        # Turn on interactive mode so the plot updates without blocking execution.
        plt.ion()
        self._figure, (self._vds_linear_ax, self._vds_log_ax) = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)

        # setup to store one Line2D object per step value (e.g. one line per vds step),
        # plus the raw x/y data backing each line so we can append to it.
        self._vds_linear_lines: dict[float, Line2D] = {}
        self._vds_log_lines: dict[float, Line2D] = {}
        self._vds_x_data: dict[float, list[float]] = {}
        self._vds_y_data: dict[float, list[float]] = {}

        self._step_param = step_param
        self._sweep_param = sweep_param

        # Configure the linear-scale subplot.
        self._vds_linear_ax.set_title(f"{routine_name} Ids vs Vds (Linear)")
        self._vds_linear_ax.set_xlabel(f"{sweep_param} (V)")
        self._vds_linear_ax.set_ylabel("Drain current (A)")
        self._vds_linear_ax.grid(True, alpha=0.3)

        # Configure the log-scale subplot (useful for viewing subthreshold current).
        self._vds_log_ax.set_title(f"{routine_name} Ids vs Vds (Log)")
        self._vds_log_ax.set_xlabel(f"{sweep_param} (V)")
        self._vds_log_ax.set_ylabel("Drain current (A)")
        self._vds_log_ax.set_yscale("log")
        self._vds_log_ax.grid(True, which="both", alpha=0.3)

    def update(self, point: RoutineMeasurement) -> None:
        """
        Called once per new measurement point. Adds the point to the
        appropriate step-value line (creating the line if needed) and
        redraws the figure.
        """
        step_value = point.step_value_v
        vds_linear_line = self._vds_linear_lines.get(step_value)
        vds_log_line = self._vds_log_lines.get(step_value)

        # First time we see this step value, create a new line/legend entry for it.
        if vds_linear_line is None or vds_log_line is None:
            (vds_linear_line,) = self._vds_linear_ax.plot([], [], marker="o", linewidth=1.5, markersize=4, label=f"{self._step_param}={step_value:.3f} V")
            (vds_log_line,) = self._vds_log_ax.plot([], [], marker="o", linewidth=1.5, markersize=4, label=f"{self._step_param}={step_value:.3f} V")
            self._vds_linear_lines[step_value] = vds_linear_line
            self._vds_log_lines[step_value] = vds_log_line
            self._vds_x_data[step_value] = []
            self._vds_y_data[step_value] = []
            self._vds_linear_ax.legend(loc="best")
            self._vds_log_ax.legend(loc="best")

        
        # Append the new data point to this step's series.
        self._vds_x_data[step_value].append(point.sweep_value_v)
        self._vds_y_data[step_value].append(point.drain_i_a)
        vds_linear_line.set_data(self._vds_x_data[step_value], self._vds_y_data[step_value])

        # Log scale can't plot non-positive values, so replace them with NaN
        # (matplotlib simply skips NaN points, keeping the line continuous elsewhere).
        vds_log_y_data = [value if value > 0 else math.nan for value in self._vds_y_data[step_value]]
        vds_log_line.set_data(self._vds_x_data[step_value], vds_log_y_data)

        # Rescale axes to fit new data, then force a redraw/flush so the
        # window actually updates on screen during the blocking measurement loop.
        self._vds_linear_ax.relim()
        self._vds_linear_ax.autoscale_view()
        self._vds_log_ax.relim()
        self._vds_log_ax.autoscale_view()
        self._ensure_log_limits()
        self._figure.canvas.draw_idle()
        self._figure.canvas.flush_events()
        plt.pause(0.001)

    
    def _ensure_log_limits(self) -> None:
        """
        Manually set y-limits for the log plot based on the min/max positive
        values seen so far, since autoscale_view doesn't always behave well
        with log axes when data spans many decades.
        """
        vds_positive_values = [
            value
            for values in self._vds_y_data.values()
            for value in values
            if value > 0
        ]
        if not vds_positive_values:
            self._vds_log_ax.set_ylim(1e-12, 1.0)
        else:
            vds_min_positive = min(vds_positive_values)
            vds_max_positive = max(vds_positive_values)
            vds_lower = max(vds_min_positive / 10.0, 1e-18)
            vds_upper = vds_max_positive * 10.0 if vds_max_positive > vds_min_positive else vds_min_positive * 10.0
            self._vds_log_ax.set_ylim(vds_lower, vds_upper)

    def finalize(self) -> None:
        """Switch off interactive mode and block on the figure so the user can inspect it after the routine finishes."""
        if plt.fignum_exists(self._figure.number):
            plt.ioff()
            plt.show(block=True)


def reset_serial_ports(ports: list[str]) -> None:
    """
    Attempt to close any open connections on the given ports to reset them.

    Opening and immediately closing each port (with buffers flushed) helps
    clear stale connections left over from a previous run/crash, particularly
    on Windows where serial handles can linger.
    """
    for port in ports:
        try:
            ser = serial.Serial(port, timeout=0.1)
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            ser.close()
            print(f"Reset {port}")
        except Exception as e:
            print(f"Reset failed for {port}: {e}")
    time.sleep(2.0)  # Longer pause for Windows to fully release resources


def _parse_voltage_literal(text: str) -> float | None:
    """
    Parse a string like "1.8", "1.8V", or "-0.5 v" into a float voltage.
    Returns None if the text doesn't match a plain numeric voltage literal
    (e.g. it's a symbolic name like "Vg" instead).
    """
    match = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*[vV]?\s*", text)
    if not match:
        return None
    return float(match.group(1))


def _is_manual_supply_rail(voltage_v: float) -> bool:
     """
    Identify voltages that correspond to rails intended to be set manually
    (e.g. 0.9 V / 1.8 V logic rails) rather than driven automatically by
    this script.
    """
    return abs(voltage_v - 0.9) <= 1e-6 or abs(voltage_v - 1.8) <= 1e-6


def _enable_aux_fixed_e3631a(config_path: str | Path, in_use_ports: set[str]) -> list[E3631A]:
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
        if not port or port in in_use_ports:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run routines from a measurement-routines CSV. "
            "By default runs all routines; use --routine-index to run one."
        )
    )
    parser.add_argument(
        "--config",
        default="instrument_list.yaml",
        help="Path to YAML instrument config.",
    )
    parser.add_argument(
        "--routines-csv",
        default="Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv",
        help="Path to routines CSV file.",
    )
    parser.add_argument(
        "--output-csv",
        default="data/first_routine_measurements.csv",
        help="Path to output CSV.",
    )
    parser.add_argument(
        "--routine-index",
        type=int,
        default=None,
        help="0-based routine index from the CSV to run. If omitted, all routines are run.",
    )
    parser.add_argument(
        "--no-live-plot",
        action="store_true",
        help="Disable the live matplotlib plot during acquisition.",
    )
    parser.add_argument(
        "--no-confirm-initial",
        action="store_true",
        help="Do not pause for user confirmation after initial voltages are applied.",
    )
    parser.add_argument(
        "--ids-settle-s",
        type=float,
        default=1.0,
        help="Settling time in seconds before each Ids measurement (default: 1.0).",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    config = load_project_config(args.config)
    routine_specs = load_routines_csv(args.routines_csv)
    if args.routine_index is None:
        routine_indices = list(range(len(routine_specs)))
    else:
        if args.routine_index < 0 or args.routine_index >= len(routine_specs):
            raise ValueError(f"routine_index {args.routine_index} out of range [0, {len(routine_specs) - 1}]")
        routine_indices = [args.routine_index]
    
    # Reset/close any lingering connections on the ports
    ports_to_reset = [config.gate_source.port, config.drain_source.port]
    if config.bulk_source:
        ports_to_reset.append(config.bulk_source.port)
    for _, src_cfg in config.quantity_sources.items():
        if src_cfg.port not in ports_to_reset:
            ports_to_reset.append(src_cfg.port)
    reset_serial_ports(ports_to_reset)
    time.sleep(0.5)  # Brief pause after reset

    aux_supplies = _enable_aux_fixed_e3631a(args.config, set(ports_to_reset))
    
    all_points: list[RoutineMeasurement] = []
    completed: list[tuple[int, str, int]] = []

    try:
        for order, routine_index in enumerate(routine_indices):
            selected_routine = routine_specs[routine_index]
            live_plot = None if args.no_live_plot else LiveRoutinePlot(
                routine_name=selected_routine.name,
                step_param=selected_routine.step_param,
                sweep_param=selected_routine.sweep_param,
            )
            try:
                routine, points = run_single_routine_from_csv(
                    config=config,
                    routines_csv=args.routines_csv,
                    routine_index=routine_index,
                    point_callback=None if live_plot is None else live_plot.update,
                    confirm_initial_bias=(not args.no_confirm_initial and order == 0),
                    ids_settle_s=args.ids_settle_s,
                )
            finally:
                if live_plot is not None:
                    live_plot.finalize()

            all_points.extend(points)
            completed.append((routine_index, routine.name, len(points)))

        write_routine_measurements_csv(args.output_csv, all_points)
    finally:
        for supply in aux_supplies:
            try:
                supply.output_off()
            finally:
                supply.close()

    print(f"Routines run: {len(completed)}")
    for routine_index, routine_name, point_count in completed:
        print(f"  - index {routine_index}: {routine_name} ({point_count} points)")
    print(f"Points total: {len(all_points)}")
    print(f"Saved: {args.output_csv}")


if __name__ == "__main__":
    main()
