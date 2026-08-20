# 28nm Cryogenic PDK — Automated Transistor Characterization

This branch automates I-V characterization of the 28nm test structure: it
selects each transistor in the 1,584-device array via the Arduino scan chain,
runs the measurement routines, and saves a CSV + annotated PNG per device —
unattended. 

**Part I (§1–5) is everything you need to run the automation. Part II (§6–10)
is reference detail.**

---

# Part I — Running the automation

## 1. Setup

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
```

Then confirm:

1. **Sketch flashed:** `Arduino/sketch_may26_r4_SEL_align/` for **chip 1**,
   `Arduino/sketch_may26_r4_SEL_chip2/` for **chip 2**. Flash with
   `arduino-cli`, then **close the Serial Monitor** (the port is
   single-occupancy).
2. **`instrument_list.yaml` matches your hardware** — correct COM ports and
   SCPI strings for the Keithley 2400 and E3631A (format in §7). Windows
   reassigns COM numbers after a replug — verify every session
   (Device Manager or `python probe_port.py`).
3. **Chip powered** (vdda core + I/O rail) and vgx rails present.

## 2. Pre-flight — run on first session to ensure correct COM 

```powershell
python test_scan_link.py --scan-port COM13
```

Verifies: `READY` banner → `PING`/`PONG` → `SEL 3 0 0` with `Mismatches <= 4`
→ a second SEL. Exit code 0 = ready. Run it twice; require identical results.

> **A healthy chain reports 2–3 mismatches and prints "Test Failed" — that is
> the ideal result.** 0 = readback saw nothing; >4 = real fault. Details in §10.

## 3. Pick your devices — `devices.csv`

Header + one `flavor,row,col` per line:

```csv
flavor,row,col
3,0,0
8,2,5
```

`row` is 0–5. `col` is 0–24, **except flavor 4 (native): 0–13**. Out-of-range
lines are rejected with an error before anything runs. nMOS vs pMOS is handled
automatically — each flavor is routed to the correct-polarity routine file.

| Flavor | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Name | nmos_lvt | nmos_hvt | nmos_mid | nmos_na (native) | nmos_ulvt | nmos_dnw | pmos_ulvt | pmos_lvt | pmos_mid | pmos_hvt | pmos_lvt_b |

Generate lists instead of typing them with claude when testing the entire array

## 4. Run the loop — `run_device_loop.py`

```powershell
python run_device_loop.py `
  --devices devices.csv `
  --routines-nmos "Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv" `
  --routines-pmos "Routines/Cryo PDK DC measurement routines - pMOS 28nm.csv" `
  --routine-index 0 1 `
  --scan-port COM13
  --out data/chip_one
--ignore-readback
```

| Argument | Default | Meaning |
|----------|---------|---------|
| `--devices` | required | The `flavor,row,col` CSV (§3). |
| `--routines-nmos` / `--routines-pmos` | required* | Routine CSV per device type. *Or pass `--routines` once for both. |
| `--routine-index` | `0` | Routine row(s), 0-based; accepts several: `0 1`. |
| `--scan-port` | required | Arduino port. |
| `--config` | `instrument_list.yaml` | Instrument config. |
| `--out` | `data/device_loop` | Output root; same `--out` resumes (§5). |
| `--ignore-readback` | off | The code has features that were meant to automatically diagnose mistakes in plotting and stop bad runs, needs work so its best to run this above as well as a flag |
| `--live-plot` | off | Live point-by-point plot per device. Omit for headless overnight runs; PNGs save either way. |

Per device it: SELs the device → routes to the correct-polarity routine → runs
the unmodified measurement engine → saves CSV + annotated PNG (geometry
stamped) → grades the curve shape.

## 5. Outputs and resume

```
<out>/<nmos|pmos>/<flavor-name>_r<row>c<col>/
    <device>__<geometry>__<routine>_<date>.csv    raw points
    <device>__<geometry>__<routine>_<date>.png    annotated plot
    <...>__mirrored.csv     (pMOS output only) as-plotted companion
    <...>.SUSPECT.txt       only if the shape grader flagged it
```

- **Resume:** re-running with the same `--out` skips any (device, routine)
  pair that already has a dated CSV — an interrupted run picks up where it
  stopped. Delete a device's CSV to force re-measurement.
- **Grading:** `validate_iv.py` marks runs `SUSPECT` (leakage floor,
  compliance-pinned, or no gate modulation) instead of silently counting them
  as good. Final summary: `done / skipped / failed / suspect`.

---

# Part II — Reference

## 6. What every file does

**Automation (this branch):**
`run_device_loop.py` the overnight loop (§4) · `test_scan_link.py` pre-flight
(§2) · `scan_link.py` shared serial protocol (imported, not run) ·
`device_registry.py` flavor → type/columns/scan-bit truth table ·
`device_geometry.py` W/L/nf per device for plot labels · `validate_iv.py`
output-shape grader.

**Measurement engine (original, untouched):** `src/iv_measure/` — routine
engine (`routines.py`), config loader, and Keithley 2400 / E3631A / BK 9132C
drivers · `run_routine.py` original single-routine runner (§8) ·
`instrument_list.yaml` ports + roles · `Routines/` nMOS and pMOS routine CSVs
(index 0 = Output WO Bulk, 1 = Accumulation to Inversion).

**Arduino:** `sketch_may26_r4_SEL_align/` **chip 1 production** ·
`sketch_may26_r4_SEL_chip2/` **chip 2 production** (adds a second 344-clock
phase to reach the daisy-chained chip) ·
`sketch_may26_r4_copy_20260609150247/` the unpatched original baseline ·
`sketch_may26_r4_SEL/` historical first patch, superseded ·
`lbl_arduino_board_switching_code/` **do not use** (wrong pins).

**Diagnostics (§9):** `probe_port.py`, `scan_bits.py`, `trace_short.py`,
`trace_gate_step.py`, `run_calibration.py`, `flush_analyze.py`,
`instrument_tests/`.

**Analysis:** `leakage_subtract.py` subtracts each device's own Vg=0 leakage
from routine-0 output curves · `overlay_leakage.py` overlays Id–Vd curves
across folders/digitized references · `overlay_vth_ladder.py` Vth ladder plot
across flavors · `plot_ids_vs_vgs.py` original CSV plotter.

**Docs/data:** `AUTOMATION.md` detailed runbook · `CHANGES_vs_main.md` branch
rationale · `CLAUDE.md` hardware quirks Q1–Q8 ·
`data/diagnostics_2026-07-13/` July fault-campaign evidence · `Manuals/`.

## 7. Configuration inputs and schemas

**`instrument_list.yaml`** — the hardware config consumed by all the Python
code: one entry per physical instrument, its serial port, and its logical
role. Key fields: `type` (`Keithley2400`, `E3631A`, `9132C`), `port` (`COM5`
etc.), and `quantity` or `channel_map` mapping the instrument to roles `Vg`,
`Vd`, `Vb`, `vgxp`, `vgxn`:

```yaml
instruments:
  keithley_2400:
    type: Keithley2400
    port: COM7
    quantity: Vd
  keithley_e3631a_a:
    type: E3631A
    port: COM5
    channel_map:
      P6V: Vb
      P25V: Vg
      N25V: None
```

**Routine CSVs** (`Routines/`) define what to measure and how to sweep it —
one routine per row, selected by `--routine-index`. Columns: `Measurement`,
`Parameter to sweep`, `Sweep Start/Stop`, `Num Sweep Points`,
`Parameter to Step`, `Step Start/Stop`, `Num Step Points`, and the init
voltages `Vg/Vb/Vd/Vs/vgxp/vgxn Init`. The nMOS file's row 0 is
"Output WO Bulk" (sweep Vd, step Vg), row 1 "Accumulation to Inversion"; the
pMOS file carries the negative-polarity equivalents.

**Output CSVs** follow the engine's `RoutineMeasurement` columns: `routine`,
`step_param`, `step_value_v`, `sweep_param`, `sweep_value_v`, `vg_v`, `vd_v`,
`vb_v`, `vs_v`, `vgxp_v`, `vgxn_v`, `drain_i_a`.

## 8. Manual single routine — `run_routine.py`

The original manual runner (no device selection, live plot, confirmation
pause) — measures whatever device is currently latched. To measure one
*specific* device, just put a single line in `devices.csv` and use the loop
(§4).



## 9. Bench diagnostics toolkit — *not fully fleshed out*

Testing code for verifying the bench (scan chain, bias paths, instruments).
**These workflows haven't been validated end-to-end.** The flags below are
transcribed from the source so they're accurate; `scan_bits.py` and the trace
scripts were exercised once during the 2026-07-13 fault campaign, the rest are
untested. Check each script's docstring/`--help` and update here once
confirmed.

| Script | What it does | Arguments |
|--------|--------------|-----------|
| `probe_port.py [PORT]` | Read-only liveness: list ports, print banner, PING→PONG. | positional port (optional) |
| `scan_bits.py` | Print SIN vs SOUT bit-by-bit with a verdict — sees stuck readbacks the mismatch count hides. | `--scan-port`* · `--flavor/--row/--col` (3/0/0) · `--width` (50) · `--save PATH` |
| `trace_short.py` | Gentle Vd sweep, fits R = dV/dI: short (Ω) vs leakage (kΩ) vs open. | `--config` · `--vmax` (0.1) · `--points` (11) · `--compliance` (1e-3) · `--settle` (0.3) · optional `--scan-port --flavor --row --col` to select first |
| `trace_gate_step.py` | Gentle Vd trace at stepped Vg — does the gate modulate at all? | as above, plus `--vg` (one or more values) · `--vmax` (0.2) · `--points` (9) · `--settle` (0.4) |
| `run_calibration.py` | Leakage baseline with *nothing* selected (all-zero chain). | `--routines`* · `--routine-index` (0) · `--scan-port`* · `--config` · `--out` (`data/calibration`) |
| `flush_analyze.py` | Two-chip chain-length discovery via pushed SEL. Matches the retired `_SEL_PUSH` protocol, not `_SEL_chip2`. | `--scan-port`* · `--flavor/--row/--col` (3/0/0) · `--push` (700) · `--save` |

\* = required.

## 10. The mismatch count, properly

The sketch compares Sout to Sin in the *same* clock cycle, so what exits
during loading is the chain's previous contents (zeros after reset). A perfect
chain therefore always flags the two one-hot bits — and prints "Test Failed."
This bench's weak-Sout analog read repeatably adds one more.

| Mismatches | Meaning |
|---|---|
| 0 | Readback saw nothing — suspicious. |
| 2 | Perfect chain. |
| 3 | Bench norm. |
| >4 | Real fault (Sout threshold, wiring, chip power). Loop aborts unless `--ignore-readback`. |

The count tests only the **readback** path, never selection. Selection is
proven by the shape of a real IV curve — which is what the output grader
checks. Never gate on the sketch's "Test Passed/Failed" strings; parse
`Mismatches: N`.
