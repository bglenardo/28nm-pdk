"""Interactive single-device routine runner.

Runs ONE routine on ONE device with a confirmation pause after the initial
voltages are applied and a live matplotlib plot. Use this for bring-up and
spot checks; use ``run_routine_automated_scan.py`` for fast multi-device scans.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import math
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

# Allow running this script directly from repository root without pip install -e .
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from iv_measure.config import load_project_config
from iv_measure.keithley2400 import build_voltage_source_init_commands
from iv_measure.routines import (
    load_routines_csv,
    MANUAL_QUANTITIES,
    RoutineMeasurement,
    run_single_routine_from_csv,
    write_routine_measurements_lbl_csv,
)
from iv_measure.bench import (
    enable_aux_fixed_e3631a,
    _is_serial_port_name,
    _load_arduino_switcher,
    _serial_port_names,
    reset_serial_ports,
    select_device_on_arduino,
)


class LiveRoutinePlot:
    """Live Ids plot with per-device baseline (Vg=0) subtraction.

    The curve measured at Vg = 0 V is treated as the leakage baseline for the
    device. For every point the plotted current is ``drain_i - baseline(sweep)``,
    matched by sweep value. The subtraction is DISPLAY-ONLY: raw currents are
    what get written to the CSV. If the routine never measures Vg = 0, no
    baseline exists and the raw currents are shown unchanged.
    """

    _BASELINE_KEY_DECIMALS = 6

    def __init__(self, routine_name: str, step_param: str, sweep_param: str) -> None:
        plt.ion()
        self._figure, (self._vds_linear_ax, self._vds_log_ax) = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)

        self._vds_linear_lines: dict[float, Line2D] = {}
        self._vds_log_lines: dict[float, Line2D] = {}
        self._vds_x_data: dict[float, list[float]] = {}
        self._vds_y_raw: dict[float, list[float]] = {}
        self._vds_y_data: dict[float, list[float]] = {}  # baseline-subtracted (displayed)

        # Baseline leakage current keyed by rounded sweep value, taken from the
        # Vg = 0 measurement.
        self._baseline: dict[float, float] = {}

        self._step_param = step_param
        self._sweep_param = sweep_param

        self._vds_linear_ax.set_title(f"{routine_name} Ids vs {sweep_param} (Linear, baseline-subtracted)")
        self._vds_linear_ax.set_xlabel(f"{sweep_param} (V)")
        self._vds_linear_ax.set_ylabel("Drain current - Vg=0 baseline (A)")
        self._vds_linear_ax.grid(True, alpha=0.3)

        self._vds_log_ax.set_title(f"{routine_name} Ids vs {sweep_param} (Log, baseline-subtracted)")
        self._vds_log_ax.set_xlabel(f"{sweep_param} (V)")
        self._vds_log_ax.set_ylabel("Drain current - Vg=0 baseline (A)")
        self._vds_log_ax.set_yscale("log")
        self._vds_log_ax.grid(True, which="both", alpha=0.3)

    def _baseline_key(self, sweep_value: float) -> float:
        return round(sweep_value, self._BASELINE_KEY_DECIMALS)

    def _subtracted(self, sweep_value: float, raw_current: float) -> float:
        return raw_current - self._baseline.get(self._baseline_key(sweep_value), 0.0)

    def _recompute_all(self) -> None:
        """Refresh every line from raw data minus the current baseline.

        Called on each update so curves drawn before the Vg=0 baseline was known
        get corrected once it arrives.
        """
        for step_value, line in self._vds_linear_lines.items():
            xs = self._vds_x_data[step_value]
            subtracted = [self._subtracted(x, y) for x, y in zip(xs, self._vds_y_raw[step_value])]
            self._vds_y_data[step_value] = subtracted
            line.set_data(xs, subtracted)
            log_ys = [value if value > 0 else math.nan for value in subtracted]
            self._vds_log_lines[step_value].set_data(xs, log_ys)

    def update(self, point: RoutineMeasurement) -> None:
        step_value = point.step_value_v
        vds_linear_line = self._vds_linear_lines.get(step_value)
        vds_log_line = self._vds_log_lines.get(step_value)
        if vds_linear_line is None or vds_log_line is None:
            (vds_linear_line,) = self._vds_linear_ax.plot([], [], marker="o", linewidth=1.5, markersize=4, label=f"{self._step_param}={step_value:.3f} V")
            (vds_log_line,) = self._vds_log_ax.plot([], [], marker="o", linewidth=1.5, markersize=4, label=f"{self._step_param}={step_value:.3f} V")
            self._vds_linear_lines[step_value] = vds_linear_line
            self._vds_log_lines[step_value] = vds_log_line
            self._vds_x_data[step_value] = []
            self._vds_y_raw[step_value] = []
            self._vds_y_data[step_value] = []
            self._vds_linear_ax.legend(loc="best")
            self._vds_log_ax.legend(loc="best")

        # Capture the Vg=0 measurement as the device's leakage baseline.
        if abs(point.vg_v) < 1e-9:
            self._baseline[self._baseline_key(point.sweep_value_v)] = point.drain_i_a

        self._vds_x_data[step_value].append(point.sweep_value_v)
        self._vds_y_raw[step_value].append(point.drain_i_a)

        self._recompute_all()

        self._vds_linear_ax.relim()
        self._vds_linear_ax.autoscale_view()
        self._vds_log_ax.relim()
        self._vds_log_ax.autoscale_view()
        self._ensure_log_limits()
        self._figure.canvas.draw_idle()
        self._figure.canvas.flush_events()
        plt.pause(0.001)

    def _ensure_log_limits(self) -> None:
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
        if plt.fignum_exists(self._figure.number):
            plt.ioff()
            plt.show(block=False)
            plt.close(self._figure)



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Interactively run a single routine on a single device. "
            "Applies init voltages first, pauses for confirmation, then performs "
            "step/sweep points with a live plot."
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
        default=0,
        help="0-based routine index from the CSV to run as the single routine (default: 0).",
    )
    parser.add_argument(
        "--device-flavor",
        type=int,
        default=None,
        help="Optional Arduino device-selection flavor index to choose before the routine starts.",
    )
    parser.add_argument(
        "--device-row",
        type=int,
        default=None,
        help="Optional Arduino device-selection row index to choose before the routine starts.",
    )
    parser.add_argument(
        "--device-col",
        type=int,
        default=None,
        help="Optional Arduino device-selection column index to choose before the routine starts.",
    )
    parser.add_argument(
        "--device-chip",
        type=int,
        default=1,
        help="Arduino scan-chain chip index (1 or 2) used when selecting a device (default: 1).",
    )
    parser.add_argument(
        "--no-verify-device",
        action="store_true",
        help="Skip the post-selection scan-chain VERIFY readback check (by default the "
             "selection is confirmed by clocking SOUT back and requiring zero mismatches).",
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
        "--four-wire",
        action="store_true",
        help="Use Keithley remote sense for the drain source and cap the source range at 2 V.",
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
    if config.drain_source.name == "keithley_2400":
        current_compliance_a = config.drain_source.current_compliance_a or 0.01
        init_commands = build_voltage_source_init_commands(
            current_compliance_a=current_compliance_a,
            remote_sense=args.four_wire,
            source_voltage_range_v=2.0,
        )
        config = replace(config, drain_source=replace(config.drain_source, init_commands=init_commands))

    arduino_switcher = _load_arduino_switcher(args.config)
    if any(v is not None for v in (args.device_flavor, args.device_row, args.device_col)):
        if args.device_flavor is None or args.device_row is None or args.device_col is None:
            raise ValueError("--device-flavor, --device-row, and --device-col must be provided together to switch devices.")
        if arduino_switcher is None:
            raise ValueError("No Arduino selector was found in the config file; add an arduino entry to instrument_list.yaml.")

    routine_specs = load_routines_csv(args.routines_csv)
    if args.routine_index < 0 or args.routine_index >= len(routine_specs):
        raise ValueError(f"routine_index {args.routine_index} out of range [0, {len(routine_specs) - 1}]")
    selected_routine = routine_specs[args.routine_index]
    live_plot = None if args.no_live_plot else LiveRoutinePlot(
        routine_name=selected_routine.name,
        step_param=selected_routine.step_param,
        sweep_param=selected_routine.sweep_param,
    )

    # Reset/close any lingering serial connections; ignore VISA/GPIB resource strings.
    ports_to_reset = _serial_port_names([
        config.gate_source.port,
        config.drain_source.port,
        config.bulk_source.port if config.bulk_source else None,
    ])
    for quantity, src_cfg in config.quantity_sources.items():
        # Never reset ports backing manual rails (vgxp/vgxn on the BK 9132C);
        # the operator controls those by hand and software must not touch them.
        if quantity in MANUAL_QUANTITIES:
            continue
        if _is_serial_port_name(src_cfg.port) and src_cfg.port not in ports_to_reset:
            ports_to_reset.append(src_cfg.port)
    reset_serial_ports(ports_to_reset)
    time.sleep(0.5)  # Brief pause after reset

    aux_supplies = enable_aux_fixed_e3631a(args.config, set(ports_to_reset))

    try:
        if arduino_switcher is not None and any(v is not None for v in (args.device_flavor, args.device_row, args.device_col)):
            # VERIFY must run BEFORE the final SEL: a VERIFY clocks the full 1032-bit
            # chain (pattern then trailing zeros) and latches at the end, which would
            # latch all-zeros and DESELECT the device. Doing the integrity check first
            # and the real SEL last leaves the requested device latched for the sweep.
            select_device_on_arduino(
                arduino_switcher,
                args.device_flavor,
                args.device_row,
                args.device_col,
                args.device_chip,
                verify_enabled=not args.no_verify_device,
            )

        routine, points = run_single_routine_from_csv(
            config=config,
            routines_csv=args.routines_csv,
            routine_index=args.routine_index,
            point_callback=None if live_plot is None else live_plot.update,
            confirm_initial_bias=not args.no_confirm_initial,
            ids_settle_s=args.ids_settle_s,
        )
        write_routine_measurements_lbl_csv(args.output_csv, points)
    finally:
        if arduino_switcher is not None:
            arduino_switcher.close()
        for supply in aux_supplies:
            try:
                supply.output_off()
            finally:
                supply.close()
        if live_plot is not None:
            live_plot.finalize()

    print(f"Routine index: {args.routine_index}")
    print(f"Routine: {routine.name}")
    print(
        "Sweep/Step: "
        f"{routine.sweep_param} {routine.sweep_start}->{routine.sweep_stop} ({routine.sweep_points}), "
        f"{routine.step_param} {routine.step_start}->{routine.step_stop} ({routine.step_points})"
    )
    print(f"Points: {len(points)}")
    print(f"Saved: {args.output_csv}")


if __name__ == "__main__":
    main()
