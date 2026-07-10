# CLAUDE.md — Project brief: automated characterization of the 28nm LDRD MOSFET array

You are Claude Code, working inside a clone of `bglenardo/28nm-pdk` at SLAC.
This file is your complete context: an earlier engineering session established
every hardware fact, bench finding, and design decision below. Treat this
document as trusted input, but VERIFY everything marked [CROSS-CHECK] against
the primary sources in the repo before writing code.

════════════════════════════════════════════════════════════════════════════
## 0. MISSION AND PRIME CONSTRAINT

**Mission:** produce automation that loops through the chip's transistor
array (select device → run existing IV routine → save CSV → save PNG plot),
runs unattended overnight, survives individual device failures, and resumes
after interruption.

**PRIME CONSTRAINT — MINIMALISM:** modify the original repository code as
little as physically possible. The repo's Python (`src/iv_measure/`) and its
Arduino scan functions have already talked to this chip on this bench; every
reimplemented line is a new opportunity for error. Concretely:

- `src/iv_measure/*.py` — **zero modifications.** Import and call only.
- Routine CSVs, `instrument_list.yaml` — **zero modifications** (ports may be
  updated by the human, not by you).
- The Arduino sketch — modify **only** `setup()`'s tail and the empty
  `loop()`, as a NEW sketch folder (never edit the originals in place).
- All new logic lives in NEW files at repo root.
- Never "improve," "clean up," or reformat original code you touch or read.
- If a task seems to require editing original files, STOP and propose
  alternatives to the human first.

════════════════════════════════════════════════════════════════════════════
## 1. GROUND-TRUTH HIERARCHY (when sources conflict, higher wins)

1. **Bench measurements** (recorded in §5 below) — physical reality.
2. **The newest working Arduino sketch** — `Arduino/sketch_may26_r4_copy_*/`
   (dated 2026-06-09). It runs on this bench. Its ACTIVE `#define`s and
   function bodies are authoritative for pins, polarities, timing, and the
   scan bit map.
3. **The "Mapping of Devices – Modified Design (SLAC-LBNL)" slide** — defines
   the 344-bit / 11-array chain of the chip physically at SLAC.
4. **The LBNL datasheet** ("28nm LDRD MOSFET Array Datasheet", P. Zarkos,
   rev 0.1, July 2024) — authoritative for array INTERNALS (geometry,
   indexing, scan-cell design, pads) but describes the ORIGINAL 472-bit
   design; its chain map and §4.1 erratum DO NOT apply to this chip.
5. This brief's transcriptions — accurate as of the earlier session, but if
   you find a conflict with 1–4, the primary source wins; report the
   discrepancy prominently.

This hierarchy exists because this project has repeatedly been burned by
stale documents: the datasheet's 472-bit chain doesn't match the chip; one
old sketch's header literally says "THESE PINS ARE ALL WRONG!"; the Sout
analog pin silently moved between sketch revisions. Trust artifacts that run,
then documents, in that order.

════════════════════════════════════════════════════════════════════════════
## 2. THE CHIP — VERIFIED FACTS

**Identity:** 28nm CMOS test ASIC ("MetaRock" die, LDRD MOSFET array block),
MODIFIED SLAC-LBNL design. Purpose: IV characterization for SPICE modeling at
4 K. Currently being characterized WARM (room temperature) first.

### 2.1 Scan chain (the device-selection mechanism)
- **344 bits total, 11 arrays**, daisy-chained FIFO. [CROSS-CHECK: the
  sketch's `TOTAL_BITS` and `flavor_base[]` table.]
- Selection is ONE-HOT: exactly two bits high — one row bit + one column bit
  in the target block. The user must never enable two rows or two columns.
- Per-block layout: bits [base .. base+5] = en_row<0..5>; bits [base+6 ..
  base+6+cols−1] = en_col; trailing no-connect spare(s) driven low.
- Block map (0-indexed bases; flavor numbers are the SKETCH's own 1–11):

  | # | name        | base | cols | notes                                |
  |---|-------------|------|------|--------------------------------------|
  | 1 | nmos_lvt    | 0    | 25   |                                      |
  | 2 | nmos_hvt    | 32   | 25   |                                      |
  | 3 | nmos_mid    | 64   | 25   | "mid" = regular Vt                   |
  | 4 | nmos_na     | 96   | 14   | NATIVE: 14 cols, 24-bit block, 4 spares |
  | 5 | nmos_ulvt   | 120  | 25   |                                      |
  | 6 | nmos_dnw    | 152  | 25   | deep n-well; only array with usable Vb |
  | 7 | pmos_ulvt   | 184  | 25   |                                      |
  | 8 | pmos_lvt    | 216  | 25   |                                      |
  | 9 | pmos_mid    | 248  | 25   |                                      |
  |10 | pmos_hvt    | 280  | 25   |                                      |
  |11 | pmos_lvt_b  | 312  | 25   | genuine SECOND pmos_lvt array        |

  Rows 0–5 everywhere. Total devices: 10×150 + 84 = **1,584**.
- Chain is FIFO: bits fed end-to-beginning (highest index enters Sin first).
  The sketch's `shiftScanChain()` already handles this — do not reimplement.
- Scan procedure (implemented in sketch, do not reimplement): assert Srst →
  shift 344 bits with two-phase non-overlapping clocks Sclkp/Sclkn → pulse
  Supdate to latch onto the array `en` ports. No Supdate pulse = DUT
  unchanged.
- Historical context you may see referenced: the ORIGINAL design was 472
  bits / 15 arrays (datasheet Table 3); the modification removed four
  area-filling repeat arrays. Array internals are unchanged.

### 2.2 Geometry (datasheet Figures 3–6 and 9–10 — these DO apply)
Row index = W; column index = (L, nf). Row mentioned first: (1,2) = row 1,
col 2.
- Standard arrays (all except native): rows W(µm) = 0.1, 0.2, 0.4, 0.8, 1.6,
  3 (rows 0–5). Cols 0–6: nf=1, L(nm) = 30, 40, 60, 90, 200, 500, 1000.
  Cols 7–24: multi-finger, grouped by L with nf = 2, 4, 8 within each group,
  L(nm) = 30 (cols 7–9), 40 (10–12), 60 (13–15), 90 (16–18), 500 (19–21),
  1000 (22–24). No L=200 multi-finger.
- Native array (flavor 4): rows W(µm) = 0.5, 0.75, 1, 1.5, 2, 2.5. Cols 0–4:
  nf=1, L(nm) = 300, 500, 600, 900, 1000. Cols 5–13: L = 300, 500, 1000 ×
  nf = 2, 4, 8.
- DRC exception: at L=1 µm, W caps at 2.65 µm — affects (5,6) and
  (5,22)–(5,24) in standard arrays.
- OPEN QUESTIONS (do not resolve by assumption; flag in outputs): whether W
  is per-finger or total; the DNW array's multi-finger dimensions (datasheet
  §2.1.3 contradicts itself — states "exact same pattern" as standard arrays
  but lists the native array's dimensions).

### 2.3 Pads / biasing model
- Selected device's gate → the shared **Vg** pad; drain/source → shared
  four-wire pads (Vdsense/Vdforce/Vssense/Vsforce, Kelvin sensing).
- ALL unselected gates are parked on **Vgxn** (NMOS, held ~50 mV BELOW
  ground, i.e. −50 mV) or **Vgxp** (PMOS, slightly above VDD) to suppress
  leakage. The lab code ramps these rails slowly (~10 s) by design — never
  shortcut that ramp.
- **Vb** pad connects ONLY to DNW-array bodies. Bulk devices' bodies are the
  common substrate.
- Leakage floor: with all devices disabled, the shared rails still carry the
  summed off-leakage of 1,583 neighbors — nA-scale at room temperature. The
  datasheet's calibration mode = measure with nothing selected, subtract.
- Nominal supplies: vdda = 0.9 V core, 1.8 V I/O rail; both currently set on
  a MANUAL bench supply not under software control.

════════════════════════════════════════════════════════════════════════════
## 3. THE REPOSITORY — WHAT EXISTS AND WHAT TO REUSE

[CROSS-CHECK all of this by reading the actual files before planning.]

```
src/iv_measure/            REUSE VERBATIM (import, never edit):
  config.py                load_project_config(path) ← instrument_list.yaml
  routines.py              load_routines_csv(path) → list[RoutineSpec]
                           run_single_routine_from_csv(config, csv_path,
                               routine_index) → (spec, points)  ← runs ONE
                               full routine: init biases, vgx ramp, step
                               param loop, sweep param loop, Keithley reads
                           write_routine_measurements_csv(path, points)
                           RoutineMeasurement dataclass: routine, step_param,
                               step_value_v, sweep_param, sweep_value_v,
                               vg_v, vd_v, vb_v, vs_v, vgxp_v, vgxn_v,
                               drain_i_a
  keithley2400.py, e3631a.py, bk9132c.py, serial_instrument.py  ← drivers
run_routine.py             existing single-device runner (reference style;
                           note its sys.path.insert(0, "src") shim — copy
                           that pattern)
plot_ids_vs_vgs.py         existing CSV plotter (output format reference)
Routines/                  lab routine CSVs. The nMOS file contains 2
                           routines; index 0 = "Output WO Bulk" (sweep=Vd,
                           step=Vg). [CROSS-CHECK names/params by loading it]
instrument_list.yaml       serial ports + roles for Keithley 2400 (sources
                           Vd, measures Id) and E3631A (Vg, Vb). Ports drift;
                           human maintains this file.
Arduino/sketch_may26_r4_copy_*/   THE authoritative sketch. Contains working
                           resetScanChain(), setScanAddress(flavor,row,col),
                           shiftScanChain(), latchScanConfig(),
                           configureDevice(flavor,row,col) [does all of the
                           above + prints a verification report], and
                           timingTest(). setup() currently hardcodes
                           configureDevice(1,0,14) then traps in while(true).
Arduino/lbl_arduino_board_*/      DO NOT USE — its own header says the pins
                           are all wrong.
```

### 3.1 Arduino pin map — the ACTIVE defines of the r4 sketch [CROSS-CHECK]
Supdate=2, Srst=3, Sclkp=4, Sclkn=5, Senable=6, Sin=7, Sout(digital)=8,
Sout_chip2=9, **Sout ANALOG = A1** (moved from A0 in older sketches — trap!).
Traps: the same file carries a commented-out LEGACY pin block (Sin=2…Srst=7,
analog A0) — never copy it.

### 3.2 Polarities [CROSS-CHECK against sketch function bodies]
- Srst: ACTIVE HIGH (pulse HIGH then LOW; idles LOW).
- Senable: ACTIVE LOW at the board level (idle HIGH = disabled, driven LOW
  while shifting). NOTE: the datasheet prose says "retain Senable HIGH" —
  a known document-vs-bench conflict; the working sketch wins.
- Sout is read via analogRead against a threshold (~100–300 ADC counts
  historically) because the chip's Sout drive is too weak for digital reads.

════════════════════════════════════════════════════════════════════════════
## 4. CRITICAL QUIRKS — ENCODE THESE, DO NOT "FIX" THEM

**Q1. The verification false-failure (most important).** The sketch's
verification compares Sout to Sin in the SAME clock cycle of a single load
pass. What exits during loading is the chain's PREVIOUS contents (zeros after
reset), so a PERFECTLY HEALTHY chain reports exactly 2 "mismatches" (the two
one-hot bits) and prints "Test Failed". Therefore: (a) NEVER gate on the
sketch's "Test Passed/Failed" strings; (b) parse the `Mismatches: N` line;
(c) 2 = perfect; small excess = tolerable (see Q2); large = real fault.
Do NOT edit the sketch's verification — interpret it correctly in Python.

**Q2. Bench reality: this chain reads 3.** Measured July 2026: repeated
`SEL 3 0 0` yields Mismatches: 3 — one spurious bit beyond the two phantoms,
attributed to the weak-Sout analog read hovering near threshold. Python
tolerance should be `mismatches > 4 → abort`, with a dated comment. Root-
cause fix (optional, human decision): tune the ADC threshold constant in the
sketch. Mismatch count only tests the READ-BACK path; correct selection is
proven by measuring a real transistor (see test ladder).

**Q3. Vg–vdda short: ABSENT on this chip.** The datasheet §4.1 documents a
Vg-shorted-to-vdda erratum for the ORIGINAL design. Bench continuity check
(July 2026): NO short on the modified chip. Therefore Vg is swept directly
and normal biasing applies. If you read §4.1 in the datasheet, do NOT build
workarounds for it.

**Q4. Native array bounds.** Flavor 4 has 14 columns (0–13), not 25.
Validate device lists against this before any run.

**Q5. Serial port is single-occupancy.** Arduino IDE Serial Monitor, and any
Python script — only ONE may hold the port. Windows reassigns COM numbers
after replug. Scripts must take the port as a CLI argument, never hardcode.

**Q6. Arduino auto-reset on port-open is unreliable.** Some boards/drivers
don't reset when the port opens, so a boot banner may never be seen by the
script. Robust open = pulse DTR to request reset → wait briefly for a READY
banner → fall back to PING/PONG liveness check. Never treat "no banner" as
failure by itself.

**Q7. vgxp/vgxn slow ramp.** The existing routines ramp these over ~10 s
deliberately. It lives inside run_single_routine_from_csv — reusing that
function preserves it automatically. Never bypass.

**Q8. Warm-measurement expectations** (for validating output): output-family
curves (Id vs Vd, stepped Vg) should fan, rise linearly then saturate,
µA-to-tens-of-µA scale for mid-geometry NMOS at 300 K. All-flat-at-nA =
nothing selected (leakage floor). Pinned at one value = compliance limit,
not physics. Flavor Vth ladder at fixed geometry: ulVt < lVt < mid < hVt,
~100–150 mV spacing. Warm subthreshold ~80–90 mV/dec (not the near-vertical
cryo curves in papers). Self-heating: wide devices drift between dense back-
to-back warm sweeps; a short pause beats blaming instruments.

════════════════════════════════════════════════════════════════════════════
## 5. BENCH LOG (measured facts, July 2026)
- Vg↔vdda continuity: NO short (unpowered multimeter). → Q3.
- SEL-patched sketch flashed and answering; `SEL 3 0 0` completes with
  Mismatches: 3, ~25 ms full-chain shift (~74 µs/bit). → Q2.
- Arduino on COM11 as of last session (verify — see Q5).
- Python env: repo-root `.venv` (Windows), packages pyserial, matplotlib,
  pyyaml installed. Activate: `.\.venv\Scripts\activate`.

════════════════════════════════════════════════════════════════════════════
## 6. DELIVERABLES (the minimalist architecture — refine, don't replace)

A prior session validated this exact shape; your job is to plan it in depth,
re-derive and cross-check every hardware detail, and produce final code.

**D1. `Arduino/sketch_may26_r4_SEL/sketch_may26_r4_SEL.ino`** — a COPY of
the r4 sketch with exactly two edits (mark each `// PATCH`):
  (a) setup(): replace `configureDevice(1,0,14); while(true){}` with
      `Serial.println(F("READY"));`
  (b) loop(): line parser for `SEL <flavor> <row> <col>` → call the original
      configureDevice() unchanged → print `SEL_DONE`; `PING` → `PONG`;
      unknown → `ERR unknown cmd: <text>`.
  Nothing else changes: pins, timing, scan functions byte-identical.
  Folder name must equal sketch name (Arduino IDE requirement). 115200 baud
  (match the sketch's existing Serial.begin).

**D2. `run_device_loop.py`** (repo root) — the loop:
  - CLI: --devices CSV(flavor,row,col) --routines <path> --routine-index N
    [N…] --scan-port PORT --config instrument_list.yaml --out DIR.
  - Robust port open per Q6; select via SEL, parse Mismatches (accept ≤4 per
    Q2, cite bench log), wait for SEL_DONE (≥30 s timeout — the report
    prints 344 per-bit lines).
  - Per (device × routine): SKIP if output CSV exists (resume mechanism;
    document its partial-file blind spot: after a crash, delete newest CSV).
  - Measure via run_single_routine_from_csv, persist via
    write_routine_measurements_csv — both imported, unmodified, using the
    same `sys.path.insert(0, "src")` shim as run_routine.py.
  - Render one PNG per routine: two panels, linear + log10(|Id|+1e-15),
    one curve per step value, matplotlib "Agg" backend (headless overnight).
  - try/except per device → write `<routine>.FAILED.txt` with the error,
    continue. Final summary line: `N done, M skipped, K failed`.
  - Output layout: `data/<run>/<flavorname>_r<row>c<col>/<routine>.csv|.png`
    with flavor names from §2.1's table.
  - Device-list bounds validation per Q4, with file:line in errors.

**D3. `test_scan_link.py`** (repo root) — 60-second pre-flight, no
instruments: robust open (Q6) → PING → `SEL 3 0 0` graded per Q1/Q2 →
`SEL 3 0 1` (proves re-selection, the property the loop depends on). Every
failure message names the most likely causes in order.

**D4. `devices_example.csv`** + documented one-liners to generate one block
(150) and the full chip (1,584, respecting Q4).

════════════════════════════════════════════════════════════════════════════
## 7. YOUR WORKFLOW — PLAN EXTENSIVELY BEFORE WRITING CODE

**Phase A — Ingest and cross-check (produce `PLAN.md` before any code):**
1. Read, in this order: the r4 sketch (fully — extract TOTAL_BITS,
   flavor_base[], pin defines, polarities, configureDevice's exact report
   format including the `Mismatches:` line and per-bit output);
   `src/iv_measure/routines.py` (exact signatures + RoutineMeasurement
   fields); `run_routine.py` (style + import shim); the routine CSVs (load
   them, list names/params); `instrument_list.yaml`.
2. If the datasheet PDF is present in the repo (ask the human to drop it in
   `docs/` if not), read it and cross-check §2.2 geometry and §2.3 pad facts
   above. Remember §1's hierarchy: the datasheet's CHAIN MAP (472 bits) and
   §4.1 erratum do NOT apply to this chip — if you find them, that is
   expected, not a discovery.
3. Produce a DISCREPANCY TABLE: every fact in this brief vs. what you found
   in the primary sources. Any mismatch = stop and surface it to the human
   before proceeding. (Expected result: zero mismatches; the table's value
   is proving you checked.)
4. Write `PLAN.md`: file-by-file design, exact functions reused vs. created,
   the serial protocol spec, error-handling matrix, the resume semantics and
   their limits, and a time-budget model (measured ~25 ms/SEL + routine
   sweep time × device count) for the overnight run.

**Phase B — Implement** (only after the human approves PLAN.md): write D1–D4.
Syntax-check everything; for D2/D3, unit-exercise the non-hardware parts
(device-list parsing incl. Q4 rejection; plot rendering from synthetic
RoutineMeasurement points; the Mismatches-line parser against a pasted real
report from §5's format).

**Phase C — Hand back a test ladder** (do not invent your own ordering; this
one isolates one subsystem per rung): (0) deps + files-on-disk check;
(1) `test_scan_link.py` twice — identical results required; (2) one device,
one routine, human grades the PNG per Q8; (3) rerun identical command →
`0 done, 1 skipped`; (4) ten devices (row 0 of nmos_mid: expect Id to FALL
with column 0→6 as L grows, RISE across 7→9 as nf grows — scrambled ordering
means selection isn't landing where labels claim: STOP); (5) overnight,
budgeted from rung-4 timing, morning triage = grep FAILED files, flavor-
ladder spot check per Q8.

**Standing rules:** never run hardware-touching commands yourself unless the
human explicitly says the bench is live and monitors it; when uncertain
about any hardware fact, the answer is "check the primary source or ask,"
never "assume"; every tolerance or magic number you write gets a comment
citing its source (sketch line, datasheet section, or bench-log entry).
