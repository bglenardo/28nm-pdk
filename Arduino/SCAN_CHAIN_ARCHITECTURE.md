# Scan-Chain Architecture & Arduino Firmware Reference

This board carries **two ASIC chips daisy-chained in series** on a single scan
chain. This document is the ground truth for how the scan chain works and which
Arduino sketch to use, because the sketches were historically scattered across
git branches with little documentation.

## TL;DR

- The two chips are in **series**: `SIN → chip 1 (344 bits) → chip 2 (344 bits) → SOUT`.
- To address a device on **chip 1** you clock **344** bits.
- To address a device on **chip 2** you must clock **688** bits (push the
  pattern *through* chip 1 into chip 2).
- To **verify** the full chain you clock **1032** bits (344×3) and read SOUT.
- `TOTAL_BITS = 344` per chip; `scan_data` is 43 bytes (344 bits).

This confirms the long-standing understanding: **yes, reaching the second chip
requires a full 688-bit shift**, and the currently-flashed
`LBL_setup/automated_arduino/automated_arduino.ino` does **not** do this (see
"Known-broken sketch" below).

## Clock-count model (from the authoritative sketches)

| Target            | Clocks | Meaning                                              |
|-------------------|--------|------------------------------------------------------|
| Chip 1            | 344    | Shift pattern into chip 1.                            |
| Chip 2            | 688    | Shift pattern *through* chip 1, into chip 2.          |
| Verify full chain | 1032   | Shift + let the pattern propagate to SOUT, read back. |

During a shift the scan pattern is driven into `SIN` only for the **first 344
clocks**; after that `SIN` is held LOW so zeros trail the pattern and push it
downstream.

## Device address map (bit offsets) — IMPORTANT: two conventions exist

`setScanAddress(flavor, row, col)` writes **two one-hot bits** into `scan_data`
(one for the row/width, one for the column/length+finger-count) inside a
per-flavor 32-bit block. The block start is `base = flavor_base[flavor]`:

| flavor | name       | base | cols |
|--------|------------|------|------|
| 1      | nmos_lvt   | 0    | 25   |
| 2      | nmos_hvt   | 32   | 25   |
| 3      | nmos_mid   | 64   | 25   |
| 4      | nmos_na    | 96   | 14   |  (native array: only 14 columns)
| 5      | nmos_ulvt  | 120  | 25   |
| 6      | nmos_dnw   | 152  | 25   |
| 7      | pmos_ulvt  | 184  | 25   |
| 8      | pmos_lvt   | 216  | 25   |
| 9      | pmos_mid   | 248  | 25   |
| 10     | pmos_hvt   | 280  | 25   |
| 11     | pmos_lvt   | 312  | 25   |

The `flavor_base` array above is identical in **every** sketch. What differs is
the per-block bit offset, and there are **two conventions** in the repo history.
Getting this wrong selects the wrong on-chip cell (or none) while leaving the
chain electrically healthy — so `VERIFY` still passes but `Ids` stops responding
to `Vg`.

**CURRENT / CORRECT convention (use this)** — the no-spacer encoding, from the
earlier `lbl_arduino_board_switching_code.ino` / `sketch_may26_r4*` and restored
in `Arduino/unified_scan_select/unified_scan_select.ino` on 2026-11-02:

```
row_bit = base + row         // rows occupy bits 0..5 of each 32-bit block
col_bit = base + 6 + col     // columns start at bit 6
```

**OLD convention (do NOT use — one bit too HIGH)** — the `+1` "spacer" encoding
from `WDH-setup/automated_arduino/automated_arduino.ino`:

```
row_bit = base + 1 + row     // +1 spacer; shifts every one-hot bit one too high
col_bit = base + 7 + col
```

Valid ranges: `1 <= flavor <= 11`, `0 <= row < 6`, `0 <= col < flavor_cols(flavor)`.

> HISTORY: the `+1` spacer appeared in the latest LBL firmware on
> `wdh-current-flow` and was briefly treated as authoritative. A `Vg` sweep on a
> **low-index** device (2026-11-01) seemed to confirm it — `Ids` = 11.1 / 251 /
> 779 µA at `Vg` = 0.1 / 0.5 / 0.9 V — but that only proved the bit landed on
> *some* real transistor, not the labelled one.
>
> CORRECTED 2026-11-02: a full 834-device scan compared against the
> flavor-keyed simulation (`data/Simulation_at_300K.csv`) showed the `+1`
> encoding was off by one **too high**. The TOP index of each field was dead
> across *every* flavor — label `row 5` lit `base+6` = physical row 6 (nonexistent),
> label `col 24` (NA: `col 13`) ran off the end of the column field — i.e. every
> label N selected physical cell N+1 and physical row 0 / col 0 were unreachable.
> Flavors were verified *correctly* aligned by the same comparison (native
> `NMOS_NA` has the lowest Vt in both measured and sim, at flavor index 3 in
> both; full Vt rank order matches, Spearman rho = 0.94). Dropping the `+1`
> (back to `base+row` / `base+6+col`) restores label N -> physical cell N.
> Re-verify on hardware with a top-index device (`row 5`, and the top column)
> after reflashing.


## Shift order — MSB-first (also critical)

The one-hot pattern must be clocked out **MSB-first**: drive `scan_data` bit
`TOTAL_BITS-1` first, down to bit `0`. The latest LBL firmware and all the
verification sketches do this:

```c
for (int i = TOTAL_BITS - 1; i >= 0; i--) { /* drive scan_data bit i */ }
```

Clocking LSB-first (bit 0 first) **bit-reverses** the one-hot pattern inside the
shift register and selects a mirror cell (or none). `VERIFY` cannot catch this:
it compares what it drove on `SIN` against what it later read on `SOUT` **in the
same order**, so a reversed order is still internally self-consistent and still
reports `passed=1`. `unified_scan_select.ino` was corrected to clock MSB-first.

## Pin map (authoritative sketches)

| Signal   | Pin  |
|----------|------|
| SUPDATE  | 2    |
| SRST     | 3    |
| SCLKP    | 4    |
| SCLKN    | 5    |
| SENABLE  | 6 (active LOW) |
| SIN      | 7    |
| SOUT     | A1 (analog read, threshold ~100) |

Gotcha: `SUPDATE` is an **edge-triggered latch** — it must be *pulsed*
(HIGH→LOW) on every `latchScanConfig()`. Driving it only LOW works once from the
idle-HIGH state but produces no edge on later calls, so the DUT never changes
and every device yields identical curves. The `scopes_asic_test.ino` sketch has
the correct pulsed latch; `cryo_pdk_DUMMY_OFFICIAL.ino` has the broken
LOW-only version.

## Which sketch to use

All paths listed under `Arduino/`.

- **`scopes_asic_test/scopes_asic_test.ino`** — RECOMMENDED. Daisy-chain aware,
  has a clean line-based host protocol and a verification mode. Compile-time
  `SCOPE_MODE` selects clock count:
  - `0` = Verification (1032 clocks, reads SOUT, prints mismatches)
  - `1` = Full scope (1032 clocks, no analog read)
  - `2` = Chip 1 (344 clocks)   ← default
  - `3` = Chip 2 (688 clocks)
  - Correct pulsed `latchScanConfig()`.
  - Serial protocol @ **115200 baud**:
    - Boot prints `start`, mode info, then `READY`.
    - `SEL <flavor> <row> <col>` (space-delimited) → configures device, then `SEL_DONE`.
    - `PING` → `PONG`.
    - In mode 0 a `SEL` also prints the mismatch report before `SEL_DONE`.
- **`cryo_pdk_DUMMY_OFFICIAL.ino`** — reference/verification harness. One-shot:
  configures a single device in `setup()` then halts; no serial command loop.
  Useful for scope work, not for automation.
- **`sketch_may26_r4_SEL/automation_r4_SEL_v1.ino`**,
  **`sketch_may26_r4_SEL_PUSH/sketch_may26_r4_SEL_PUSH.ino`** — Nano-R4
  experiments (extra "push" clocks to overcome latching). Kept for history.

### Known-broken sketch

`LBL_setup/automated_arduino/automated_arduino.ino` (the one currently flashed):
- Only ever shifts **344 bits ×4** with a latch between passes — it never does
  688 bits, so it **cannot address chip 2** correctly.
- Computes `c1_val`/`c2_val` from the `chip` argument but then **never uses
  them**.
- Never reads SOUT (`soutLog` stays all-zero), so its `compareLogs` always
  reports set bits as `SIN=1 SOUT=0` — the "verification" is meaningless.
Treat it as deprecated. (Note: its `base+1+row` / `base+7+col` offsets are
actually the *correct* convention — see the address-map section — but the
344×4 shift strategy still makes it unusable for addressing chip 2.)

## RESOLVED: where is SOUT physically tapped?

**A1 is wired to the SOUT of chip 2 — the very END of the series chain.**
(Confirmed by the user, 2026-10-25, from the board.) Chip 1's SOUT connects
directly to chip 2's SIN through a **0 Ω resistor**, so the two chips form one
continuous 688-stage shift register: `SIN → chip1 (344) → 0Ω → chip2 (344) → A1`.

Consequences:
- A data bit driven at clock `k` only appears on A1 after it propagates through
  **both** chips, i.e. at clock `k + 688` (empirically ~687–688). So the only
  valid readback alignment is the **chip-2 / end-of-chain tap (~688)**; the
  "midpoint(344)" hypothesis is ruled out.
- To read back **any** data you must clock the full chain (≥688). `VERIFY`
  clocks 1032, so a correct A1 capture should show `best_offset ≈ 687–688` with
  `tap=chip2`.
- The older sketches' first/middle sampling windows were simply wrong guesses;
  end-of-chain is correct.

> Because the tap is now known, a flat-LOW A1 (`sout_highs=0`) is **not** a tap
> alignment problem — it means no real data is reaching A1 (wiring to A1, analog
> threshold, or, most likely, the DUT scan-chain rails not being powered).


## Runtime chip selection limitation

In the older authoritative sketches, chip 1 vs chip 2 was a **compile-time**
`SCOPE_MODE`, not a runtime `SEL` argument. This has been resolved by the
unified sketch below.

## Unified sketch (RECOMMENDED for automation)

`Arduino/unified_scan_select/unified_scan_select.ino` is a new, runtime-
controlled driver that supersedes the older sketches for automation:

- Selects the target chip at **runtime** from the host command, clocking 344
  bits for chip 1 or 688 bits for chip 2.
- Uses the authoritative bit offsets (`base+row`, `base+6+col`) and the correct
  **pulsed** `latchScanConfig()`.
- Protocol @ **115200 baud**, newline-terminated, commas OR spaces accepted:
  - boot: prints a banner ending in `READY`
  - `SEL <f> <r> <c> <chip>` -> selects device, replies `SEL_DONE` (or
    `SEL_FAIL` on a bad address)
  - `VERIFY <f> <r> <c>` -> clocks the full 1032-bit chain, samples SOUT, and
    prints `VERIFY ... mismatch_mid=.. mismatch_end=.. best=.. passed=..` then
    `VERIFY_DONE`
  - `PING` -> `PONG`

### How VERIFY resolves the SOUT tap-point question automatically

The VERIFY command captures SOUT on all 1032 clocks and then counts mismatches
against the driven pattern under **two** alignment hypotheses:
- `mismatch_mid` assumes SOUT is tapped after 344 stages (chip-1 output).
- `mismatch_end` assumes SOUT is tapped after 688 stages (chip-2 output).
Whichever count is ~0 reveals the real tap point empirically (no schematic
needed). The host sees both numbers and the firmware's `best=` pick.

The Python host (`iv_measure.bench.ArduinoDeviceSelector`, used by both
`run_routine_test.py` and `run_routine_automated_scan.py`), the YAML
(`instrument_list.yaml`, 115200 baud, 4-field command) and
`test_arduino_connection.py` (`--verify`, `--chip`) all target this sketch.

To use: flash `unified_scan_select.ino` to the Nano R4, then run
`python test_arduino_connection.py --verify --flavor 1 --row 1 --col 6` to read
the alignment report before running routines.
