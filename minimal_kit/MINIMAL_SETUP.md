# MINIMAL SETUP — every change, its exact location, and the test ladder

Total footprint on the repo: **1 replaced sketch + 3 new files at repo
root. Zero existing Python files are modified.**

```
28nm-pdk/                                  (your existing clone)
├── Arduino/
│   └── sketch_may26_r4_SEL/               ← NEW folder (from this kit)
│       └── sketch_may26_r4_SEL.ino        ← flash THIS to the scan Arduino
├── run_device_loop.py                     ← NEW (this kit) — the loop
├── test_scan_link.py                      ← NEW (this kit) — pre-flight
├── devices_example.csv                    ← NEW (this kit) — edit freely
│
├── src/iv_measure/…                       untouched
├── Routines/…                             untouched
├── instrument_list.yaml                   untouched (verify ports only)
└── run_routine.py, plot_ids_vs_vgs.py     untouched (still work as before)
```

────────────────────────────────────────────────────────────────────────────
## CHANGE 1 of 2 — the Arduino (the only firmware change)

`sketch_may26_r4_SEL.ino` is the repo's newest working sketch with exactly
two edits, both marked `// PATCH` in the file so you can diff it against the
original in seconds:

  * **setup(), bottom** — original ends with:
        configureDevice(1, 0, 14); // (flavor, row, col)
        while (true) {}
    patched version replaces those two lines with:
        Serial.println(F("READY"));
  * **loop()** — original is `void loop() {}`; patched version parses
    `SEL <flavor> <row> <col>` and `PING` from Serial and calls the
    **original `configureDevice()` unchanged**.

Everything else — pin defines, clock timing, `setScanAddress()`,
`shiftScanChain()`, `latchScanConfig()`, the verification report — is the
original file byte-for-byte. Flash via Arduino IDE to the scan Arduino
(same board the old sketch ran on; this replaces it — the old sketch stays
in the repo untouched if anyone needs to go back).

Flavor numbers are the sketch's own 1–11:
  1 nmos_lvt   2 nmos_hvt   3 nmos_mid   4 nmos_na(14 cols!)  5 nmos_ulvt
  6 nmos_dnw   7 pmos_ulvt  8 pmos_lvt   9 pmos_mid  10 pmos_hvt
  11 pmos_lvt_b (the chip's second PMOS lVt array)
Rows 0–5, cols 0–24 (0–13 for flavor 4).

────────────────────────────────────────────────────────────────────────────
## CHANGE 2 of 2 — three files copied into the repo root

* **run_device_loop.py** — the automation. Imports the repo's own
  `load_project_config`, `load_routines_csv`, `run_single_routine_from_csv`,
  `write_routine_measurements_csv` and adds only: the SEL serial handshake,
  the device loop, skip-if-CSV-exists resume, per-device error isolation,
  and a linear+log PNG per routine.
* **test_scan_link.py** — 60-second pre-flight (no instruments needed).
* **devices_example.csv** — three devices to start. Generate a whole block:
      python -c "print('flavor,row,col'); [print(f'3,{r},{c}') for r in range(6) for c in range(25)]" > devices.csv
  or all 1,584 devices:
      python -c "print('flavor,row,col'); [print(f'{f},{r},{c}') for f in range(1,12) for r in range(6) for c in range(14 if f==4 else 25)]" > devices_all.csv

Prerequisites (once): `pip install pyserial matplotlib pyyaml`

────────────────────────────────────────────────────────────────────────────
## BEFORE FIRST RUN — verify these 3 things (nothing else)

1. **instrument_list.yaml ports** — the Keithley and E3631A entries must
   name the ports they're on TODAY (they drift when USB adapters move).
   The Arduino's port is NOT in this file; it's the `--scan-port` argument.
2. **You know which port is the Arduino** — unplug/replug and watch the
   device list, or `python test_scan_link.py --scan-port <guess>` (a wrong
   port fails safely at step 1 with "no READY").
3. **Chip is powered** (vdda/manual rails up) before any SEL — the scan
   chain can't latch into an unpowered chip.

────────────────────────────────────────────────────────────────────────────
## TEST LADDER — run in this order, each rung gates the next

RUNG 1 — firmware alone (no instruments, chip powered):
    python test_scan_link.py --scan-port COM8
  Expect: READY, PONG, two SELs with Mismatches=2 and "Test Failed".
  YES, "Test Failed" with exactly 2 is the HEALTHY result — the original
  sketch's verification compares Sout to Sin in the same clock cycle, so a
  good chain always "fails" at the two one-hot bit positions. >2 = real
  problem (Sout threshold, wiring, power). The Python accepts <=2.

RUNG 2 — one device, one routine (instruments on):
    python run_device_loop.py --devices devices_example.csv \
        --routines "Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv" \
        --routine-index 0 --scan-port COM8 --out data/smoke
  ...but first trim devices_example.csv to ONE line. Expect one folder:
    data/smoke/nmos_mid_r0c0/Output_WO_Bulk.csv + .png
  Open the PNG: does it look like a transistor? (routine 0 is an output
  family: Id vs Vd at several Vg — expect fanned curves, linear rise then
  saturation, µA-scale for a warm mid-size NMOS.)

RUNG 3 — resume check (free, 5 seconds):
  Re-run the identical command. Expect "0 done, 1 skipped". That's the
  resume mechanism you'll rely on overnight.

RUNG 4 — small loop (~10 devices): restore devices_example.csv / generate a
  partial block. Watch 2–3 iterations live: SEL report → routine sweeps →
  files appear. Then check one flavor-consistency spot: curves within one
  block should look like siblings.

RUNG 5 — overnight: devices_all.csv (or one block), both routine indices:
    ... --routine-index 0 1 --out data/warm_fullchip
  Before walking away: note the per-device time from rung 4 and multiply —
  if it exceeds your night, split by block across nights. Any device that
  errors writes <name>.FAILED.txt and the loop continues; grep for those in
  the morning:  ls data/warm_fullchip/*/*FAILED* 

────────────────────────────────────────────────────────────────────────────
## What you get on disk

    data/<run>/<flavor>_r<row>c<col>/<routine>.csv     (repo's own format)
    data/<run>/<flavor>_r<row>c<col>/<routine>.png     (linear + log panels)

CSV columns are unchanged from the repo's writer, so plot_ids_vs_vgs.py and
any existing analysis notebooks keep working on these files.

## Known limits of the minimal path (accepted trade-offs)
  * Resume = "CSV exists": a run killed MID-file leaves a partial CSV that
    will be skipped. If a crash happens, delete the newest CSV before
    re-running.
  * No metadata sidecar (temperature, timestamps, scan vector) beyond the
    CSV itself — write cooldown conditions in the lab notebook.
  * vgxp/vgxn ramp, settle times, compliance: all exactly as the repo's
    routines.py already does them (that's the point).
