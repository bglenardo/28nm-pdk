"""run_device_loop.py -- loop devices -> run existing routines -> save CSV + PNG.

Drop this file in the REPO ROOT of bglenardo/28nm-pdk, next to run_routine.py.
It is written in the same style as run_routine.py and reuses the existing
machinery UNCHANGED:

    iv_measure.config.load_project_config      (instrument_list.yaml)
    iv_measure.routines.load_routines_csv      (the lab's routine CSVs)
    iv_measure.routines.run_single_routine_from_csv
    iv_measure.routines.write_routine_measurements_csv

The ONLY new behavior: before each routine it sends "SEL <flavor> <row> <col>"
to the Arduino (which must be running the ~30-line patch in
ARDUINO_PATCH.txt), then loops devices x routines, and saves a linear+log
Ids plot PNG next to each CSV.

Each device is routed to the correct-polarity routine file for its type
(nMOS flavors 1-6 vs pMOS flavors 7-11, per device_registry), and every
result is graded for physical plausibility (validate_iv, CLAUDE.md Q8) so a
meaningless run is flagged as SUSPECT instead of silently counting as done.

Usage:
    python run_device_loop.py \
        --devices devices.csv \
        --routines-nmos "Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv" \
        --routines-pmos "Routines/Cryo PDK DC measurement routines - pMOS 28nm.csv" \
        --routine-index 0 \
        --scan-port COM8 \
        --out data/loop_run1

(--routines <one file> still works and is used for both types.)

devices.csv format (header required); flavor uses the SKETCH's 1..11 numbers:
    flavor,row,col
    3,0,0
    3,0,1
    ...
Generate a whole block (e.g. all 150 of flavor 3 = nmos_mid) with:
    python -c "print('flavor,row,col');
    [print(f'3,{r},{c}') for r in range(6) for c in range(25)]" > devices.csv

Re-running with the same --out skips (device, routine) pairs whose CSV
already exists, so an interrupted overnight run resumes where it stopped.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

import matplotlib

# Backend must be chosen BEFORE pyplot is imported. Default is Agg (headless-
# safe: overnight runs have no display and just write PNGs). With --live-plot we
# need an interactive backend that can show a window, so we peek at argv here --
# argparse hasn't run yet at import time. PNGs are still saved either way.
_LIVE_PLOT = "--live-plot" in sys.argv
if not _LIVE_PLOT:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
import serial

# Same import shim as run_routine.py: run from repo root without pip install.
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from iv_measure.config import load_project_config
from iv_measure.routines import (
    RoutineMeasurement,
    load_routines_csv,
    run_single_routine_from_csv,
    write_routine_measurements_csv,
)

# New repo-root modules (pure, no hardware): flavor->type registry and the
# automated output-shape grader. These give each device the correct-polarity
# routine and flag physically-meaningless runs (CLAUDE.md Q8).
import device_registry
import device_geometry
from validate_iv import grade_output_family

# Reuse run_routine.py's live plot VERBATIM (its .update is the point_callback
# that run_single_routine_from_csv already fires per measured point). Imported
# lazily inside main() only when --live-plot is set, so a headless run never
# pulls in the interactive path.

# PMOS source rail (V). On this bench the pMOS source is held at 0.9 V and the
# TRANSFER routine's CSV stores its STEP Vd as |Vsd| (the source-drain drop),
# so the true device Vd shown in that plot's legend is VSD_RAIL_V - Vd (e.g. a
# CSV Vd of 0.3 is the real Vd = 0.6). Label-only; measured data is unchanged,
# and this applies ONLY to the transfer routine (step param == Vd).
VSD_RAIL_V = 0.9


# --------------------------------------------------------------------------- #
# Scan-Arduino helpers (talks to the SEL-patched sketch)
# --------------------------------------------------------------------------- #
def open_scan_arduino(port: str, baud: int = 115200) -> serial.Serial:
    """Open the port and confirm the SEL sketch is answering.

    Robust open per CLAUDE.md Q6: Arduino auto-reset on port-open is
    unreliable, so a READY banner may never appear. We wait briefly for READY,
    but "no banner" is NOT treated as failure -- we fall back to a PING/PONG
    liveness check. Only if PING gets no PONG do we conclude the sketch isn't
    there (wrong port, or the original firmware that hangs after 'start').
    """
    ser = serial.Serial(port=port, baudrate=baud, timeout=2)
    time.sleep(2.0)  # allow a reset-on-open (if it happens) to boot
    deadline = time.time() + 8
    while time.time() < deadline:
        line = ser.readline().decode(errors="ignore").strip()
        if line == "READY":
            return ser  # banner seen: freshly reset, buffers clean

    # No banner -- Q6 fallback: prove the parser is alive with PING/PONG.
    ser.reset_input_buffer()
    ser.write(b"PING\n")
    deadline = time.time() + 5
    while time.time() < deadline:
        line = ser.readline().decode(errors="ignore").strip()
        if line == "PONG":
            return ser
    raise RuntimeError(
        "Arduino gave no READY banner and did not answer PING with PONG -- "
        "is the SEL-patched sketch flashed, and is this the right port? "
        "(No banner alone is normal, Q6; no PONG means the parser isn't there.)")


def select_device(ser: serial.Serial, flavor: int, row: int, col: int,
                  ignore_readback: bool = False) -> None:
    """Send SEL and parse configureDevice()'s existing report.

    IMPORTANT: the sketch's built-in verification compares Sout to Sin in the
    SAME clock cycle of the load pass, so on a perfectly healthy chain it
    reports exactly 2 "mismatches" (the two one-hot bits) and prints
    "Test Failed" (CLAUDE.md Q1). On THIS bench the weak-Sout analog read
    hovers near threshold and repeatably yields 3 (CLAUDE.md Q2 / Section 5
    bench log, July 2026). We therefore accept Mismatches <= 4 and only abort
    on more, which indicates a real chain problem (stuck bit, threshold,
    wiring). The count only tests the Sout read-back path; correct selection
    is proven by measuring a real transistor.

    ignore_readback: when True, SEL_DONE is accepted regardless of the
    Mismatches count (still logged). Use only when the Sout READ-BACK path is
    known-broken but selection itself is being verified another way -- namely
    by grading the measured curve (validate_iv). Per Q1/Q2 the count tests only
    the read-back, never selection, so this does not lower measurement quality;
    the output-shape grader remains the real gate.
    """
    ser.reset_input_buffer()
    ser.write(f"SEL {flavor} {row} {col}\n".encode())
    mismatches: int | None = None
    deadline = time.time() + 30
    while time.time() < deadline:
        line = ser.readline().decode(errors="ignore").strip()
        if line.startswith("Mismatches:"):
            mismatches = int(line.split(":")[1])
        if line == "SEL_DONE":
            if mismatches is None:
                # Scope-mode / daisy-chain sketch (scopes_asic_test.ino) does
                # no analogRead and never prints Mismatches; SEL_DONE alone
                # confirms the 688-clock shift completed. The count only ever
                # tested the Sout read-back path, never selection (Q1/Q2), so
                # its absence is expected -- the output-shape grader is the real
                # gate on whether selection landed. Accept and move on.
                return
            if mismatches > 4:  # CLAUDE.md Q2 / Section 5: 2 ideal, 3 bench-normal
                msg = (f"scan verification: {mismatches} mismatches (>4). "
                       "2-3 is expected (same-cycle check quirk + weak-Sout "
                       "analog read); more means a real chain fault -- check "
                       "Sout threshold and wiring.")
                if not ignore_readback:
                    raise RuntimeError(msg)
                print(f"    WARN (readback ignored): {msg}")
            return
    raise RuntimeError("timed out waiting for SEL_DONE")


# --------------------------------------------------------------------------- #
# PMOS-output "as-plotted" companion CSV. The main CSV is the raw as-measured
# data (the "before" copy). For PMOS OUTPUT routines the plot reflects x about
# the sweep midpoint (pivot - Vd, see save_iv_plot's docstring) so the family
# reads left-to-right in |Vsd|. This returns a copy of the points with
# sweep_value_v replaced by that same mirrored value -- nothing else changes
# (drain_i_a stays exactly as measured) -- so the companion CSV matches the
# linear panel 1:1. Non-PMOS-output points are returned unchanged.
def mirror_points_for_plot(points: list[RoutineMeasurement], sweep_param: str,
                           pmos: bool) -> list[RoutineMeasurement]:
    if not (pmos and sweep_param == "Vd"):
        return list(points)
    xs = [p.sweep_value_v for p in points]
    pivot = (min(xs) + max(xs)) if xs else 0.0  # same pivot save_iv_plot uses
    return [replace(p, sweep_value_v=pivot - p.sweep_value_v) for p in points]


# --------------------------------------------------------------------------- #
# Plotting (same content as plot_ids_vs_vgs.py / run_routine.py live plot,
# rendered once from the finished point list)
def save_iv_plot(points: list[RoutineMeasurement], routine_name: str,
                 sweep_param: str, step_param: str, out_png: Path,
                 subtitle: str | None = None, pmos: bool = False) -> None:
    """Linear + log Ids vs sweep parameter, one curve per step value.

    subtitle: optional line stamped across the top of the image -- used to
    record the device geometry (flavor #, W, L, nf) and measurement date on
    the figure itself, per the requested output convention.

    pmos: when True the data is MIRRORED horizontally about the sweep midpoint
    while the x-axis keeps its normal orientation (0 V at left, ~0.9 V at right,
    positive labels). The Keithley reports the sweep as Vd going high->low, but
    it is physically sweeping |Vsd|, so as-measured the largest current sits at
    the 0.9 V point. Reflecting each x to (lo + hi) - x moves that largest-current
    point to the 0 V side and the smallest-current point to the 0.9 V side, so
    the curve reads left-to-right as |Vsd| increases. Current values are plotted
    exactly as measured (unchanged); only their x-positions are reflected.
    """
    by_step: dict[float, tuple[list[float], list[float]]] = {}
    for p in points:
        xs, ys = by_step.setdefault(p.step_value_v, ([], []))
        xs.append(p.sweep_value_v)
        ys.append(p.drain_i_a)

    # PMOS OUTPUT (Ids-vs-Vds) ONLY: reflect x about the sweep midpoint
    # (lo + hi - x). Pivot from the actual measured range so it is exact
    # regardless of sweep direction. The PMOS transfer (Vgs) sweep and ALL nmos
    # plots leave x untouched.
    pmos_output = pmos and (sweep_param == "Vd")
    pmos_transfer = pmos and (sweep_param == "Vg")
    if pmos_output:
        all_x = [x for xs, _ in by_step.values() for x in xs]
        pivot = (min(all_x) + max(all_x)) if all_x else 0.0
        mirror = lambda x: pivot - x
    else:
        mirror = lambda x: x

    fig, (ax_lin, ax_log) = plt.subplots(1, 2, figsize=(12, 5),
                                         constrained_layout=True)
    for step_v in sorted(by_step):
        xs, ys = by_step[step_v]
        px = [mirror(x) for x in xs]
        # PMOS transfer routine: CSV Vd (the STEP param) is |Vsd|, so show the
        # true device Vd = rail - Vd in the legend. PMOS-only, label only.
        label_v = (VSD_RAIL_V - step_v) if pmos_transfer else step_v
        label = f"{step_param}={label_v:.3f} V"
        ax_lin.plot(px, ys, marker="o", ms=3, lw=1.2, label=label)
        ax_log.plot(px, [abs(y) + 1e-15 for y in ys], marker="o", ms=3,
                    lw=1.2, label=label)
    if subtitle:
        fig.suptitle(subtitle, fontsize=10)
    ax_lin.set_title(f"{routine_name} (linear)")
    ax_log.set_title(f"{routine_name} (log)")
    ax_log.set_yscale("log")
    # Axis labels: PMOS transfer -> Vg (V) / |Drain current| (A); PMOS output ->
    # |Drain current| (A). NMOS is left exactly as before (raw sweep_param,
    # "Drain current"). The PMOS transfer TITLE is still "Ids vs Vgs".
    if pmos_transfer:
        xlabel, ylabel = "Vg (V)", "|Drain current| (A)"
    else:
        xlabel = f"{sweep_param} (V)"
        ylabel = "|Drain current| (A)" if pmos else "Drain current (A)"
    for ax in (ax_lin, ax_log):
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)
    fig.savefig(out_png, dpi=200)
    plt.close(fig)


# --------------------------------------------------------------------------- #
def load_device_list(path: Path) -> list[tuple[int, int, int]]:
    """Read devices.csv -> [(flavor, row, col), ...] with bounds checks."""
    devices: list[tuple[int, int, int]] = []
    with path.open(newline="") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            fl, r, c = int(row["flavor"]), int(row["row"]), int(row["col"])
            # Registry is the single source of truth for bounds (native array
            # = 14 cols, Q4). It raises with a device-specific message.
            try:
                device_registry.validate_flavor(fl, r, c)
            except ValueError as exc:
                raise ValueError(f"{path}:{i}: {exc}") from None
            devices.append((fl, r, c))
    return devices


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--devices", required=True, help="CSV: flavor,row,col")
    # Type-aware routing: nMOS and pMOS flavors get their own correct-polarity
    # routine file (the fix for the 2026-07-13 pMOS-on-nMOS-routine failure).
    ap.add_argument("--routines-nmos", help="routine CSV for nMOS flavors (1-6)")
    ap.add_argument("--routines-pmos", help="routine CSV for pMOS flavors (7-11)")
    ap.add_argument("--routines", help="single routine CSV used for BOTH types "
                    "(back-compat; overridden by --routines-nmos/-pmos)")
    ap.add_argument("--routine-index", type=int, nargs="+", default=[0],
                    help="which routine row(s) to run per device")
    ap.add_argument("--scan-port", required=True, help="Arduino serial port")
    ap.add_argument("--config", default="instrument_list.yaml")
    ap.add_argument("--out", default="data/device_loop")
    ap.add_argument("--ignore-readback", action="store_true",
                    help="do not abort on high scan Mismatches counts. The "
                    "count tests only the Sout read-back path (Q1/Q2), never "
                    "selection; use when Sout read-back is known-broken and "
                    "selection is verified by the output-shape grader instead.")
    ap.add_argument("--live-plot", action="store_true",
                    help="show a live matplotlib window that draws each device's "
                    "IV curve point-by-point as it is measured, then auto-closes "
                    "and advances to the next device (no clicking). PNGs are "
                    "saved either way. Omit for headless overnight runs.")
    args = ap.parse_args()

    # Live plot uses run_routine.py's class verbatim; import only when asked so
    # a headless run never touches the interactive path.
    global LiveRoutinePlot
    if args.live_plot:
        from run_routine import LiveRoutinePlot

    # Resolve which routine file each type uses. At least one source required.
    nmos_routines = args.routines_nmos or args.routines
    pmos_routines = args.routines_pmos or args.routines
    if not nmos_routines or not pmos_routines:
        ap.error("provide --routines-nmos and --routines-pmos (or --routines "
                 "for both)")

    config = load_project_config(args.config)          # existing loader
    devices = load_device_list(Path(args.devices))
    # Compliance magnitude for the shape grader (drain source; 0.01 A today).
    compliance_a = getattr(config.drain_source, "current_compliance_a", None) or 0.01
    # Cache the routine-name lookup per file so output paths stay stable.
    routine_names: dict[str, list] = {}

    def routines_for(path: str) -> list:
        if path not in routine_names:
            routine_names[path] = load_routines_csv(path)  # existing loader
        return routine_names[path]
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    scan = open_scan_arduino(args.scan_port)
    print(f"{len(devices)} devices x {len(args.routine_index)} routines "
          f"-> {out_root}")

    measured_on = date.today().isoformat()  # YYYY-MM-DD, stamped on outputs
    done = skipped = failed = suspect = 0
    for flavor, row, col in devices:
        kind = device_registry.kind_of(flavor)  # "nmos" | "pmos" -> subfolder
        dev_name = f"{device_registry.name_of(flavor)}_r{row}c{col}"
        # Geometry label for the plot (flavor #, W, L, nf), per output spec.
        geo_label = device_geometry.label(flavor, row, col)
        # Route to the correct-polarity routine file for this flavor's type.
        routines_path = str(device_registry.routine_file_for(
            flavor, nmos_path=nmos_routines, pmos_path=pmos_routines))
        routines = routines_for(routines_path)
        # Output layout: data/<out>/<nmos|pmos>/<device>/ with dated filenames.
        dev_dir = out_root / kind / dev_name
        for ridx in args.routine_index:
            rname = routines[ridx].name.replace(" ", "_")
            # Label the stem with the device so each CSV names the device it
            # measured and stays paired with its PNG (same stem). The CSV writer
            # itself is reuse-only (routines.py), so the label lives in the
            # filename: <device>_<geo>_<routine>_<date>. Geometry (W/L/nf) is
            # sanitized to a filename-safe token.
            geo_token = "-".join(
                t for t in ("".join(ch if ch.isalnum() else " "
                                    for ch in geo_label)).split())
            stem = f"{dev_name}__{geo_token}__{rname}_{measured_on}"
            csv_path = dev_dir / f"{stem}.csv"
            png_path = dev_dir / f"{stem}.png"
            # Resume: skip if this device+routine already has ANY dated CSV.
            # Glob matches the new stem shape (device__geo__routine_date) on any
            # date, so a re-run into the same --out still resumes correctly.
            if dev_dir.exists() and any(
                    dev_dir.glob(f"{dev_name}__*__{rname}_*.csv")):
                skipped += 1
                continue
            print(f"[{done + skipped + failed + 1}] {kind}/{dev_name} :: "
                  f"{rname}  ({geo_label})")
            try:
                select_device(scan, flavor, row, col,
                              ignore_readback=args.ignore_readback)
                # Live plot: reuse run_routine.py's LiveRoutinePlot unchanged.
                # Its .update is the point_callback the runner fires per point,
                # so the curve draws as it measures. Auto-advance (not finalize,
                # which would block): the figure is closed after each device.
                live = None
                if args.live_plot:
                    rspec = routines[ridx]
                    is_pmos = device_registry.is_pmos(flavor)
                    pmos_output = is_pmos and rspec.sweep_param == "Vd"
                    pmos_transfer = is_pmos and rspec.sweep_param == "Vg"
                    # PMOS OUTPUT only: mirror the live curve about the sweep
                    # midpoint (start + stop) to match the mirrored saved PNG.
                    # PMOS transfer and all NMOS leave x untouched (None).
                    mirror_pivot = (rspec.sweep_start + rspec.sweep_stop
                                    if pmos_output else None)
                    # PMOS transfer: device-only prefix so the live title reads
                    # "<device> Ids vs Vgs" (class adds descriptor); else keep
                    # the routine name.
                    live_name = (dev_name if pmos_transfer
                                 else f"{dev_name} {rspec.name}")
                    # PMOS transfer (Vd is the STEP param): relabel the Vd legend
                    # to true Vd = VSD_RAIL_V - Vd (CSV Vd is |Vsd|).
                    step_label_pivot = VSD_RAIL_V if pmos_transfer else None
                    live = LiveRoutinePlot(live_name,
                                           rspec.step_param, rspec.sweep_param,
                                           mirror_pivot=mirror_pivot,
                                           step_label_pivot=step_label_pivot,
                                           transfer_labels=pmos_transfer)
                spec, points = run_single_routine_from_csv(   # existing runner
                    config, routines_path, routine_index=ridx,
                    point_callback=(live.update if live is not None else None))
                if live is not None:
                    plt.close(live._figure)  # auto-advance to next device
                dev_dir.mkdir(parents=True, exist_ok=True)
                write_routine_measurements_csv(csv_path, points)  # existing
                # PMOS OUTPUT only: also write an "as-plotted" CSV whose
                # sweep_value_v is mirrored exactly like the PNG (pivot - Vd).
                # The main CSV above stays the raw as-measured "before" copy;
                # this <stem>__mirrored.csv is the "after" copy that matches the
                # plotted curve. Same reused writer, so both files share format.
                is_pmos_flavor = device_registry.is_pmos(flavor)
                if is_pmos_flavor and spec.sweep_param == "Vd":
                    mirrored = mirror_points_for_plot(
                        points, spec.sweep_param, pmos=True)
                    write_routine_measurements_csv(
                        dev_dir / f"{stem}__mirrored.csv", mirrored)
                # PMOS Vg-sweep transfer routine is titled "Ids vs Vgs" (device
                # prefix kept). NMOS and the Vd-sweep output family keep the
                # routine name unchanged.
                plot_title = (f"{dev_name} Ids vs Vgs"
                              if (is_pmos_flavor
                                  and spec.sweep_param == "Vg")
                              else f"{dev_name} {spec.name}")
                save_iv_plot(points, plot_title,
                             spec.sweep_param, spec.step_param, png_path,
                             subtitle=f"{geo_label}  |  measured {measured_on}",
                             # Source-reference the plot for PMOS flavors so the
                             # 0.9->0 sweep reads as a normal first-quadrant
                             # family. Detected from the flavor via the registry
                             # (the authoritative type map), not from the routine
                             # file, so it is correct however the device is routed.
                             pmos=is_pmos_flavor)
                # Grade the shape (Q8). Data is always kept; a bad shape is
                # flagged, not discarded, so it can't masquerade as a good run.
                verdict = grade_output_family(points, compliance_a=compliance_a)
                (dev_dir / f"{stem}.verdict.txt").write_text(str(verdict))
                if verdict.ok:
                    done += 1
                else:
                    suspect += 1
                    (dev_dir / f"{stem}.SUSPECT.txt").write_text(
                        "\n".join(verdict.reasons))
                    print(f"    SUSPECT: {'; '.join(verdict.reasons)}")
            except Exception as exc:  # noqa: BLE001 -- one device must not
                failed += 1           # kill the overnight loop
                print(f"    FAILED: {exc} -- continuing with next device")
                dev_dir.mkdir(parents=True, exist_ok=True)
                (dev_dir / f"{stem}.FAILED.txt").write_text(str(exc))
                time.sleep(1.0)

    print(f"finished: {done} done, {skipped} skipped (already had CSV), "
          f"{failed} failed, {suspect} suspect (bad shape, see SUSPECT.txt)")


if __name__ == "__main__":
    main()
