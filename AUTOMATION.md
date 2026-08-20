# AUTOMATION.md — running the overnight device-loop characterization

This document covers the **unattended array automation**: selecting each
transistor via the Arduino scan chain, running the existing IV routines, and
saving a CSV + PNG per device. For a single manual measurement of whatever
device is currently latched, use `run_routine.py` instead (see
[README.md](README.md)).

The automation is three repo-root scripts, layered so you never start a long
run on an unproven bench:

| Script | Touches instruments? | Purpose |
|--------|----------------------|---------|
| `test_scan_link.py` | No (scan chain only) | 60-second pre-flight |
| `run_device_loop.py` | Yes | the overnight loop |
| `flush_analyze.py`  | No | chain-length discovery for the 2nd chip (see [PUSH_RUNBOOK.md](PUSH_RUNBOOK.md)) |

---

## 0. One-time setup

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
```

Then confirm:

1. The **SEL-patched sketch** is flashed to the Arduino
   (`Arduino/sketch_may26_r4_SEL/` for chip 1 only, or
   `Arduino/sketch_may26_r4_SEL_PUSH/` for the two-chip chain — see
   [PUSH_RUNBOOK.md](PUSH_RUNBOOK.md)). Flash with `arduino-cli`, then
   **close the Arduino Serial Monitor** — the serial port is
   single-occupancy (only one program at a time).
2. `instrument_list.yaml` lists the correct **COM ports** for the Keithley
   2400 and the E3631A. Windows reassigns COM numbers after a replug, so
   verify before every session.
3. The chip is **powered** (manual bench supply: vdda core, I/O rail) and the
   vgx rails are present at the chip pins.

> **Ports are always passed on the command line** (`--scan-port`), never
> hardcoded. Find the Arduino port with Device Manager or `probe_port.py`.

---

## 1. Pre-flight — `test_scan_link.py`

Run this **first, every session**. No instruments needed.

```powershell
python test_scan_link.py --scan-port COM11
```

It checks, in order:

1. `READY` banner after port-open — the patched sketch is flashed.
2. `PING` → `PONG` — the command parser is alive.
3. `SEL 3 0 0` completes with `Mismatches: <= 4`.
4. A second `SEL 3 0 1` completes — proves re-selection works.

**Reading the mismatch count** (this trips everyone up): a *healthy* chain
reports **2 or 3** mismatches. The sketch compares Sout to Sin in the same
clock cycle, so it always flags the two one-hot bits as phantom "mismatches",
and this bench's weak-Sout analog read adds one more. `0` means the readback
saw nothing; `> 4` means a real fault (Sout threshold, wiring, or chip power).
The count tests only the readback path — it does **not** prove selection.
Selection is proven later by the shape of a real transistor's IV curve.

Exit code `0` = ready. Run it **twice** and require identical results before
proceeding.

---

## 2. The device list — `devices.csv`

A CSV with a header and one `flavor,row,col` per line. `flavor` is the
sketch's **1–11** number:

```
flavor,row,col
3,0,0
3,0,1
```

| flavor | name | flavor | name |
|--------|------|--------|------|
| 1 | nmos_lvt | 7 | pmos_ulvt |
| 2 | nmos_hvt | 8 | pmos_lvt |
| 3 | nmos_mid | 9 | pmos_mid |
| 4 | nmos_na *(14 cols)* | 10 | pmos_hvt |
| 5 | nmos_ulvt | 11 | pmos_lvt_b |
| 6 | nmos_dnw | | |

Rows are `0–5` everywhere. Columns are `0–24`, **except flavor 4 (native),
which is `0–13`.** The loop validates these bounds and rejects an
out-of-range row with a `file:line` error.

**Generate a whole block** (all 150 devices of nmos_mid = flavor 3):

```powershell
python -c "print('flavor,row,col'); [print(f'3,{r},{c}') for r in range(6) for c in range(25)]" > devices.csv
```

**Generate the full chip** (1,584 devices, respecting native's 14 columns):

```powershell
python -c "print('flavor,row,col'); [print(f'{f},{r},{c}') for f in range(1,12) for r in range(6) for c in range((14 if f==4 else 25))]" > devices.csv
```

---

## 3. The overnight loop — `run_device_loop.py`

```powershell
python run_device_loop.py `
  --devices devices.csv `
  --routines-nmos "Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv" `
  --routines-pmos "Routines/Cryo PDK DC measurement routines - pMOS 28nm.csv" `
  --routine-index 0 `
  --scan-port COM11 `
  --out data/loop_run1
```

For each `(device × routine)` it: sends `SEL <flavor> <row> <col>` to the
Arduino → runs the existing routine (`run_single_routine_from_csv`, which
preserves the slow vgx ramp) → writes the measurements CSV → renders a
two-panel PNG (linear + log |Id|). Then it grades each result for physical
plausibility and flags meaningless runs as **SUSPECT** rather than silently
counting them done.

### Key arguments

- `--devices` *(required)* — the `flavor,row,col` CSV.
- `--routines-nmos` / `--routines-pmos` — routine CSV per type. **Use both**:
  nMOS and pMOS need opposite-polarity routines (a pMOS device run against an
  nMOS routine is the 2026-07-13 failure). `--routines <file>` applies one
  file to both types (back-compat only).
- `--routine-index N [N …]` — which routine row(s) to run per device
  (default `0`).
- `--scan-port` *(required)* — Arduino COM port.
- `--config` — instrument YAML (default `instrument_list.yaml`).
- `--out` — output root (default `data/device_loop`).
- `--ignore-readback` — do **not** abort on high mismatch counts. Use only
  when Sout readback is known-broken and you are trusting the shape grader.
- `--no-leak-subtract` — skip the automatic post-run leakage-subtraction
  pass (by default each NMOS Output routine-0 CSV also gets a
  `__leaksub.csv/.png`).
- `--live-plot` — show a live window that draws each curve as it measures,
  then auto-advances. **Omit for headless overnight runs.** PNGs are saved
  either way.

### Output layout

```
data/<out>/<nmos|pmos>/<flavorname>_r<row>c<col>/<device>__<geo>__<routine>_<date>.csv
                                                  <device>__<geo>__<routine>_<date>.png
```

The final line prints a summary: `N done, M skipped, K failed` (plus SUSPECT
count).

### Resume after interruption

The loop **skips any device+routine that already has a CSV** in `--out`, so
re-running the identical command resumes where it stopped. **Blind spot:** a
crash mid-write can leave a truncated CSV that looks "done". After any crash,
**delete the newest CSV** before resuming.

---

## 4. Test ladder (recommended order for a fresh bench)

1. `test_scan_link.py` twice — identical results required.
2. One device, one routine — **human grades the PNG**: Id–Vd curves should
   fan with Vg, rise then saturate, µA-scale. All-flat-at-nA = nothing
   selected; pinned at compliance = a short, not physics.
3. Re-run the identical command → expect `0 done, 1 skipped` (resume works).
4. Ten devices (row 0 of nmos_mid): Id should **fall** as column 0→6 (L
   grows) and **rise** across 7→9 (nf grows). Scrambled ordering means
   selection isn't landing where the labels claim — **stop**.
5. Overnight run, budgeted from the rung-4 timing (~25 ms per SEL + routine
   sweep time × device count). Morning triage: grep for `FAILED` files,
   spot-check the flavor Vth ladder.

---

## Related documents

- [README.md](README.md) — single-device `run_routine.py`, instrument YAML,
  routine CSV format.
- [PUSH_RUNBOOK.md](PUSH_RUNBOOK.md) — configuring the **second** chip on the
  shared scan chain (the push mechanism).
- [CLAUDE.md](CLAUDE.md) — full hardware brief, quirks (Q1–Q8), and bench log.
