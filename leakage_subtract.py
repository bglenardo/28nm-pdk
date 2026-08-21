#!/usr/bin/env python3
"""Subtract each device's own off-gate leakage curve from its other output steps.

Scope: routine 0 only -- "Output WO Bulk" (sweep=Vd, step=Vg). Routine 1
(Accumulation to Inversion) is NOT touched. Both NMOS and PMOS output are
handled; the OFF-gate step is the leakage floor and differs by type:

  * NMOS (original scope, locked 2026-08-18): OFF at Vg=0 (Vgs=0). Baseline =
    the Vg=0 V step. Routine 0 steps Vg at 0/0.3/0.6/0.9 V, so that curve is
    already inside every device's own Output CSV.
  * PMOS (added 2026-08-20): source sits at the rail (~0.9 V), so the device is
    OFF at the HIGHEST Vg step (Vgs->0) and fully ON at Vg=0. Baseline = the
    largest Vg step. Detected without flavor logic: run_device_loop writes a
    <stem>__mirrored.csv companion for PMOS output ONLY, so its presence marks
    a PMOS file, and the leaksub plot + CSV are built from that mirrored copy
    (as-plotted x = pivot - Vd) to match the device's normal PMOS plot.

  Baseline is SELF-CONTAINED per file: with the device's gate at its off value
  the drain reads the shared-rail leakage floor indexed by Vd. We take that
  Id_leak(Vd) curve and subtract it (Vd-matched, linear interpolation) from the
  SAME file's other Vg step curves. No separate/pre-existing baseline run.

For each device the script writes, NEXT TO the original CSV/PNG:
  * <stem>__leaksub.png -- 2x2: raw curves (linear + log|Id|) on top, the
    leakage-subtracted curves on the bottom, one line per Vg step.
  * <stem>__leaksub.csv -- the original rows with drain_i_a replaced by the
    subtracted value (raw and baseline preserved in extra columns).
So a routine-0 device folder ends up with TWO PNGs (original + before/after)
and TWO CSVs (original + subtracted), all in one place.

Plot conventions (log floor 1e-15, Agg backend, sorted-by-Vd) match
overlay_leakage.py. Original files are read-only; nothing is overwritten.
"""
import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless, per project convention
import matplotlib.pyplot as plt

# routine 0 == "Output WO Bulk" (CLAUDE.md Section 3 / Routines nMOS file).
OUTPUT_ROUTINE_NAME = "Output WO Bulk"
LOG_FLOOR = 1e-15   # matches overlay_leakage.py so |Id| never hits log(0)
VG0_TOL = 1e-6      # a step within this of 0 V counts as the Vg=0 V baseline


def _interp(x, xs, ys):
    """Linear interpolation of ys(xs) at x; xs must be sorted ascending.

    Flat (clamped) extrapolation outside the baseline's Vd range so a target
    Vd slightly beyond the leakage sweep still gets the nearest floor value
    rather than NaN.
    """
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    t = (x - xs[lo]) / (xs[hi] - xs[lo])
    return ys[lo] + t * (ys[hi] - ys[lo])


def routine_name_of(csv_path: Path) -> str:
    """Read the 'routine' column from the first data row (empty string if none).

    Same field the device loop titles its PNGs with, so the leaksub plot can
    display the true routine name instead of a hardcoded constant.
    """
    with open(csv_path, newline="") as fh:
        for row in csv.DictReader(fh):
            return row.get("routine", "").strip()
    return ""


def geometry_subtitle(csv_path: Path) -> str:
    """Rebuild the single-plot device subtitle from the CSV filename.

    run_device_loop names files <device>__<geo>__<routine>_<date> where <geo> is
    device_geometry.label() with non-alnum runs turned into dashes, e.g.
    'flavor-8-pmos-lvt-W-0-1um-L-30nm-nf-1'. We invert that token to the same
    human string the singular NMOS/PMOS plots stamp, so the 2x2 leaksub plot
    carries identical flavor/row/col + W/L/nf labelling without importing
    device_geometry (this module stays pure / hardware-free). Falls back to ''
    if the filename is not in the expected 3-part shape.

    Original label form (device_geometry.label): 'flavor N (name) | W=.. L=.. nf=..'
    Reconstructed here as: '<device> | flavor N (name) | W=.. L=.. nf=..'
    """
    parts = csv_path.stem.split("__")
    if len(parts) < 2:
        return ""
    device, geo = parts[0], parts[1]
    toks = geo.split("-")
    # toks like: flavor 8 pmos lvt W 0 1um L 30nm nf 1  (dashes split '0.1um' too)
    out = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "flavor" and i + 1 < len(toks):
            # 'flavor 8' then the name tokens up to the W marker
            num = toks[i + 1]
            j = i + 2
            name = []
            while j < len(toks) and toks[j] != "W":
                name.append(toks[j])
                j += 1
            out.append(f"flavor {num} ({'_'.join(name)})")
            i = j
        elif t in ("W", "L", "nf") and i + 1 < len(toks):
            # W/L values may have been split on the decimal ('0','1um'); rejoin
            # tokens until the next known marker into one value string.
            j = i + 1
            val = []
            while j < len(toks) and toks[j] not in ("W", "L", "nf"):
                val.append(toks[j])
                j += 1
            # '0','1um' -> '0.1um'; '30nm' stays '30nm'
            out.append(f"{t}={'.'.join(val)}")
            i = j
        else:
            i += 1
    geo_str = " ".join(out)
    return f"{device} | {geo_str}" if geo_str else device


def load_output_curves(csv_path: Path):
    """Return {step_v: ([Vd sorted], [Id])} for one Output-routine CSV.

    Returns None if the file is not the Output routine (routine 0), so callers
    skip Accumulation / other files without touching them.
    """
    curves: dict[float, tuple[list[float], list[float]]] = \
        defaultdict(lambda: ([], []))
    with open(csv_path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print(f"  (skipping empty file: {csv_path.name})")
        return None
    routine = rows[0].get("routine", "").strip()
    if routine != OUTPUT_ROUTINE_NAME:
        # As requested, subtraction is applied to routine 0 ("Output WO Bulk")
        # ONLY. Routine-1 (Accumulation to Inversion) files are left alone.
        print(f"  (leaving routine-1 file untouched: {csv_path.name})")
        return None
    for row in rows:
        step_v = float(row["step_value_v"])
        xs, ys = curves[step_v]
        xs.append(float(row["sweep_value_v"]))
        ys.append(float(row["drain_i_a"]))
    # sort each curve by Vd (monotonic left-to-right, per overlay_leakage.py)
    out = {}
    for step_v, (xs, ys) in curves.items():
        pts = sorted(zip(xs, ys))
        out[step_v] = ([p[0] for p in pts], [p[1] for p in pts])
    return out


def baseline_from_curves(curves, pmos=False):
    """Pick the file's own leakage-floor Vg step as (step_v, (Vd, Id)) baseline.

    The leakage floor is the gate bias that turns the device OFF, so its curve
    is the shared-rail leakage indexed by Vd:

      * NMOS (pmos=False): OFF at Vg=0 (Vgs=0). Baseline = the step nearest 0 V.
        Returns None if no step is within VG0_TOL of 0 V (e.g. an older run
        measured before the routine included a 0 V step).
      * PMOS (pmos=True): the source sits at the rail (~0.9 V), so the device is
        OFF at the HIGHEST Vg step (Vgs -> 0) and fully ON at Vg=0 (Vgs -> -0.9).
        Baseline = the LARGEST step value. Verified 2026-08-20 on pmos_lvt_r0c0:
        mean|Id| falls 5.6e-5 (Vg=0) -> 1.0e-6 (Vg=0.9), so the top step is the
        floor. (Subtracting Vg=0 -- the fully-ON curve -- would be wrong.)
    """
    if pmos:
        step = max(curves)          # most-off gate = leakage floor for PMOS
        return step, curves[step]
    step0 = min(curves, key=lambda s: abs(s))
    if abs(step0) > VG0_TOL:
        return None
    return step0, curves[step0]


def find_target_csvs(target: Path):
    """Expand a target (file or directory) to candidate CSVs.

    run_device_loop writes short, content-tagged names per device folder:
      <routine>_Raw.csv                 the raw measurement (what we subtract)
      <routine>_Mirrored.csv            PMOS-output as-plotted view (not a
                                        separate measurement -- skip)
      <routine>_Subtracted_Leakage.csv  this tool's own output (skip)
    So we take only *_Raw.csv files. (A bare file target is still honored as-is
    for the standalone CLI.)"""
    if target.is_file():
        return [target]
    return sorted(p for p in target.rglob("*_Raw.csv"))


def write_subtracted_csv(src_csv: Path, base_xs, base_ys, base_step: float,
                         out_csv: Path) -> None:
    """Re-emit src_csv with leakage-subtracted drain current.

    Preserves original column order/values; drain_i_a becomes (raw - baseline
    @Vd). Appends drain_i_raw_a (original reading) and drain_i_leak_a (the
    Vg=0 V baseline subtracted) so nothing is lost. A comment line records the
    baseline provenance.
    """
    with open(src_csv, newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    for extra in ("drain_i_raw_a", "drain_i_leak_a"):
        if extra not in fieldnames:
            fieldnames.append(extra)
    with open(out_csv, "w", newline="") as fh:
        fh.write(f"# leakage-subtracted; baseline = this file's own "
                 f"Vg={base_step:g} V step\n")
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            vd = float(row["sweep_value_v"])
            raw = float(row["drain_i_a"])
            leak = _interp(vd, base_xs, base_ys)
            row["drain_i_raw_a"] = repr(raw)
            row["drain_i_leak_a"] = repr(leak)
            row["drain_i_a"] = repr(raw - leak)
            w.writerow(row)


def plot_before_after(device: str, curves, base_xs, base_ys, base_step: float,
                      out_png: Path, routine_name: str = OUTPUT_ROUTINE_NAME,
                      subtitle: str = "", pmos: bool = False) -> None:
    """2x2: raw (linear/log) over corrected (linear/log), one line per Vg step.

    Every measured Vg step is drawn in BOTH rows, including the baseline step
    itself -- in the SUBTRACTED panels it is ~0 (baseline minus itself).

    subtitle: full device descriptor (flavor/row/col + W/L/nf) stamped as a
    second title line, matching the singular NMOS/PMOS device plots.
    """
    fig, axes = plt.subplots(2, 2, figsize=(13, 10), constrained_layout=True)
    (ax_lin_raw, ax_log_raw), (ax_lin_cor, ax_log_cor) = axes

    for step_v in sorted(curves):
        vd, idc = curves[step_v]
        lbl = f"Vg={step_v:.2f} V"
        ax_lin_raw.plot(vd, idc, marker="o", ms=3, lw=1.2, label=lbl)
        ax_log_raw.plot(vd, [abs(i) + LOG_FLOOR for i in idc],
                        marker="o", ms=3, lw=1.2, label=lbl)
        # The baseline step itself is drawn in the corrected panels too (it is
        # ~0 there -- baseline minus itself) so every measured Vg step appears
        # in both rows, per request 2026-08-20.
        idc_cor = [i - _interp(v, base_xs, base_ys) for v, i in zip(vd, idc)]
        ax_lin_cor.plot(vd, idc_cor, marker="o", ms=3, lw=1.2, label=lbl)
        ax_log_cor.plot(vd, [abs(i) + LOG_FLOOR for i in idc_cor],
                        marker="o", ms=3, lw=1.2, label=lbl)

    # Panel titles match the original single-device PNG ("<routine> (Linear)/
    # (Log)"), with a tag marking the source row: the top row is the as-plotted
    # input -- "Mirrored" for PMOS (the mirrored companion CSV feeds it), "Raw"
    # for NMOS -- and the bottom row is the leakage-subtracted result.
    source_tag = "Mirrored" if pmos else "Raw"
    ax_lin_raw.set_title(f"{routine_name} ({source_tag}) (Linear)")
    ax_log_raw.set_title(f"{routine_name} ({source_tag}) (Log)")
    ax_lin_cor.set_title(f"{routine_name} (Subtracted Leakage) (Linear)")
    ax_log_cor.set_title(f"{routine_name} (Subtracted Leakage) (Log)")
    for ax in (ax_log_raw, ax_log_cor):
        ax.set_yscale("log")
    # Axis labels match the single-device plots: PMOS shows |Drain current| (A)
    # (data plotted as measured); NMOS keeps "Drain current (A)". x is Vd (V).
    ylabel = "|Drain current| (A)" if pmos else "Drain current (A)"
    for ax in axes.flat:
        ax.set_xlabel("Vd (V)")
        ax.set_ylabel(ylabel)
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)
    # The geometry descriptor sits at the very top of the image (suptitle),
    # matching the singular NMOS/PMOS device PNGs. The device/routine info now
    # lives in the per-panel titles, so it is not repeated here.
    if subtitle:
        fig.suptitle(subtitle, fontsize=11)
    fig.savefig(out_png, dpi=200)
    plt.close(fig)


def subtract_tree(targets, out_dir: Path | None = None,
                  subtitle: str | None = None) -> tuple[int, int]:
    """Run self-subtraction over each target (CSV file or folder tree).

    Reusable entry point so run_device_loop.py can chain subtraction onto the
    measurement loop (one command) while the CLI main() below still works
    standalone. Returns (done, skipped). Only NMOS routine-0 ("Output WO Bulk")
    files are touched; everything else is reported and left alone.

    subtitle: exact image suptitle to stamp on the 2x2 plot. run_device_loop
    passes the SAME string it puts on the singular 1x1 device PNG so the two
    plots carry an identical top line (flavor #, W/L/nf, measured date). Left
    None for standalone CLI use, where the folder-derived device descriptor is
    used instead.
    """
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    done = skipped = failed = 0
    for target in targets:
        for csv_path in find_target_csvs(Path(target)):
            # Per-file guard: one unreadable/malformed CSV must not abort the
            # whole tree (added 2026-08-20). Before, a single failure here killed
            # the leakage pass for every device after it, silently. Successful
            # files are unaffected -- the body below is byte-identical to before,
            # only wrapped. Skips (not-routine-0, no baseline) still `continue`.
            try:
                # PMOS OUTPUT only: run_device_loop writes a <stem>__mirrored.csv
                # companion (sweep_value_v = pivot - Vd, drain_i_a unchanged) that
                # matches the plotted x-axis. When it exists, drive BOTH the
                # leaksub plot and the subtracted CSV from it, so the leakage
                # output is in the same as-plotted x as the device's normal PMOS
                # plot. NMOS files have no such companion, so this leaves them
                # exactly as before. The subtracted Id values are identical either
                # way -- subtraction is pointwise and matched on the sweep column,
                # so mirroring the curve and its Vg=0 baseline together only
                # relabels x. (Requested 2026-08-20: "for the leakage plot use the
                # mirrored csv data".)
                # PMOS-output devices get a <routine>_Mirrored.csv companion
                # next to the <routine>_Raw.csv; its presence marks a PMOS file.
                # csv_path is "<routine>_Raw.csv", so swap the _Raw suffix for
                # _Mirrored to find it.
                mirrored = csv_path.with_name(
                    csv_path.name[:-len("_Raw.csv")] + "_Mirrored.csv")
                is_pmos = mirrored.exists()  # only PMOS output gets a mirrored copy
                src_csv = mirrored if is_pmos else csv_path
                curves = load_output_curves(src_csv)
                if not curves:  # not routine 0 -> already reported, left untouched
                    continue
                # PMOS leakage floor = most-off gate (highest Vg step); NMOS = Vg=0.
                base = baseline_from_curves(curves, pmos=is_pmos)
                if base is None:
                    print(f"  SKIP {csv_path.name}: no Vg=0 V step in this file "
                          f"(steps: {sorted(curves)}); cannot self-subtract.")
                    skipped += 1
                    continue
                base_step, (base_xs, base_ys) = base
                # Descriptor from the folder path (FLAVOR/width/length), since the
                # short filename no longer carries geometry. Pure path parsing --
                # no device_geometry import, so this module stays hardware-free.
                # parents[0..2] = length, width, flavor dirs; reversed reads
                # "NMOS_MID / 0.1um / L_30nm_NF_1".
                path_parts = [p.name for p in list(csv_path.parents)[:3]][::-1]
                device = " / ".join(path_parts) if path_parts else csv_path.parent.name
                # Routine name straight from the CSV (same source the loop's PNG
                # title uses), so the leaksub plot labels the routine like the
                # other plots. load_output_curves already gated on this being the
                # Output routine, so it is populated.
                routine_name = routine_name_of(src_csv) or OUTPUT_ROUTINE_NAME
                # Output name mirrors the loop's convention: the raw file is
                # "<routine>_Raw", so its leakage result is
                # "<routine>_Subtracted_Leakage.{png,csv}" beside it.
                base_stem = csv_path.name[:-len("_Raw.csv")]  # e.g. Output_WO_Bulk
                dest = out_dir if out_dir else csv_path.parent
                out_png = dest / f"{base_stem}_Subtracted_Leakage.png"
                out_csv = dest / f"{base_stem}_Subtracted_Leakage.csv"
                # Suptitle sits at the very top of the image, matching the
                # singular NMOS/PMOS device PNGs. When run_device_loop supplies
                # its exact 1x1 suptitle, use it verbatim so both plots share an
                # identical top line; otherwise (standalone CLI) fall back to the
                # folder-derived device descriptor.
                plot_before_after(device, curves, base_xs, base_ys, base_step,
                                  out_png, routine_name=routine_name,
                                  subtitle=(subtitle if subtitle is not None
                                            else device),
                                  pmos=is_pmos)
                write_subtracted_csv(src_csv, base_xs, base_ys, base_step, out_csv)
                note = " (from mirrored)" if src_csv is mirrored else ""
                print(f"  {csv_path.name} -> {out_png.name}, {out_csv.name}{note}")
                done += 1
            except Exception as exc:  # noqa: BLE001 -- one file must not stop the rest
                print(f"  ERROR {csv_path.name}: {type(exc).__name__}: {exc} "
                      f"-- skipping this file, continuing.")
                failed += 1

    tail = f", {failed} failed" if failed else ""
    print(f"{done} device curve(s) corrected, {skipped} skipped{tail}")
    return done, skipped


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", action="append", dest="targets", required=True,
                    help="device CSV or folder tree of NMOS routine-0 CSVs. "
                    "Each file's own Vg=0 V step is used as its baseline. "
                    "(repeatable)")
    ap.add_argument("--out-dir", default=None,
                    help="where the __leaksub PNG+CSV are written. DEFAULT: next "
                    "to each source CSV, so the original and subtracted files "
                    "share one folder. Pass a path to collect them elsewhere.")
    args = ap.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else None
    subtract_tree(args.targets, out_dir)


if __name__ == "__main__":
    main()
