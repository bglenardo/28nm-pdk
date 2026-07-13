# `automated_characterization` — changes vs `main`, and why

This branch adds automation to loop the 28nm MOSFET array (select device → run
the existing IV routine → save CSV + plot) plus a set of bench-diagnostic tools.
It follows the PRIME CONSTRAINT in `CLAUDE.md`: the original measurement code is
**not modified**. Everything new lives in new repo-root files; the one edited
non-original artifact is a *copy* of the Arduino sketch.

## What is NOT changed (deliberately)
- `src/iv_measure/**` — imported and called, never edited. The measurement
  engine (`run_single_routine_from_csv`) is byte-for-byte what the original
  `run_routine.py` uses.
- `instrument_list.yaml`, the original routine CSVs, and the original sketches.

## New files and why

### Automation
- **`run_device_loop.py`** — the overnight loop: for each device in a CSV, send
  `SEL <flavor> <row> <col>` to the SEL sketch, run the existing routine, save
  CSV + annotated PNG, grade the shape, and resume-skip finished devices.
- **`run_one_device.py`** — single device, no loop/resume logic. Built for A/B
  testing against the original path (same measurement call, only serial
  selection added). `--no-select` mimics the original no-selection runner.
- **`device_registry.py`** — single source of truth for flavor → type
  (nMOS 1–6 / pMOS 7–11), subtype, columns, scan base bit. From the sketch's
  `flavor_base[]`, confirmed against datasheet p.2. Drives correct-polarity
  routing so a pMOS device never gets an nMOS-polarity sweep.
- **`device_geometry.py`** — W/L/nf per (flavor,row,col) from `CLAUDE.md` §2.2,
  used to stamp geometry on each plot. DRC cap + native/DNW caveats encoded.
- **`validate_iv.py`** — `grade_output_family()` flags physically implausible
  runs (leakage floor / compliance-pinned / no gate modulation, per Q8) so a
  bad run is marked `SUSPECT` instead of silently counting as good.
- **`Routines/Cryo PDK DC measurement routines - pMOS 28nm.csv`** — new pMOS
  routine (Vd sweep 0 → −0.85). A NEW file; the original nMOS CSV is untouched.

### Diagnostics (added while debugging the bench 2026-07-13)
- **`scan_bits.py`** — sends a SEL and prints the scan chain **SIN vs SOUT**
  bit-by-bit with a plain-language verdict. This is how you see whether the
  read-back is healthy vs. stuck — the summary "Mismatches" count hides it.
- **`trace_short.py`** — gentle low-V / low-compliance Vd sweep; fits R = dV/dI
  to tell a real short (few Ω) from leakage (kΩ) from an open node.
- **`trace_gate_step.py`** — gentle Vd trace stepping Vg; shows whether the
  channel current responds to the gate (working transistor) or not.
- **`run_calibration.py`** — datasheet §2.3 leakage baseline: measure with
  nothing selected (latches an all-zero chain via an out-of-range SEL).

### Docs / helpers
- **`RUNBOOK.md`** — how to run everything by hand (setup, ports, bias, the
  scan bit-stream check, the traces, the loop, result interpretation).
- **`CHANGES_vs_main.md`** — this file.
- **`devices_*.csv`** — example/working device lists.

## Modifications to files already on this branch
- **`run_device_loop.py`** — scan mismatch abort threshold relaxed from `>2` to
  `>4` (CLAUDE.md Q2: 2 ideal, 3 is the bench norm); type-aware routing +
  geometry annotation + `data/<chip>/<nmos|pmos>/<device>/<routine>_<date>.*`
  output layout + shape grading; robust Q6 port-open (PING/PONG fallback);
  `--ignore-readback` for when the Sout read-back is known-broken.
- **`test_scan_link.py`** — same `>2`→`>4` relaxation and the Q6 PING/PONG
  fallback so a missing READY banner is no longer a false failure.

## Bench status recorded on this branch (2026-07-13)
The automation is validated: an A/B test on the same device (nmos_mid r0c0)
showed **this code and the original `run_routine.py` + original sketch produce
identical curves** — so the current "no gate modulation, pinned at compliance"
result is a **shared bench/hardware issue, not the automation**. The scan
read-back (Sout, chip pin 15 → Arduino A1) is **stuck HIGH** (`scan_bits.py`),
and gentle traces show the silicon conducts real current (not a dead short).
Evidence: `data/diagnostics_2026-07-13/`. Next hardware step: meter Sout pin 15
during a SEL.
