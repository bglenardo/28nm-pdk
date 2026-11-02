"""Fast automated device-array scan.

Scans over a Flavor x Row x Col device array (selected from the CLI) running one
or more routines per device, with NO confirmation pause and NO live plot so that
the time between points and sweeps is minimized. Results for every device are
aggregated into a single CSV tagged with the device coordinates.

For interactive single-device bring-up with a confirmation pause and live plot,
use ``run_routine_test.py`` instead.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import sys
import time
from pathlib import Path

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
    tag_measurements_with_device,
    write_routine_measurements_lbl_csv,
)
from iv_measure.bench import (
    enable_aux_fixed_e3631a,
    _is_serial_port_name,
    _load_arduino_switcher,
    _parse_index_list,
    _serial_port_names,
    reset_serial_ports,
    select_device_on_arduino,
)


def run_device_array_scan(
    config,
    routines_csv: str | Path,
    arduino_switcher,
    flavors: list[int],
    rows: list[int],
    cols: list[int],
    chip: int,
    routine_indices: list[int],
    ids_settle_s: float,
    verify_enabled: bool,
) -> list[RoutineMeasurement]:
    """Iterate a device array (Flavor x Row x Col), running routines on each.

    For every device: VERIFY+SEL on the scan chain, run each requested routine
    via ``run_single_routine_from_csv`` (which opens/closes its own instrument
    pool), tag the points with the device coordinates, and accumulate them. No
    confirmation pause is used so the scan runs unattended. The caller writes the
    aggregated list to a single CSV.
    """
    devices = [(f, r, c) for f in flavors for r in rows for c in cols]
    total = len(devices) * len(routine_indices)
    all_points: list[RoutineMeasurement] = []
    done = 0

    print(
        f"Device-array scan: {len(devices)} device(s) x {len(routine_indices)} "
        f"routine(s) = {total} acquisition(s)."
    )

    for flavor, row, col in devices:
        print(f"\n=== Device flavor={flavor} row={row} col={col} chip={chip} ===")
        select_device_on_arduino(arduino_switcher, flavor, row, col, chip, verify_enabled)

        for routine_index in routine_indices:
            done += 1
            print(f"[{done}/{total}] Running routine index {routine_index} ...")
            _routine, points = run_single_routine_from_csv(
                config=config,
                routines_csv=routines_csv,
                routine_index=routine_index,
                point_callback=None,
                confirm_initial_bias=False,
                ids_settle_s=ids_settle_s,
            )
            tagged = tag_measurements_with_device(
                points, flavor=flavor, row=row, col=col, chip=chip
            )
            all_points.extend(tagged)

    return all_points


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Automated multi-device scan. Iterates a Flavor x Row x Col device "
            "array as quickly as possible (no confirmation pause, no live plot) "
            "and writes one aggregated CSV tagged with device coordinates."
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
        default=None,
        help="Path to aggregated output CSV. If omitted, a name encoding the "
             "board and chip is generated automatically, e.g. "
             "data/array_scan_board1_chip2.csv.",
    )
    parser.add_argument(
        "--board",
        type=int,
        default=1,
        help="Board ID number. Recorded in the auto-generated output filename (default: 1).",
    )
    parser.add_argument(
        "--device-flavors",
        type=str,
        required=True,
        help="Flavor indices as a comma/range list (e.g. '1', '1,2', '1-3').",
    )
    parser.add_argument(
        "--device-rows",
        type=str,
        required=True,
        help="Row indices as a comma/range list (e.g. '4', '1,2', '1-8').",
    )
    parser.add_argument(
        "--device-cols",
        type=str,
        required=True,
        help="Column indices as a comma/range list (e.g. '4', '1,2', '1-8').",
    )
    parser.add_argument(
        "--device-chip",
        type=int,
        default=1,
        help="Arduino scan-chain chip index (1 or 2) used when selecting devices (default: 1).",
    )
    parser.add_argument(
        "--routine-indices",
        type=str,
        default=None,
        help="Routine indices to run per device as a comma/range list (e.g. '0', '0,1', '0-2'). "
             "Defaults to just routine index 0.",
    )
    parser.add_argument(
        "--no-verify-device",
        action="store_true",
        help="Skip the per-device scan-chain VERIFY readback check.",
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
        help="Settling time in seconds before each Ids measurement (default: 1.0). "
             "Lower this to speed up the scan at the cost of settling accuracy.",
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

    flavors = _parse_index_list(args.device_flavors)
    rows = _parse_index_list(args.device_rows)
    cols = _parse_index_list(args.device_cols)
    routine_indices = _parse_index_list(args.routine_indices) or [0]

    # Default the output path to one that encodes the board and chip for
    # provenance, keeping the raw LBL column layout untouched.
    output_csv = args.output_csv
    if output_csv is None:
        output_csv = f"data/array_scan_board{args.board}_chip{args.device_chip}.csv"

    arduino_switcher = _load_arduino_switcher(args.config)
    if arduino_switcher is None:
        raise ValueError("No Arduino selector was found in the config file; add an arduino entry to instrument_list.yaml.")

    routine_specs = load_routines_csv(args.routines_csv)
    for index in routine_indices:
        if index < 0 or index >= len(routine_specs):
            raise ValueError(f"routine_index {index} out of range [0, {len(routine_specs) - 1}]")

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

    start_time = time.time()
    try:
        points = run_device_array_scan(
            config=config,
            routines_csv=args.routines_csv,
            arduino_switcher=arduino_switcher,
            flavors=flavors,
            rows=rows,
            cols=cols,
            chip=args.device_chip,
            routine_indices=routine_indices,
            ids_settle_s=args.ids_settle_s,
            verify_enabled=not args.no_verify_device,
        )
        write_routine_measurements_lbl_csv(output_csv, points)
    finally:
        if arduino_switcher is not None:
            arduino_switcher.close()
        for supply in aux_supplies:
            try:
                supply.output_off()
            finally:
                supply.close()

    elapsed_s = time.time() - start_time
    print(
        f"\nDevice-array scan complete: {len(flavors) * len(rows) * len(cols)} device(s), "
        f"{len(routine_indices)} routine(s), {len(points)} total points in {elapsed_s:.1f} s."
    )
    print(f"Saved: {output_csv}")


if __name__ == "__main__":
    main()
