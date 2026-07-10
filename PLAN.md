# PLAN.md — Implementation plan for D1–D4 (overnight IV-characterization automation)

This plan is file-by-file, cites a source for every number, and specifies the
serial protocol, error matrix, resume semantics, and overnight time budget.

> **STATUS: Phase B implemented and non-hardware-validated (2026-07-10).** D-1 was
> resolved (routines CSV reverted). Delivered/finalized: `scan_link.py` (new, shared
> protocol), `run_device_loop.py` (rewritten: shared helpers, `--limit`,
> `--ids-settle-s`, `--mismatch-abort`, traceback-in-FAILED, mismatch tol fixed 2→4),
> `test_scan_link.py` (rewritten onto `scan_link.py`), `devices_example.csv` (rung-4
> 10-device set), and `Arduino/sketch_may26_r4_SEL/sketch_may26_r4_SEL.ino` (byte-exact
> copy + exactly two `// PATCH` hunks, diff-verified). All non-hardware checks pass
> (device-list Q4 rejection, plot render, Mismatches parser 2/3/5, CLI guards). Nothing
> in `src/`, the routine CSVs, `instrument_list.yaml`, or the original sketches was
> touched. **Next: the hardware test ladder (§Phase C) — bench must be live, human-run.**

> **Standing note — prior-session files already exist.** `run_device_loop.py`,
> `test_scan_link.py`, and `devices_example.csv` are already committed at their D2/D3/D4
> target paths (a prior session produced them). This plan treats Phase B as *reviewing
> and finalizing* those files against this design + the cross-checked facts, not writing
> greenfield. Any change stays inside those NEW files; **zero** edits to `src/iv_measure/`,
> the routine CSVs, `instrument_list.yaml`, or the original Arduino sketches (§PRIME).
> Where this plan and an existing file disagree, I will surface the diff for approval,
> not silently overwrite.

---

## Resolved decisions (human, this session)

- **D-1 (routines CSV):** RESOLVED. File reverted to committed `HEAD` (2 nMOS routines,
  index 0 = "Output WO Bulk", positive polarity) via `git checkout HEAD --`. The 3rd
  "PMOS WO Bulk" row and the negative-polarity index-0 edit were failed PMOS experiments
  and are gone. Routine-index space is **0..1**.
- **PMOS is an open problem:** PMOS characterization on this rig is not yet validated (the
  reverted experiments were PMOS attempts that "didn't work"). The device list may still
  contain PMOS flavors 7–11, but there is no proven PMOS routine — treat PMOS output as
  unvalidated and do not let a PMOS device silently masquerade as a passing nMOS-style run.
- **Serial helper (Q2 of Phase A):** NEW `scan_link.py` at repo root holds the shared
  protocol; both `run_device_loop.py` and `test_scan_link.py` import it. (5 new files total.)
- **Routine scope:** `--routine-index` stays an explicit CLI arg with **no baked-in default**;
  scope chosen at launch after rung-4 timing. The loop is the unattended batch characterizer.
- **NEW — `--limit N` (a.k.a. `--max-devices`):** run at most N devices *per invocation*,
  counting only devices actually **run** (skips due to existing CSV do NOT count). Lets the
  user test in short intervals and, combined with resume, walk a 150-device block N-at-a-time
  across many short sessions. `--limit 1` = single-device smoke test; `--limit 10` = rung-4
  ten-device check; omitted = whole list (overnight).

---

## 0. Reused-verbatim vs. new code

**Imported and called, never edited** (all from `src/iv_measure/`, cited in DISCREPANCIES §3):
- `config.load_project_config(path)` — `config.py:55`
- `routines.run_single_routine_from_csv(config, routines_csv, routine_index, ids_settle_s=…)` — `routines.py:170`
  (this carries the init-bias sequence, the ~10 s vgx ramp per Q7/`routines.py:220`, the
  step/sweep loops, and the Keithley reads — reusing it preserves all of that)
- `routines.write_routine_measurements_csv(path, points)` — `routines.py:304`
- `routines.load_routines_csv(path)` — `routines.py:59` (for index-range validation only)
- `routines.RoutineMeasurement` dataclass — `routines.py:41` (read `.step_value_v`,
  `.sweep_value_v`, `.drain_i_a` for plotting)

**Import shim (copied exactly from `run_routine.py:18–19`, the absolute-path form — not the
literal `"src"` string; see DISCREPANCIES Note 3-a):**
```python
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))
```

**New code (all at repo root, in the four deliverable files only):** the SEL sketch
(D1), the device loop + serial driver + plotting (D2), the pre-flight (D3), and the
device-list examples/generators (D4). No new files anywhere else.

---

## D1 — `Arduino/sketch_may26_r4_SEL/sketch_may26_r4_SEL.ino`

A **byte-for-byte copy** of `sketch_may26_r4_copy_20260609150247.ino` with **exactly two
edits**, each marked `// PATCH`. Everything else — pins (§3.1), `threshold=100`
(sketch:31), `TOTAL_BITS=344` (sketch:34), `flavor_base[]` (sketch:40–51), the clock
timing (sketch:119–128), `configureDevice`, `shiftScanChain`, the `Mismatches:` report —
stays identical. Folder name == sketch name (Arduino IDE requirement, §D1). Baud stays
**115200** (sketch:265).

**PATCH (a) — `setup()` tail.** Replace the hardcoded selection + trap
(`timingTest(200); configureDevice(1,0,14); while(true){}`, sketch:275–280) with a
readiness banner:
```cpp
Serial.println(F("READY"));   // PATCH: replaces timingTest + configureDevice(1,0,14) + while(true)
```
Rationale: the original `timingTest` and hardcoded device select are bench-bring-up
scaffolding; the loop needs a live command interface, and Q6 wants a banner to sync on.
`start` (sketch:267) is left as-is; `READY` is the new sync token D2/D3 wait for.

**PATCH (b) — `loop()` body.** Replace empty `loop()` (sketch:283) with a line parser:
```cpp
void loop() {                                              // PATCH: command interface
  static String line;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      line.trim();
      if (line.length() == 0) { /* ignore blank */ }
      else if (line == "PING") Serial.println(F("PONG"));
      else if (line.startsWith("SEL ")) {
        int f, r, col;
        if (sscanf(line.c_str() + 4, "%d %d %d", &f, &r, &col) == 3) {
          configureDevice(f, r, col);        // ORIGINAL function, unchanged
          Serial.println(F("SEL_DONE"));
        } else {
          Serial.print(F("ERR bad SEL args: ")); Serial.println(line);
        }
      } else {
        Serial.print(F("ERR unknown cmd: ")); Serial.println(line);
      }
      line = "";
    } else {
      line += c;
    }
  }
}
```
`configureDevice` is called **unmodified**; it does reset→set→shift→latch and prints its
own report ending in `Mismatches: N` then `Test Passed/Failed`. The Python side reads
`SEL_DONE` as the terminator (it prints *after* the report). Bounds are still enforced
inside `setScanAddress` (sketch:81–86) — an out-of-range SEL prints `Invalid flavor/row/col`
but the sketch still emits its report + `SEL_DONE`; D2 also pre-validates (Q4) so bad rows
never reach the wire.

**Explicitly NOT changed:** the commented LEGACY pin block (sketch:10–18 — the A0 trap),
`PIN_SOUT_ANALOG A1`, the clock delays, the verification comparison (Q1 — interpreted in
Python, never "fixed" in the sketch).

---

## D2 — `run_device_loop.py` (repo root)

### CLI (per §D2)
```
--devices <csv>            columns: flavor,row,col
--routines <path>          routines CSV (default: the nMOS file)
--routine-index N [N ...]  one or more 0-based indices (index space is 0..1 after D-1 revert);
                           explicit, no baked-in default — scope chosen at launch time
--scan-port PORT           Arduino COM port (REQUIRED; never hardcoded — Q5)
--config instrument_list.yaml
--out DIR                  run output root (default data/<run>)
--ids-settle-s             default 1.0 (matches run_routine.py:235)
--mismatch-abort           default 4 (Q2 bench log; documented magic number)
--limit N                  (a.k.a. --max-devices) run at most N devices this invocation;
                           counts only devices actually RUN, not skipped-by-resume; omit = all
```

### Control flow
1. Parse `--devices`; **validate bounds before opening anything** (Q4): flavor∈1..11,
   row∈0..5, col∈0..(14 if flavor==4 else 25)−1. On violation, raise with the offending
   `devices.csv:<line>` and the rule cited. (Bounds mirror `setScanAddress`, sketch:81–86.)
2. Open the scan port robustly (Q6 — see protocol below).
3. `config = load_project_config(--config)`; `load_routines_csv(--routines)` once to
   validate every `--routine-index` is in range (reuses `routines.py:59`).
4. For each device × each routine index (stop early once `--limit` devices have been RUN):
   - Compute output paths (layout below). **If the `.csv` exists → SKIP** (resume, §D2).
     A skip does NOT increment the `--limit` counter — only a device that actually runs a
     routine does. This makes `--limit 10` reliably measure 10 fresh devices regardless of
     how many are already complete, so repeated short sessions walk the block N-at-a-time.
   - `SEL <flavor> <row> <col>` → parse `Mismatches:` → grade (Q1/Q2) → wait `SEL_DONE`.
   - `spec, points = run_single_routine_from_csv(config, --routines, index, ids_settle_s=…)`
     (reused verbatim — carries the vgx ramp, Q7).
   - `write_routine_measurements_csv(csv_path, points)` (reused verbatim).
   - Render PNG (below).
   - Wrap each device×routine in try/except → on failure write `<routine>.FAILED.txt`
     with the exception text + traceback, then continue.
5. Print final summary: `N done, M skipped, K failed` (§D2).

### Output layout (§D2)
```
data/<run>/<flavorname>_r<row>c<col>/<routine>.csv
data/<run>/<flavorname>_r<row>c<col>/<routine>.png
data/<run>/<flavorname>_r<row>c<col>/<routine>.FAILED.txt   (only on error)
```
`<flavorname>` from the §2.1 table (flavor 11 → **`pmos_lvt_b`**, DISCREPANCIES Note 2.1-a,
to avoid colliding with flavor 8's `pmos_lvt`). `<routine>` = the routine name with
filesystem-unsafe chars replaced. `<run>` = a run label; **must be passed in / derived
deterministically, not from wallclock inside a workflow**, but in a normal CLI run a
timestamped default is fine.

### PNG rendering (§D2)
- `matplotlib.use("Agg")` set **before** importing pyplot (headless overnight, §D2).
- Two panels: left linear `Id` vs sweep param; right `log10(|Id| + 1e-15)` vs sweep param
  (the `1e-15` floor is the §D2-specified epsilon — cite inline).
- One curve per **step value** (`RoutineMeasurement.step_value_v`); x = `sweep_value_v`,
  y = `drain_i_a`. Title includes flavor name, r/c, routine, sweep/step params.
- Plot from the in-memory `points` list; no re-read of the CSV. Follows the two-panel
  linear+log style already in `run_routine.py:27–99` (reference, not imported — that
  class is live/interactive; D2 needs static Agg saves).

### New helper module boundary
All serial logic (open, `sel()`, `ping()`, mismatch parse, `SEL_DONE` wait) lives as
functions **inside `run_device_loop.py`** and is **imported by `test_scan_link.py`** so the
protocol has one implementation. (If cleaner, a single new `scan_link.py` at repo root is
acceptable — still a NEW file; I'll confirm the split with you in Phase B rather than
assume.)

---

## Serial protocol spec (D1 ⇄ D2/D3)

- **Link:** 115200 8N1 (sketch:265), `\n`-terminated commands, newline-delimited replies.
- **Open sequence (Q6):** open port → pulse **DTR** low→high to request reset → read lines
  for up to ~3 s looking for `READY` (D1 PATCH-a) or the older `start` banner → **fallback:**
  send `PING`, expect `PONG` within a short timeout. "No banner" alone is **not** failure
  (Q6). Give the board ~2 s post-open settle before the DTR pulse, mirroring
  `run_routine.py`'s port-reset pauses (`run_routine.py:113,270`).
- **Commands → replies:**

  | Command | Arduino replies (in order) | Terminator D2 waits for |
  |---|---|---|
  | `PING` | `PONG` | `PONG` |
  | `SEL <f> <r> <c>` | `configureDevice` report incl. `=== Scan shift results ===`, `Mismatches: N`, `Test Passed/Failed`, then `SEL_DONE` | **`SEL_DONE`** |
  | `<junk>` | `ERR unknown cmd: <text>` | `ERR …` |

- **`SEL_DONE` timeout ≥ 30 s** (§D2): the report prints one line per bit (344 lines,
  `shiftScanChain` lines 149–158) plus the summary — at 115200 baud that is well under a
  second, but 30 s gives margin for a slow/renumbered port. Cite: §D2 + sketch:150.
- **Mismatch grading (Q1/Q2):** parse the integer on the `Mismatches:` line (sketch:231).
  `2` = perfect (two one-hot phantom bits, Q1). `3` = the July-2026 bench norm (Q2, §5).
  **`> 4` → abort** that device with a FAILED file (Q2). Never key on `Test Passed/Failed`
  (Q1). Threshold constant gets an inline comment citing the §5 bench log.

---

## Error-handling matrix

| Condition | Detection | Action | Source |
|---|---|---|---|
| Bad device row (flavor/row/col out of range) | pre-flight validation | abort run, message names `devices.csv:<line>` + rule | Q4, sketch:81–86 |
| Native col ≥ 14 | same | same | Q4 |
| Port won't open / wrong COM | `serial.Serial()` raises | abort run, message: "check --scan-port; Windows renumbers COMs after replug" | Q5 |
| No banner after open | timeout on READY/start | **not fatal** → try PING/PONG | Q6 |
| No PONG either | PING timeout | abort run: "Arduino not responding — check power, port, that no Serial Monitor holds the port" | Q5/Q6 |
| `Mismatches` = 3 | parse | proceed (tolerated) | Q2 |
| `Mismatches` > 4 | parse | skip device → FAILED file: "readback path suspect; check Sout analog / threshold" | Q2 |
| `SEL_DONE` not seen in 30 s | timeout | FAILED file for that device×routine, continue | §D2 |
| Instrument/measurement raises mid-routine | try/except around `run_single_routine_from_csv` | FAILED file w/ traceback, continue to next device | §D2 |
| Output `.csv` already present | `path.exists()` | SKIP (count as skipped) | §D2 resume |
| Bad `--routine-index` | `load_routines_csv` len check | abort before any hardware | routines.py:179 |

The `run_single_routine_from_csv` `finally` block (routines.py:275–281) already ramps
controls to zero and closes instruments on any exit — so a per-device exception leaves the
rails safe without D2 doing teardown itself.

---

## Resume semantics and their documented limit

- **Mechanism:** a device×routine is skipped iff its output `.csv` already exists (§D2).
  Re-running the identical command after a partial overnight run continues where it stopped.
- **Blind spot (must be documented in D2's header + `--help`, per §D2):** the CSV is written
  by `write_routine_measurements_csv` **only after the routine fully completes**
  (routines.py:283 returns, then D2 writes). So a crash *mid-routine* leaves **no** CSV and
  that device re-runs cleanly — good. But if the process is killed *between* `write_…_csv`
  finishing and the next step, the newest CSV could in principle be short/partial only if
  the write itself was interrupted. **Documented remedy (§D2): after any crash, delete the
  single newest CSV before resuming.** The PNG is regenerated from `points` each run, so a
  missing/stale PNG next to a present CSV is not re-created on resume — noted as a known
  minor limit (a `--force-plots` flag is an optional Phase-B nicety, not required).

---

## Tolerances / magic numbers (every one cited)

| Value | Meaning | Source |
|---|---|---|
| `mismatch_abort = 4` (abort if `> 4`) | readback-path health gate | Q2 / §5 bench log (reads 3; 2 phantoms per Q1) |
| `SEL_DONE` timeout `30 s` | wait for 344-line report + summary | §D2; sketch:150 (344 lines) |
| open/READY wait `~3 s`, post-open settle `~2 s` | Q6 robust open | Q6; pattern from run_routine.py:113,270 |
| log-panel epsilon `1e-15` | `log10(|Id|+1e-15)` floor | §D2 |
| `ids_settle_s = 1.0` default | per-point settle | run_routine.py:235 |
| vgx ramp `10 s / 40 steps` | leakage-rail slow ramp | **not set by D2** — inherited from routines.py:220 (Q7); never bypassed |
| threshold `100` ADC counts | Sout analog read | sketch:31 (in D1, unchanged) |

---

## Overnight time-budget model

Per-point wall time ≈ `ids_settle_s` (1.0 s, run_routine.py:235) + per-point SCPI set/measure
overhead. Fixed per-routine overhead ≈ the ~10 s vgx ramp (routines.py:220, Q7) + initial
non-vgx settle(s) (`settle_s`, config default 0.5 s, config.py:88) ≈ **~12 s**. Per-SEL scan
≈ **25 ms** (§5 bench log; ~74 µs/bit × 344) — negligible vs. the sweep.

**Point counts (from the working-tree routines CSV — SUBJECT TO D-1):**
| idx | routine | sweep pts | step pts | points | est. time/device @1.0 s + 12 s |
|---|---|---|---|---|---|
| 0 | Output WO Bulk | 30 | 6 | 180 | ~180 s + 12 s ≈ **3.2 min** |
| 1 | Accumulation to Inversion | 30 | 10 | 300 | ~300 s + 12 s ≈ **5.2 min** |
| 2 | PMOS WO Bulk | 30 | 6 | 180 | ~3.2 min |

- **One block (150 devices), index-0 only:** 150 × ~3.2 min ≈ **8.0 h**.
- **One block, indices 0+1:** 150 × ~8.4 min ≈ **21 h** (too long for one night — pick
  indices per D-1).
- **Full chip (1,584 devices), index-0 only:** 1,584 × ~3.2 min ≈ **84 h** (multi-night).

**Implication:** an overnight run is realistically **one block, one routine index**, or a
**sub-list**. The time model is linear in device count × (points × settle + ~12 s), so the
rung-4 ten-device timing (test ladder) gives an empirical constant to re-scale before
committing to a full night. If `ids_settle_s` can be safely reduced after rung-2 grading,
the budget scales down proportionally. **These numbers move if D-1 changes the routine set.**

---

## D3 — `test_scan_link.py` (repo root) — 60-second pre-flight, no instruments

- Robust open (Q6): DTR pulse → READY/start wait → PING/PONG fallback.
- `PING` → expect `PONG`.
- `SEL 3 0 0` → grade `Mismatches` per Q1/Q2 (2 ideal, 3 bench-normal, >4 fail).
- `SEL 3 0 1` → proves **re-selection** works (the property the loop depends on) — grade again.
- Every failure message names likely causes **in order** (§D3): e.g. for no-response →
  (1) no power / wrong `--scan-port`, (2) Serial Monitor holding the port (Q5),
  (3) board didn't reset (Q6); for high mismatch → (1) Sout analog threshold, (2) wiring.
- CLI: `--scan-port PORT` (required, Q5). Imports the shared serial helpers from D2 so the
  open/SEL/parse logic is identical to the overnight loop.

---

## D4 — `devices_example.csv` + generator one-liners

- `devices_example.csv` (exists): header `flavor,row,col` + a few sample rows.
- **Documented one-liners** (in README-style comments or the file header, generating to
  stdout — I will confirm placement in Phase B):
  - One block (nmos_mid = flavor 3, 150 devices):
    `python -c "print('flavor,row,col'); [print(f'3,{r},{c}') for r in range(6) for c in range(25)]"`
  - Full chip (1,584, honoring Q4 native=14 cols):
    `python -c "print('flavor,row,col'); [print(f'{f},{r},{c}') for f in range(1,12) for r in range(6) for c in range(14 if f==4 else 25)]"`
  - These respect flavor 4 = 14 cols (Q4) and produce exactly 10×150+84 = 1,584 rows (§2.1).

---

## Phase-B validation (non-hardware, per §Phase B) — planned, not yet run

- **Device-list parsing incl. Q4 rejection:** feed a native-col-14 row, assert it's rejected
  with a `devices.csv:<line>` message.
- **Plot rendering from synthetic `RoutineMeasurement` points:** build a fake output family,
  render the two-panel PNG under Agg, assert file exists and has ≥1 curve per step value.
- **`Mismatches:` parser** against a pasted real report in §5's exact format (`Mismatches: 3`).
- **Syntax-check** all Python; the `.ino` gets a visual diff vs. the r4 sketch showing exactly
  two `// PATCH` hunks.

---

## Open questions — all RESOLVED (2026-07-10)

1. **D-1 (routines CSV):** RESOLVED — reverted to committed `HEAD` (2 nMOS routines,
   index 0 positive). Index space is 0..1. PMOS left as an open problem (no valid routine).
2. **Helper split:** RESOLVED — new `scan_link.py`, imported by both scripts.
3. **Existing D2/D3/D4 files:** RESOLVED — finalized in place (edited), diffs surfaced.

═══════════════════════════════════════════════════════════════════════════════

# WHAT'S NEXT — Phase C hardware test ladder (human-run, live bench)

**Nothing below has been run.** All of it requires the physical bench and must be
driven by a human who is watching it (CLAUDE.md standing rule: never run
hardware-touching commands unless the human says the bench is live and monitors it).
The ladder isolates ONE subsystem per rung — do not skip or reorder. If a rung fails,
STOP at that rung; do not proceed to the next.

Assumed environment each session: repo-root `.venv` active
(`.\.venv\Scripts\activate`), chip powered on the manual bench supply (0.9 V core /
1.8 V I/O per `instrument_list.yaml` lines 32–33), and you know the Arduino's current
COM port (Windows renumbers after replug — Q5; `COM11` as of the last session, §5).
Placeholders below: `<PORT>` = scan Arduino port, `<RUN>` = an output dir you choose.

---

### Rung 0 — Deps + files-on-disk check (no hardware)
**Do:**
```
.\.venv\Scripts\python -c "import serial, matplotlib, yaml; print('deps ok')"
```
Confirm these exist: `scan_link.py`, `run_device_loop.py`, `test_scan_link.py`,
`devices_example.csv`, `Arduino/sketch_may26_r4_SEL/sketch_may26_r4_SEL.ino`.
**Pass:** `deps ok` prints; all five files present.
**Stop if:** any import fails → `pip install -r requirements.txt` in the venv.

### Rung 0.5 — Flash the SEL sketch (one-time per board)
**Do:** open `Arduino/sketch_may26_r4_SEL/sketch_may26_r4_SEL.ino` in the Arduino IDE,
select the correct board/port, **Upload**. Then **close the Serial Monitor** (serial
port is single-occupancy — Q5; a Python script and the Monitor cannot both hold it).
**Pass:** compiles and uploads clean.
**Stop if:** it won't compile → you edited the wrong file; re-copy from the r4 sketch
(the SEL sketch must differ from the original by exactly the two `// PATCH` hunks —
verify with `diff` against `Arduino/sketch_may26_r4_copy_20260609150247/…`).

### Rung 1 — Scan link pre-flight, run TWICE (no instruments)
Chip powered, instruments may be off. This tests ONLY the scan-chain read-back path.
**Do (twice):**
```
.\.venv\Scripts\python test_scan_link.py --scan-port <PORT>
```
**Pass:** exit code 0 both times, with **identical** grading both runs. Expected:
`READY` seen (or PING/PONG fallback), `PONG`, then `SEL 3 0 0` and `SEL 3 0 1` each
reporting **Mismatches = 2 or 3** (2 = ideal per Q1; 3 = July-2026 bench norm per Q2).
**Stop if:** Mismatches > 4 (real read-back fault → check Sout analog threshold
sketch:31, wiring, chip power); or the two runs disagree (intermittent link → reseat,
check power rails); or no READY *and* no PONG (wrong port / Monitor holding it / old
firmware still flashed — the error message lists these in order).

### Rung 2 — One device, one routine (instruments live) → HUMAN grades the PNG
Bench fully live: Keithley 2400 + E3631A on the ports in `instrument_list.yaml`.
**Do:**
```
.\.venv\Scripts\python run_device_loop.py ^
    --devices devices_example.csv ^
    --routines "Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv" ^
    --routine-index 0 ^
    --scan-port <PORT> ^
    --out data/<RUN> ^
    --limit 1
```
(`--limit 1` measures just the first device, `nmos_mid_r0c0`.)
**Pass:** summary `1 done, 0 skipped, 0 failed`; a CSV + PNG appear under
`data/<RUN>/nmos_mid_r0c0/`. **Human grades the PNG against Q8:** an Id–Vd output
family should fan with Vg, rise linearly then saturate, µA-to-tens-of-µA scale for
mid-geometry NMOS at 300 K.
**Stop if:** all curves flat at nA (nothing selected — leakage floor; selection not
landing); pinned at one value (compliance limit, not physics); wrong sign/shape
(check routine polarity and that the DUT is really NMOS).

### Rung 3 — Resume check (re-run the identical command)
**Do:** re-run the **exact** Rung-2 command (same `--out`, `--limit 1`).
**Pass:** summary reports the device **skipped** (its CSV already exists) — i.e.
`0 done, 1 skipped, 0 failed`, or it advances past the done device. Proves resume works.
**Stop if:** it re-measures the done device (resume/skip logic broken).

### Rung 4 — Ten devices, monotonicity spot-check
`devices_example.csv` is exactly this set: nmos_mid (flavor 3) row 0, cols 0–9.
**Do:**
```
.\.venv\Scripts\python run_device_loop.py ^
    --devices devices_example.csv ^
    --routines "Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv" ^
    --routine-index 0 --scan-port <PORT> --out data/<RUN> --limit 10
```
(Rung-2's device is skipped; this fills in the other 9. Note the wall-clock — that is
your empirical per-device time for the Rung-5 budget.)
**Pass:** across cols **0→6** Id should **fall** as L grows (30→1000 nm); across cols
**7→9** Id should **rise** as nf grows (nf=2,4,8 at L=30 nm) — geometry per §2.2.
**Stop if:** the ordering is scrambled — selection is NOT landing where the labels
claim, so no overnight run is trustworthy. Debug selection before proceeding.

### Rung 5 — Overnight run (budgeted from Rung-4 timing)
Build the device list for the scope you want, then launch. Examples:
```
:: one full nMOS block (flavor 3 = nmos_mid, 150 devices)
.\.venv\Scripts\python -c "print('flavor,row,col'); [print(f'3,{r},{c}') for r in range(6) for c in range(25)]" > devices_block3.csv

:: whole chip (1,584 devices, honors native=14 cols — Q4)
.\.venv\Scripts\python -c "print('flavor,row,col'); [print(f'{f},{r},{c}') for f in range(1,12) for r in range(6) for c in range(14 if f==4 else 25)]" > devices_all.csv

.\.venv\Scripts\python run_device_loop.py ^
    --devices devices_block3.csv ^
    --routines "Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv" ^
    --routine-index 0 --scan-port <PORT> --out data/<RUN>
```
**Budget (re-scale with Rung-4's measured per-device time):** at ~3.2 min/device
(index 0, 180 pts × 1.0 s + ~12 s), one block ≈ **8 h**, whole chip index-0 ≈ **84 h**
(multi-night). Pick a scope that fits your window; use `--limit` to cap a session.
**Morning triage:** `grep -rl "" data/<RUN>/**/*.FAILED.txt` to find failures; then a
flavor-ladder spot check per Q8 (ulVt < lVt < mid < hVt, ~100–150 mV Vth spacing).
**Interruption recovery:** re-run the same command — done devices are skipped. If the
process was killed mid-write, delete the single newest CSV first (resume blind spot,
documented in `run_device_loop.py`).

---

## Deferred / not in scope for the current code (revisit when needed)
- **PMOS characterization (flavors 7–11):** no validated routine exists (the reverted
  CSV edits were failed PMOS attempts). The loop can *select* a PMOS device but running
  an nMOS-polarity routine on it yields meaningless curves. This is a routine-CSV task
  (author a correct-polarity PMOS routine, human-owned), not a loop-code change.
- **`--force-plots`** (regenerate a PNG when the CSV exists but the PNG is stale/missing):
  optional nicety, not built — a done device is skipped entirely on resume.
- **ADC-threshold tuning** (sketch:31) to drive the bench Mismatches from 3 down to 2:
  optional, human decision, requires editing the sketch's `threshold` constant.
- **DNW `Vb` sweeps (flavor 6):** the only array with usable body bias; current routines
  don't exercise Vb meaningfully. Add a Vb-stepping routine if DNW body effect is wanted.
