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
from iv_measure.rigol_dp8xx import RigolDP8xx
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

def _enable_aux_fixed_rigol(config_path: str | Path, in_use_resources: set[str]) -> list[RigolDP8xx]:
    """
    Enable fixed-voltage channels on any Rigol DP800-series supplies defined
    in the config that are NOT already opened as routine sources.

    This mirrors _enable_aux_fixed_e3631a, but differs in two ways to match
    how the Rigol driver works:
      1. Rigol instruments are identified by a VISA "resource_name" string
         (e.g. "USB0::...::INSTR") rather than a serial "port" like COM5.
      2. Rigol channels are named CH1/CH2/CH3 rather than P6V/P25V/N25V,
         so there's no fixed set of "valid" channel names to validate against
         beyond what RigolDP8xx.apply() already checks.

    Returns the list of opened RigolDP8xx instances so the caller can turn
    them off and close them when done.
    """
    # Load the entire instrument config YAML file into a plain dict.
    raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []

    instruments = raw.get("instruments")
    if not isinstance(instruments, dict):
        return []

    opened: list[RigolDP8xx] = []

    for name, cfg in instruments.items():
        if not isinstance(cfg, dict):
            continue

        # Only consider entries explicitly typed as "RigolDP8xx".
        if str(cfg.get("type", "")).strip().upper() != "RIGOLDP8XX":
            continue

        resource_name = str(cfg.get("resource_name", "")).strip()
        # Skip if this resource is already claimed by a routine source, or
        # if no resource_name is given at all.
        if not resource_name or resource_name in in_use_resources:
            continue

        channel_map = cfg.get("channel_map")
        if not isinstance(channel_map, dict):
            continue

        # Current limit applied to every fixed channel on this supply.
        current_limit_a = float(cfg.get("current_limit_a", 0.1))

        # Same idea as the E3631A version: "fixed" channels are ones mapped
        # to a plain numeric voltage rather than a symbolic routine role
        # (Vg/Vd/Vb/Vs/etc.) or "none".
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

        # Nothing to apply on this instrument — skip opening it entirely.
        if not fixed_channels:
            continue

        # Open the Rigol supply and apply each fixed channel's voltage/current.
        supply = RigolDP8xx(
            resource_name=resource_name,
            timeout_ms=int(cfg.get("timeout_ms", 5000)),
        )
        supply.open()

        for channel, fixed_v in fixed_channels:
            # RigolDP8xx.apply() both configures and turns on the channel,
            # unlike E3631A where output_on() is a separate, single
            # whole-instrument call made once up front.
            supply.apply(channel, fixed_v, current_limit_a)
            print(f"Set fixed supply {name} {channel} = {fixed_v:.3f} V")

        print(f"Enabled auxiliary Rigol {name} on {resource_name}")
        opened.append(supply)

    return opened

def _enable_aux_fixed_e3631a(config_path: str | Path, in_use_ports: set[str]) -> list[E3631A]:
     """
    Enable fixed-voltage channels on any E3631A (E3631A is a triple-output DC power supply made by Keysight (formerly Agilent/HP)) supplies defined in the config
    that are NOT already opened as routine sources (gate/drain/bulk/quantity
    sources). This lets auxiliary supply rails (e.g. bias voltages unrelated
    to the swept parameters) get turned on automatically alongside the main
    routine sources.

    Returns the list of opened E3631A instances so the caller can turn them
    off and close them when done.
    """
     # Load the entire instrument config YAML file into a plain dict.
    raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []

    # Pull out the "instruments" section, which should map instrument
    # names to their individual config dicts.
    instruments = raw.get("instruments")
    if not isinstance(instruments, dict):
        return []

    opened: list[E3631A] = []

     # Iterate over every instrument entry defined in the config file.
    for name, cfg in instruments.items():
        if not isinstance(cfg, dict):
             # Skip malformed entrie
            continue
             
        # Only consider E3631A entries
        if str(cfg.get("type", "")).strip().upper() != "E3631A":
            continue

        port = str(cfg.get("port", "")).strip()
        # Skip if this port is already claimed by a routine source (gate/drain/etc.)
        if not port or port in in_use_ports:
            continue

        # channel_map tells us what each physical output channel
        # (e.g. "P6V", "P25V", "N25V") is being used for.
        channel_map = cfg.get("channel_map")
        if not isinstance(channel_map, dict):
            continue

        # Here a current limit to apply to every fixed channel on this supply
        # (defaults to 0.1 A if not specified in config).
        current_limit_a = float(cfg.get("current_limit_a", 0.1))

         # Fixed_channels are power supply channels whose voltage is meant to be set once and left alone.
        fixed_channels: list[tuple[str, float]] = []
        for channel, mapped in channel_map.items():
            channel_text = str(channel).strip()
            mapped_text = str(mapped).strip()
             
            # Skip channels mapped to "none"/blank or to symbolic routine
            # roles (Vg, Vd, Vb, Vs, etc.) — those are handled elsewhere,
            # not as fixed auxiliary voltages.
            if mapped_text.lower() in {"none", "null", "", "vg", "vd", "vb", "vs", "vgxp", "vgxn"}:
                continue

             # Try to parse the mapped value as a literal voltage
            # (e.g. "3.3" or "3.3V"). If it doesn't parse as a number,
            # it's not a fixed-voltage assignment, so skip it.
            fixed_v = _parse_voltage_literal(mapped_text)
            if fixed_v is None:
                continue
                 
            # Skip rails meant to be set by hand (e.g. logic supply rails).
            if _is_manual_supply_rail(fixed_v):
                print(f"Skipping manual supply rail {name} {channel_text} = {fixed_v:.3f} V")
                continue
            fixed_channels.append((channel_text, fixed_v))
             
        # If this instrument has no fixed channels to apply, don't bother opening it.
        if not fixed_channels:
            continue

        # Open the supply and turn on the fixed-voltage channels identified above.
        supply = E3631A(
            port=port,
            baudrate=int(cfg.get("baudrate", 9600)),
            timeout_s=float(cfg.get("timeout_s", 1.0)),
        )
        supply.open()
        supply.output_on()

        # Apply each fixed voltage/current-limit pair to its channel.
        for channel, fixed_v in fixed_channels:
            supply.apply(channel, fixed_v, current_limit_a)
            print(f"Set fixed supply {name} {channel} = {fixed_v:.3f} V")

        print(f"Enabled auxiliary E3631A {name} on {port}")

         # Track this instance so the caller can turn it off / close it
        # later (e.g. in main()'s finally block).
        opened.append(supply)

    return opened


def build_parser() -> argparse.ArgumentParser:
    """Define and return the command-line argument parser for this script."""
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

    # Load instrument config (SMU/supply ports, channel maps, etc.) and the
    # list of routine specs (sweep/step definitions) from the CSV.
    config = load_project_config(args.config)
    routine_specs = load_routines_csv(args.routines_csv)

    # Decide which routine(s) to run: either a single index or all of them.
    if args.routine_index is None:
        routine_indices = list(range(len(routine_specs)))
    else:
        if args.routine_index < 0 or args.routine_index >= len(routine_specs):
            raise ValueError(f"routine_index {args.routine_index} out of range [0, {len(routine_specs) - 1}]")
        routine_indices = [args.routine_index]
    
    # Reset/close any lingering connections on the ports used by the main
    # routine sources (gate, drain, bulk, and any other quantity sources)
    # before opening them for real, to avoid "port already in use" issues.
    ports_to_reset = [config.gate_source.port, config.drain_source.port]
    if config.bulk_source:
        ports_to_reset.append(config.bulk_source.port)
    for _, src_cfg in config.quantity_sources.items():
        if src_cfg.port not in ports_to_reset:
            ports_to_reset.append(src_cfg.port)
    reset_serial_ports(ports_to_reset)
    time.sleep(0.5)  # Brief pause after reset

    # Turn on any auxiliary fixed-voltage E3631A channels that aren't part
    # of the main routine sources.
    aux_supplies = _enable_aux_fixed_e3631a(args.config, set(ports_to_reset))
    
    all_points: list[RoutineMeasurement] = []
    completed: list[tuple[int, str, int]] = []

    try:
        for order, routine_index in enumerate(routine_indices):
            selected_routine = routine_specs[routine_index]

            # Setup live plot for routine unless disabled by user flag
            live_plot = None if args.no_live_plot else LiveRoutinePlot(
                routine_name=selected_routine.name,
                step_param=selected_routine.step_param,
                sweep_param=selected_routine.sweep_param,
            )
            try:
                # Running the routine, feeding each new point to
                # live plots update() callback as its acquired
                # Only prompt for config before first routine
                # (order == 0 ), and only if user hasn't disabled it
                routine, points = run_single_routine_from_csv(
                    config=config,
                    routines_csv=args.routines_csv,
                    routine_index=routine_index,
                    point_callback=None if live_plot is None else live_plot.update,
                    confirm_initial_bias=(not args.no_confirm_initial and order == 0),
                    ids_settle_s=args.ids_settle_s,
                )
            finally:
                # Always finalize (block on) the plot window, even if the
                # routine raised an exception, so the user can still see
                # whatever data was captured.
                if live_plot is not None:
                    live_plot.finalize()

            all_points.extend(points)
            completed.append((routine_index, routine.name, len(points))) # add index, name, and points to list

        # Write out all collected measurement points across all routines run.
        write_routine_measurements_csv(args.output_csv, all_points)
    finally:
        # Always attempt to turn off and close auxiliary supplies, even if
        # something above failed, to avoid leaving voltages applied.
        for supply in aux_supplies:
            try:
                supply.output_off()
            finally:
                supply.close()
                 
    # Print a summary of what was run.
    print(f"Routines run: {len(completed)}")
    for routine_index, routine_name, point_count in completed:
        print(f"  - index {routine_index}: {routine_name} ({point_count} points)")
    print(f"Points total: {len(all_points)}")
    print(f"Saved: {args.output_csv}")


if __name__ == "__main__":
    main()
