# RUNBOOK — manually operating the 28nm PDK characterization rig

Practical, copy-pasteable commands for running measurements and diagnosing the
bench by hand. Everything here uses the NEW repo-root scripts; the original
`src/iv_measure/` code, routine CSVs, `instrument_list.yaml`, and sketches are
never edited (see `CLAUDE.md` for the minimalism rule).

> **Bench safety:** only run hardware-touching commands when the rig is powered
> and you are watching it. When a chip looks "dead," check the physical bench
> first (rails, bias, wiring) before assuming silicon damage.

---

## 0. One-time setup each session

```bash
# from the repo root
.venv/Scripts/activate            # Windows venv (pyserial, matplotlib, pyyaml)
```

**Ports drift after replug (Q5).** Confirm them before anything else:

```bash
.venv/Scripts/python -c "import serial.tools.list_ports as p; [print(x.device, x.description) for x in p.comports()]"
```

Expected roles (verify against `instrument_list.yaml`):

| Role | Instrument | Port (typical) |
|------|-----------|----------------|
| Scan chain | Arduino Nano R4 (SEL sketch) | **COM11** |
| Vd source / Id meter | Keithley 2400 | **COM7** |
| Vg (P25V) + Vb (P6V) | E3631A | **COM5** |

**Only ONE program may hold a serial port.** Close the Arduino IDE Serial
Monitor before running any Python that talks to COM11, and vice-versa.

**Manual bench supplies — set these BEFORE measuring (not software-controlled):**
- Core rail **0.9 V**, I/O rail **1.8 V** (if OFF, the chip looks totally dead).
- **vgxp = +0.95 V** (just above VDD), **vgxn = −0.2 V** (BELOW ground).
  vgxn positive turns on all unselected devices → gate-independent leakage that
  pins compliance. −0.2 V is the known-good value (matches good-data runs).

---

## 1. Pre-flight: is the scan link alive?

```bash
.venv/Scripts/python test_scan_link.py --scan-port COM11
```

Opens the port (READY banner OR PING/PONG fallback, Q6), pings, and does two
SELs. **Note (Q1/Q2):** a "Mismatches" count near 342 does NOT by itself mean
failure — the count only tests the Sout read-back path. Use the bit-stream tool
(below) to see what's really happening.

---

## 2. Inspect the scan bit stream (SIN vs SOUT)  ← the key diagnostic

Shows, bit-by-bit, what was shifted IN vs what the chip read back. This is how
you tell a healthy chain from a dead read-back — the summary count hides it.

```bash
.venv/Scripts/python scan_bits.py --scan-port COM11 --flavor 3 --row 0 --col 0
```

Options: `--flavor/--row/--col` (default 3 0 0), `--width N` (bits per block),
`--save PATH` (write the raw sketch dump).

**Reading the output** — three aligned rows per block plus a verdict line:

```
bit   0: SIN  000...   what the Arduino shifted in (one-hot: exactly two 1s)
         SOUT 111...   what the chip read back (A1 analog > threshold)
         diff ^^^...   ^ where they differ
```

| SOUT pattern | Meaning |
|--------------|---------|
| **all 1s (flat)** | Sout stuck HIGH — line disconnected/pulled high, or ADC threshold too low. **Read-back dead** (chip pin 15 → Arduino A1). |
| **all 0s (flat)** | Sout stuck LOW — not driven, or threshold too high. |
| **≤4 mismatches** | Read-back healthy (2 ideal, 3 bench-norm, Q2). |
| **structured, many mismatches** | Chain is shifting; compare SOUT to a *shifted* copy of SIN. |

The two SIN=1 bits encode the selected device: for flavor F the row bit is at
`base+row` and the col bit at `base+6+col` (bases in `device_registry.py`). The
sketch prints in REVERSE order, so printed `Bit#` = `343 − logical bit`.

**Current known state (2026-07-13):** SOUT stuck HIGH → read-back dead. Next
hardware step: meter connector **pin 15 (CHIP2_SOut)** to GND during a SEL.

---

## 3. Diagnose the drain path (short vs leakage vs open)

Every routine slams to the 10 mA / 0.85 V rail, which can fake a "short." These
trace GENTLY (low V, low compliance) to get a real number.

**Resistance of the drain node** (fits R = dV/dI):

```bash
.venv/Scripts/python trace_short.py --scan-port COM11 --flavor 3 --row 0 --col 0 \
    --vmax 0.1 --compliance 1e-3
```

Verdict: few Ω = hard short (fixture/blown); kΩ = leakage; MΩ = open (the 10 mA
runs were a forward-biased junction, not an ohmic short). Omit `--scan-port` to
trace whatever is currently latched (no selection).

**Does the gate control the channel?** (steps Vg, gentle Vd):

```bash
.venv/Scripts/python trace_gate_step.py --scan-port COM11 --flavor 3 --row 0 --col 0 \
    --vmax 0.2 --compliance 1e-3 --vg 0.0 0.2 0.4 0.6 0.8
```

If Id at a fixed Vd changes strongly across Vg → working transistor. If it
doesn't → gate isn't reaching the channel (selection or gate wiring), NOT
geometry.

---

## 4. Calibration / leakage baseline (nothing selected)

Measures the shared rails with NO device enabled (datasheet §2.3). If this looks
identical to a "selected" run, the current is parasitic, not from a transistor.

```bash
.venv/Scripts/python run_calibration.py \
    --routines "Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv" \
    --scan-port COM11 --out data/calibration_check
```

(It deselects by sending an out-of-range SEL, which latches an all-zero chain.)

---

## 5. Full automated measurement loop

Selects each device, runs the correct-polarity routine, saves CSV + annotated
PNG, grades the shape, and can resume after interruption.

**Device list** (`devices.csv`, header required; flavor = sketch's 1–11):

```
flavor,row,col
3,0,0
3,0,1
```

Generate one full nMOS block (flavor 3 = nmos_mid, 150 devices):

```bash
.venv/Scripts/python -c "print('flavor,row,col'); [print(f'3,{r},{c}') for r in range(6) for c in range(25)]" > devices.csv
```

**Run it** (type-aware routing: nMOS flavors 1–6 vs pMOS 7–11):

```bash
.venv/Scripts/python run_device_loop.py \
    --devices devices.csv \
    --routines-nmos "Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv" \
    --routines-pmos "Routines/Cryo PDK DC measurement routines - pMOS 28nm.csv" \
    --routine-index 0 \
    --scan-port COM11 \
    --out data/chip_two
```

Flags:
- `--routines <one file>` — use one CSV for both types (back-compat).
- `--routine-index N [N…]` — which routine row(s) per device (0 = "Output WO Bulk").
- `--ignore-readback` — don't abort on high scan Mismatches. Use ONLY when the
  Sout read-back is known-broken but selection is verified another way (the
  shape grader stays the real gate). See Q1/Q2.
- `--config` — instrument YAML (default `instrument_list.yaml`).

**Output layout:**
```
data/<out>/<nmos|pmos>/<flavor>_r<row>c<col>/<routine>_<YYYY-MM-DD>.{csv,png,verdict.txt,SUSPECT.txt}
```
The PNG is stamped with `flavor N (name) | W=..um L=..nm nf=.. | measured DATE`.
A bad-shaped run is saved but flagged `SUSPECT` (never silently "passes").
Final line: `N done, M skipped, K failed, S suspect`. Re-running the same
`--out` skips devices that already have a CSV (resume).

---

## 6. Single device / interactive (original runner, live plot)

```bash
.venv/Scripts/python run_first_routine.py \
    --routines-csv "Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv" \
    --routine-index 0 --output-csv data/one.csv
```

Does NOT drive the scan chain — measures whatever device is currently latched.
Add `--no-live-plot --no-confirm-initial` to run headless (no GUI window / no
Enter prompt), e.g. when driving it from a non-interactive shell.

---

## 7. Interpreting results (CLAUDE.md Q8)

Healthy output family: curves FAN with Vg, rise then saturate, µA–tens-of-µA for
mid-geometry NMOS at 300 K. Warning signs:
- **All flat at nA** → nothing selected (leakage floor).
- **Pinned at one value** → compliance limit, not physics.
- **Curves overlap (no Vg spread)** → gate not controlling the channel.

The `validate_iv` grader checks these automatically and writes `SUSPECT.txt`.

---

## Quick troubleshooting map

| Symptom | Check |
|---------|-------|
| "no READY / no PONG" on open | right COM port? Serial Monitor open? SEL sketch flashed? |
| E3631A returns empty strings | needs `SYST:REM` first + `\r\n`/`\n` termination |
| Keithley first read empty | reset port + retry; it returns a 5-element array (I = field 1) |
| All curves flat / pinned / overlapping | rails on? vgxn = −0.2 V? then `scan_bits.py` + `trace_gate_step.py` |
| SOUT all 1s in `scan_bits.py` | Sout read-back dead — meter chip pin 15 to GND during a SEL |
