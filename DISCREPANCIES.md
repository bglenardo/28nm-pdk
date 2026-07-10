# DISCREPANCIES.md — Phase A cross-check of CLAUDE.md against primary sources

Produced during Phase A (ingest & cross-check). **No code was written or run;
no repo files were modified; nothing touched the bench.** This document is the
evidence that every hardware fact in CLAUDE.md §2–§4 and §3 was verified against
the artifacts that actually run.

Primary sources read, in the CLAUDE.md-specified order:
- `Arduino/sketch_may26_r4_copy_20260609150247/sketch_may26_r4_copy_20260609150247.ino` (the r4 sketch)
- `src/iv_measure/routines.py`
- `run_routine.py`
- `Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv` (+ DEPRECATED sibling)
- `instrument_list.yaml`
- `src/iv_measure/config.py` (for `load_project_config` / `SweepConfig.settle_s` citations)
- `docs/28nm LDRD Device Array Datasheet (1).pdf` (extracted via `pdftotext -layout`
  to a scratch file outside the repo; line numbers below are that extraction's lines)

---

## ⚠️ ITEMS REQUIRING YOUR INPUT (read first)

### D-1 — The nMOS routines CSV has changed under CLAUDE.md's feet (needs a decision)

CLAUDE.md §3 states the nMOS routines file *"contains 2 routines; index 0 =
'Output WO Bulk' (sweep=Vd, step=Vg)."* The file on disk **right now** does not
match that, and `git status` shows it as **Modified** in the working tree — i.e.
you appear to be mid-edit.

| Property | CLAUDE.md §3 | Committed `HEAD` | Working tree (on disk now) |
|---|---|---|---|
| Routine count | 2 | 2 | **3** |
| Index 0 name | Output WO Bulk | Output WO Bulk | Output WO Bulk ✓ |
| Index 0 sweep / step param | Vd / Vg | Vd / Vg | Vd / Vg ✓ |
| Index 0 Sweep Stop | (n/s) | **+0.85** | **−0.85** |
| Index 0 Step Start→Stop | (n/s) | **+0.1 → +0.8** | **−0.1 → −0.8** |
| Index 2 | — | — | **"PMOS WO Bulk"** (new) |

Evidence:
- CLAUDE.md §3, "Routines/" paragraph.
- `git show HEAD:"Routines/…nMOS 28nm.csv"` → 2 data rows, index 0 positive.
- Working-tree file lines 2–4 → 3 data rows; index 0 now **negative** polarity;
  a third row "PMOS WO Bulk" added.

**Why this matters for the deliverables (not a code blocker, but a design input):**
- **D2 `--routine-index`**: the index space is now 0..2, not 0..1. Anything that
  documents "index 0/1" needs to say 0..2, and the overnight command must name the
  indices you actually want to run.
- **Q8 warm-expectation grading (test-ladder rungs 2 & 4)**: Q8 says an NMOS
  output family should have Id **rise** with positive Vd. Index-0 "Output WO Bulk"
  now sweeps Vd **0 → −0.85** with Vg stepped **−0.1 → −0.8** — that is a *PMOS-style*
  polarity on a routine whose name and the file title both say **nMOS**. If index 0
  is genuinely meant for NMOS devices, the negative polarity will read as "all flat"
  / wrong-sign and trip a false STOP at rung 2/4.

**Question for you:** Is the working-tree edit intentional and final (i.e. index 0
is now negative on purpose, and there are 3 routines), or is it in-progress? I will
not touch this file either way (§PRIME: routine CSVs are zero-modification, human-
maintained). I just need to know which routine indices the overnight loop should
target and whether the negative-polarity index 0 is expected, so the Q8 grading
guidance in PLAN.md and the test ladder don't fight your data. **Holding on this
before Phase B.**

*(Everything below cross-checked clean. The remaining "notes" are reconciliations
CLAUDE.md already anticipated, not conflicts.)*

---

## §2.1 — Scan chain (device-selection mechanism)

| CLAUDE.md fact | Primary source | Verdict |
|---|---|---|
| 344 bits total | sketch `const int TOTAL_BITS = 344;` (line 34) | ✅ match |
| 11 arrays, flavors 1–11 | sketch `FLAVOR_COUNT = 11`, `flavor_base[12]` (lines 38–52) | ✅ match |
| One-hot: exactly one row bit + one col bit | `setScanAddress` sets exactly `row_bit` and `col_bit` (lines 90–94) | ✅ match |
| bits [base..base+5] = en_row<0..5> | `row_bit = base + row`, `row < 6` validated (lines 82, 90) | ✅ match |
| bits [base+6 ..] = en_col | `col_bit = base + 6 + col` (line 93) | ✅ match |
| Base map 0,32,64,96,120,152,184,216,248,280,312 | `flavor_base[]` (lines 40–51) | ✅ exact |
| Native (flavor 4) = 14 cols; others 25 | `flavor_cols()` returns 14 if flavor==4 else 25 (lines 54–57) | ✅ match |
| Rows 0–5 everywhere | `row < 0 || row >= 6` reject (line 82) | ✅ match |
| Total devices 10×150 + 84 = 1,584 | 10 flavors × (6 rows × 25 cols)=150; native 6×14=84 → 1,584 | ✅ arithmetic checks |
| FIFO, highest index enters Sin first | `for (i = TOTAL_BITS-1; i>=0; i--) digitalWrite(PIN_SIN, bit i)` (lines 111–116) | ✅ match |
| Procedure: Srst → shift w/ two-phase Sclkp/Sclkn → Supdate latch | `configureDevice`: reset→set→shift→latch (lines 212–219); clocks lines 119–128 | ✅ match |
| No Supdate = DUT unchanged | datasheet Note (lines 282–283); latch is separate `latchScanConfig` (lines 162–166) | ✅ match |
| Original design 472 bits / 15 arrays (does NOT apply) | datasheet "global scan chain has 472 configuration bits" (line 320); "15 subarrays" (line 56) | ✅ present & expected — not this chip |

**Note 2.1-a (naming, not a conflict):** flavor 11's sketch comment says `pmos_lvt`
(line 51); CLAUDE.md §2.1 calls it **`pmos_lvt_b`** ("genuine second pmos_lvt").
These describe the same array. PLAN.md adopts `pmos_lvt_b` for output-directory
names specifically to avoid colliding with flavor 8's `pmos_lvt` directory.

**Note 2.1-b (block widths, corroborating):** standard block = 6 row + 25 col =
31 bits in a 32-bit stride → 1 spare; native block = 6 + 14 = 20 bits in a 24-bit
stride (96→120) → 4 spares. Matches CLAUDE.md's "24-bit block, 4 spares" for
flavor 4 and the datasheet's "one bit left unconnected" per segment (line 297).

---

## §2.2 — Geometry (datasheet Figs 3–6, 9–10 — these DO apply)

| CLAUDE.md fact | Datasheet | Verdict |
|---|---|---|
| Standard rows W(µm)=0.1,0.2,0.4,0.8,1.6,3 | lines 149, 158 | ✅ match |
| Single-finger cols 0–6: nf=1, L=30,40,60,90,200,500,1000 | line 147 | ✅ match |
| Multi-finger: no L=200; L=30,40,60,90,500,1000 × nf=2,4,8 → cols 7–24 | lines 153–160 (L=200 excluded); 6 L-groups × 3 nf = 18 cols | ✅ match |
| DRC: at L=1µm, W caps 2.65µm → affects (5,6),(5,22)–(5,24) | lines 151, 162, 205, 219; row 5=3µm, L=1000nm at col 6 (1f) & cols 22–24 (mf) | ✅ match |
| Native rows W(µm)=0.5,0.75,1,1.5,2,2.5 | lines 218, 223 | ✅ match |
| Native single-finger cols 0–4: L=300,500,600,900,1000 | line 217 | ✅ match |
| Native multi-finger cols 5–13: L=300,500,1000 × nf=2,4,8 | lines 222–223 (9 cols) | ✅ match |
| OPEN: W per-finger vs total | datasheet does not disambiguate | ✅ genuinely unspecified — flag in outputs, do not assume |
| OPEN: DNW multi-finger dims self-contradict | §2.1.3 says "exact same pattern" as standard (line 189) **then** lists native's L=300,500,1000 / W=0.5–2.5 (lines 199–201) | ✅ contradiction confirmed verbatim — flag, do not resolve |

---

## §2.3 — Pads / biasing model

| CLAUDE.md fact | Source | Verdict |
|---|---|---|
| Selected gate → shared Vg pad; drain/source → 4-wire Kelvin pads | datasheet lines 77, 84, 98, 237–238 | ✅ match |
| Unselected NMOS gates → Vgxn ≈ −50 mV; PMOS → Vgxp ≈ above VDD | datasheet lines 78, 302 ("50mV below vssd (i.e. −50mV)") | ✅ match |
| vgxp/vgxn ramped slowly (~10 s) by design | `routines.py` `_ramp_biases(..., duration_s=10.0, steps=40)` (lines 220–226) | ✅ match |
| Vb connects ONLY to DNW-array bodies | datasheet lines 109, 113 ("body terminal of DNW devices") | ✅ match |
| Leakage floor = summed off-leakage; calibrate by measuring with nothing selected | datasheet lines 80–81, 304 | ✅ match |
| Nominal supplies vdda 0.9 V core, 1.8 V I/O, on a MANUAL supply | `instrument_list.yaml` `keithley_e3631a_b`: P6V=`0.9V`, P25V=`1.8V`, comment "Manual-only rails; software intentionally does not drive these" (lines 30–34) | ✅ match (datasheet says only "28nm supply levels"; the YAML pins the 0.9/1.8 values and the manual-supply status) |

---

## §3 — Repository (functions to reuse verbatim)

| CLAUDE.md claim | Source | Verdict |
|---|---|---|
| `config.load_project_config(path)` | `config.py:55` `def load_project_config(path: str \| Path) -> ProjectConfig` | ✅ match |
| `routines.load_routines_csv(path) -> list[RoutineSpec]` | `routines.py:59` | ✅ match |
| `run_single_routine_from_csv(config, csv_path, routine_index) -> (spec, points)` | `routines.py:170`; returns `tuple[RoutineSpec, list[RoutineMeasurement]]` (line 283) | ✅ match. Full signature also has `point_callback`, `confirm_initial_bias`, `ids_settle_s` (lines 170–177) |
| It runs init biases, vgx ramp, step loop, sweep loop, Keithley reads | `routines.py` lines 192–274 (non-vgx init → vgx ramp → step→sweep loops → `_measure_current_a`) | ✅ match |
| `write_routine_measurements_csv(path, points)` | `routines.py:304` | ✅ match |
| `RoutineMeasurement` fields (12, exact order) | `routines.py:41–53` | ✅ exact: routine, step_param, step_value_v, sweep_param, sweep_value_v, vg_v, vd_v, vb_v, vs_v, vgxp_v, vgxn_v, drain_i_a |
| Drivers keithley2400/e3631a/bk9132c/serial_instrument present | `src/iv_measure/` listing | ✅ all present |
| `run_routine.py` uses a `sys.path.insert(0, "src")` shim | `run_routine.py:18–19` — actually `REPO_ROOT=Path(__file__).resolve().parent; sys.path.insert(0, str(REPO_ROOT/"src"))` | ✅ same effect. **Note 3-a:** the real shim is the absolute-path variant, more robust than the literal `"src"`. PLAN.md will copy the **actual** absolute-path form. |
| `plot_ids_vs_vgs.py` exists (output-format reference) | present at repo root | ✅ match |
| Routines nMOS file, index 0 = "Output WO Bulk" (sweep=Vd, step=Vg) | working tree lines 1–2 | ⚠️ index-0 name/params match, **count and polarity do not** — see **D-1** above |
| `instrument_list.yaml`: Keithley 2400 sources Vd/measures Id; E3631A does Vg & Vb | YAML: `keithley_2400 quantity: Vd` (line 5); `keithley_e3631a_a` P6V→Vb, P25V→Vg (lines 20–23) | ✅ match |

---

## §3.1 — Arduino pin map (active `#define`s)

| CLAUDE.md | sketch | Verdict |
|---|---|---|
| Supdate=2 | line 21 `#define PIN_SUPDATE 2` | ✅ |
| Srst=3 | line 22 | ✅ |
| Sclkp=4 | line 23 | ✅ |
| Sclkn=5 | line 24 | ✅ |
| Senable=6 | line 25 | ✅ |
| Sin=7 | line 26 | ✅ |
| Sout(digital)=8 | line 27 | ✅ |
| Sout_chip2=9 | line 28 | ✅ |
| **Sout ANALOG = A1** (moved from A0) | line 29 `#define PIN_SOUT_ANALOG A1` | ✅ |
| Commented-out LEGACY block Sin=2…Srst=7, analog A0 (trap) | lines 10–18 (all commented, "Pins OLD") | ✅ present & inert |
| Baud 115200 | line 265 `Serial.begin(115200)` | ✅ (D1 must match) |

---

## §3.2 — Polarities

| CLAUDE.md | sketch | Verdict |
|---|---|---|
| Srst ACTIVE HIGH (pulse HIGH→LOW; idles LOW) | `resetScanChain` HIGH→LOW (lines 70–73); setup idle LOW (line 260) | ✅ match |
| Senable ACTIVE LOW (idle HIGH = disabled, LOW while shifting) | `shiftScanChain` drives LOW then HIGH (lines 106, 146); setup idle HIGH "active low → disabled" (line 258) | ✅ match |
| Datasheet says "retain Senable HIGH" (documented conflict; sketch wins) | datasheet Scan Operation step 2, lines 277–279 | ✅ conflict present & expected — sketch is authoritative per §1 |
| Sout read via `analogRead` vs threshold (~100–300 counts) | `threshold=100` (line 31); `readSOUT_analog` `analogRead(A1) > threshold` (lines 64–66) | ✅ match (100 sits at the low end of the cited band) |

---

## §4 — Critical quirks

| Quirk | Source | Verdict |
|---|---|---|
| **Q1** verification compares Sout↔Sin in the SAME clock cycle → healthy chain reports 2 phantom mismatches | `shiftScanChain` compares `soutBit != expectedBit` inside the shift loop (lines 130, 137–140); `configureDevice` prints `Mismatches: N` (line 231) and `Test Passed/Failed` (line 232) | ✅ mechanism confirmed. Never gate on the pass/fail string; parse the count. |
| **Q2** bench reads 3; Python abort if `mismatches > 4` | CLAUDE.md §5 bench log (July 2026). Not encoded in the sketch. | ✅ bench fact; will cite in D2/D3 |
| **Q3** Vg–vdda short ABSENT on this chip | datasheet §4.1 documents it for the ORIGINAL design (lines 342–353); §5 bench continuity check found no short | ✅ erratum present & expected — build no workaround |
| **Q4** native array = 14 cols (0–13) | `flavor_cols()` (lines 54–57) | ✅ match |
| **Q5** serial single-occupancy; ports drift; take port as CLI arg | operational fact; consistent with `instrument_list.yaml` COM assignments | ✅ no conflict |
| **Q6** Arduino auto-reset on port-open unreliable → DTR pulse + READY banner + PING/PONG fallback | operational fact; current sketch prints `start` (line 267), not a READY banner (D1 adds `READY`) | ✅ no conflict |
| **Q7** vgxp/vgxn ~10 s ramp lives inside `run_single_routine_from_csv` | `routines.py` `_ramp_biases(duration_s=10.0)` (lines 220–226) | ✅ match — reuse preserves it |
| **Q8** warm-measurement expectations | qualitative bench guidance; no code contradiction (but see **D-1** re: index-0 polarity now negative on an nMOS routine) | ✅ no source conflict; flagged interaction with D-1 |

---

## Summary

**One item needs your decision: D-1** (the nMOS routines CSV now has 3 routines and
an index-0 polarity flipped negative, versus CLAUDE.md §3's "2 routines … Output WO
Bulk (Vd/Vg)"; `git status` shows the file mid-edit). Everything else — the entire
scan chain (§2.1), geometry (§2.2), pad/bias model (§2.3), reused functions (§3),
pin map (§3.1), polarities (§3.2), and all eight quirks (§4) — cross-checks **clean**
against the sketch, `routines.py`, `config.py`, the datasheet, and `instrument_list.yaml`.
The datasheet's 472-bit chain and §4.1 Vg-vdda erratum are present exactly as
CLAUDE.md predicted and do **not** apply to this chip. The `pmos_lvt`↔`pmos_lvt_b`
naming and the absolute-path import shim are reconciliations, not conflicts.
