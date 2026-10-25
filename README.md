# Cryo 28 nm PDK — Transistor I-V Measurement Bench

This project provides a Python interface for transistor I-V measurements on the
SLAC cryo 28 nm PDK bench, plus the Arduino scan-chain firmware used to select
which on-chip device is under test.

The main entry point for a single measurement routine is `run_routine.py`.
The scan-chain device selector is driven by the Arduino firmware in
[Arduino/unified_scan_select/](Arduino/unified_scan_select/).

> **Scan-chain architecture:** the board carries **two ASIC chips daisy-chained
> in series** (`SIN → chip 1 (344 bits) → 0 Ω → chip 2 (344 bits) → SOUT/A1`).
> The authoritative reference for bit offsets, clock counts, and pin mapping is
> [Arduino/SCAN_CHAIN_ARCHITECTURE.md](Arduino/SCAN_CHAIN_ARCHITECTURE.md).

## What the Python code does

- Reads the instrument definitions from `instrument_list.yaml`
- Loads one routine from a routine CSV file
- Programs the configured gate, drain, and optional bulk/auxiliary sources
- Sweeps the selected routine parameters and records `Ids`
- Writes all measured points to CSV
- Shows a live plot while running, unless disabled

## Quick Start (Windows)

1. Create a virtual environment:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
pip install -e .
```

3. Edit `instrument_list.yaml` so the ports and SCPI commands match your hardware.

4. Run a single routine with `run_routine.py`.

## Running `run_routine.py`

The script accepts a routine index and several optional settings.
By default it uses a simpler two-wire drain measurement. Pass `--four-wire` to enable remote sense.

### Basic usage

```powershell
python run_routine.py --routine-index 0
```

### Copy/paste example

```powershell
python run_routine.py `
  --config instrument_list.yaml `
  --routines-csv "Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv" `
  --output-csv data/first_routine_measurements.csv `
  --routine-index 0 `
  --ids-settle-s 1.0
```

### Arguments

- `--config`
  - Path to the instrument list YAML file.
  - Default: `instrument_list.yaml`
- `--routines-csv`
  - Path to the routine definition CSV.
  - Default: `Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv`
- `--output-csv`
  - Path where measured points are written.
  - Default: `data/first_routine_measurements.csv`
- `--routine-index`
  - Zero-based index of the routine to run from the routine CSV.
  - Default: `0`
- `--device-flavor`, `--device-row`, `--device-col`
  - Optional scan-chain device coordinates. When supplied, the runner sends a
    `SEL` command to the Arduino before the sweep starts.
- `--device-chip`
  - Scan-chain chip index (`1` or `2`) for the selected device. Chip 1 clocks
    344 bits; chip 2 clocks 688 bits (pushing the pattern through chip 1).
  - Default: `1`
- `--no-live-plot`
  - Disables the live matplotlib plot.
- `--no-confirm-initial`
  - Skips the manual confirmation pause after the initial voltages are applied.
- `--four-wire`
  - Enables Keithley remote sense for the drain source and caps the source range at 2 V.
- `--ids-settle-s`
  - Delay in seconds before each `Ids` measurement.
  - Default: `1.0`

## Inputs

### 1. Instrument list YAML

For the SLAC rack, the current hardware mapping is:

- `keithley_2400`: Keithley 2401 through the GPIB/serial path used by the bench; drives `Vd`
- `keithley_e3631a_a`: Agilent E3631A used for `Vb` and `Vg`
- `keithley_e3631a_b`: second E3631A with the fixed manual rails for 0.9 V and 1.8 V
- `bk_9132c`: BK Precision 9132C with `vgxn` on CH1 = -0.1 V and `vgxp` on CH2 = +1.0 V
- `arduino_device_switch`: Nano R4 selector board on the configured COM port

The key safety requirement is that the 0.9 V and 1.8 V rails remain under manual control; the Python code should not toggle them in software.

The 1.8 V rail current is also monitored with an HP34401A in series on the supply line. Configure it as a current meter in [instrument_list.yaml](instrument_list.yaml):

```yaml
  hp34401a_1v8:
    type: HP34401A
    port: COM8
    baudrate: 9600
    measure_current_cmd: "MEAS:CURR:DC?"
    current_meter: true
    sample_every_n_points: 10
```

The runner records `supply_i_a` every 10th data point by default, while the Keithley continues to record the drain current at every point.

For the BK 9132C, the expected startup values are:

- CH1 -> `vgxn` = -0.1 V
- CH2 -> `vgxp` = +1.0 V
- leave CH3 disconnected / not used for this routine family

The Arduino switcher is flashed separately with the firmware under
[Arduino/unified_scan_select/](Arduino/unified_scan_select/) (see
[Arduino firmware & bench tests](#arduino-firmware--bench-tests) below). The
Python runner only sends the `SEL,<flavor_idx>,<row_idx>,<col_idx>,<chip_idx>`
command over the configured COM port at 115200 baud and waits for `SEL_DONE`.

The instrument list is the hardware configuration file consumed by the Python code.

It defines:

- Each physical instrument and its serial port
- The SCPI command strings used to program each instrument
- Which logical measurement role each instrument plays

The current file is [instrument_list.yaml](instrument_list.yaml).

Important fields:

- `instruments`
  - Contains one entry per physical instrument
- `type`
  - Identifies the instrument family, such as `Keithley2400`, `E3631A`, or `9132C`
- `port`
  - The serial port, such as `COM5`, `COM6`, or `COM7`
- `quantity` or `channel_map`
  - Maps the instrument to logical roles like `Vg`, `Vd`, `Vb`, `vgxp`, and `vgxn`

Example:

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

### 2. Arduino device selector

The scan-chain switcher is configured via [instrument_list.yaml](instrument_list.yaml) and can be changed without editing Python. This is the device-by-device selector used by the older LBL flow, now moved into the config-driven setup.

The YAML entry is intentionally separate from the electrical sources so the COM port and board variant can be changed in one place:

```yaml
instruments:
  arduino_device_switch:
    type: Arduino
    model: NANO_R4
    port: COM14
    baudrate: 115200
    ack_timeout_s: 3.0
    device_select_cmd: "SEL,{flavor_idx},{row_idx},{col_idx},{chip_idx}\n"
```

This selector is used by the routine runner when you pass the optional device
coordinates (note the `--device-chip` flag, which chooses chip 1 or chip 2 on
the series scan chain):

```powershell
python run_routine.py `
  --config instrument_list.yaml `
  --routines-csv "Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv" `
  --output-csv data/first_routine_measurements.csv `
  --routine-index 0 `
  --device-flavor 1 --device-row 1 --device-col 6 --device-chip 1
```

The Arduino firmware must be flashed onto the board separately from
[Arduino/unified_scan_select/](Arduino/unified_scan_select/); the Python script
only sends the selection command over the configured serial port. See
[Arduino firmware & bench tests](#arduino-firmware--bench-tests) for the flashing
and verification workflow.

### 3. Routine CSV file

The routine CSV tells the script which measurement to run and how to sweep it.

The current routine file is [Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv](Routines/Cryo%20PDK%20DC%20measurement%20routines%20-%20nMOS%2028nm.csv).

The script reads these columns:

- `Measurement`
- `Parameter to sweep`
- `Sweep Start`
- `Sweep Stop`
- `Num Sweep Points`
- `Parameter to Step`
- `Step Start`
- `Step Stop`
- `Num Step Points`
- `Vg Init`
- `Vb Init`
- `Vd Init`
- `Vs Init`
- `vgxp Init`
- `vgxn Init`

The `--routine-index` argument selects which row to run.

## Arduino firmware & bench tests

### Which firmware to flash

**Use [Arduino/unified_scan_select/unified_scan_select.ino](Arduino/unified_scan_select/unified_scan_select.ino).**
This is the current, authoritative sketch for the Nano R4 selector board. It
supersedes every older sketch in [Arduino/](Arduino/) and
[LBL_setup/](LBL_setup/) (those are kept only for history and are **deprecated**;
`LBL_setup/automated_arduino/automated_arduino.ino` in particular is known-broken
and must not be used).

Flash it with the Arduino IDE (board: *Arduino Nano R4* / Renesas UNO R4 core),
then confirm the serial port (COM14 on this bench) matches
[instrument_list.yaml](instrument_list.yaml).

### Serial protocol (115200 baud, newline-terminated)

Fields may be separated by commas **or** spaces. On boot the board prints a
banner ending in `READY`.

| Command | Purpose | Reply |
|---------|---------|-------|
| `SEL <flavor> <row> <col> <chip>` | Select a device. `chip=1` clocks 344 bits; `chip=2` clocks 688 bits. | `SEL_DONE` (or `SEL_FAIL` on a bad address) |
| `VERIFY <flavor> <row> <col>` | Clock the full 1032-bit chain, read SOUT back, and auto-diagnose the tap point. | report line + `VERIFY_DONE` |
| `SOUTRAW <flavor> <row> <col>` | Dump the raw `analogRead(A1)` envelope (static + shift min/max/mean). Use to tell a dead line from an under-threshold swing. | `SOUTRAW ...` + `SOUTRAW_DONE` |
| `PING` | Liveness check. | `PONG` |

### Test 1 — Arduino connection test

Confirms two-way communication with the board **before** running a routine.
Opens the port, waits for the `READY` banner, sends one command, and prints a
pass/fail verdict. Uses the port/baud from [instrument_list.yaml](instrument_list.yaml)
unless overridden.

Copy/paste:

```powershell
# Default: selects flavor 1, row 1, col 6, chip 1 and expects SEL_DONE
python test_arduino_connection.py

# Explicit coordinates / chip
python test_arduino_connection.py --flavor 1 --row 1 --col 6 --chip 1

# Pure round-trip liveness check (expects PONG)
python test_arduino_connection.py --cmd "PING"
```

A healthy run prints `SEL_DONE` (or `PONG`) and `RESULT: OK`.

### Test 2 — Scan-chain verification test

Clocks the full chain and reads SOUT (pin A1) back to confirm the scan chain is
physically working end-to-end. On this board A1 is tapped at **chip 2's SOUT**
(the end of the series chain), so a correct capture reports `tap=chip2` with
`best_offset ≈ 687`.

Copy/paste:

```powershell
# Full-chain readback + tap-point self-diagnosis
python test_arduino_connection.py --verify --flavor 1 --row 1 --col 6

# Raw A1 ADC envelope (debug a flat / floating SOUT line)
python test_arduino_connection.py --raw --flavor 1 --row 1 --col 6
```

How to read the `VERIFY` result:

- `sout_highs > 0` and `best_mismatch ≈ 0` → chain verified; `best_offset` /
  `tap` report where SOUT is tapped.
- `sout_highs = 0` → SOUT is reading flat LOW (no readback data). This is **not**
  a tap-alignment issue; check, in order: the SOUT wire to A1, a common ground
  between the Arduino and the DUT board, and that the DUT rails are powered. Run
  the `--raw` command to distinguish a truly dead line (`shift_max ≈ 0`) from a
  signal that swings but never crosses the threshold (`0 < shift_max < 100`).

### Flashing workflow summary

1. Flash [Arduino/unified_scan_select/unified_scan_select.ino](Arduino/unified_scan_select/unified_scan_select.ino)
   onto the Nano R4.
2. Run `python test_arduino_connection.py` — expect `RESULT: OK`.
3. Run `python test_arduino_connection.py --verify --flavor 1 --row 1 --col 6` to
   confirm the scan chain reads back.
4. Then run `run_routine.py` to perform measurements.

The Python code does not upload Arduino firmware for you.

## Known issues

- **SOUT scan-chain readback is non-functional (OUTSTANDING, 2026-10-25).**
  `VERIFY` / `SOUTRAW` show pin A1 floating at ~0.2–0.4 V (`sout_highs = 0`,
  `shift_max ≈ 59` of 1023) with no correlation to the driven `SIN` pattern, so
  the full-chain readback cannot be verified yet. Ruled out so far: the Arduino
  command/clock protocol (device `SEL` acks `SEL_DONE` correctly), the readback
  *software* (firmware and host verified), the SOUT tap point (confirmed A1 =
  chip-2 SOUT), SOUT wiring continuity to A1, and the DUT 0.9 V / 1.8 V rails
  (powering them changed nothing). The fault is upstream of SOUT — most likely a
  grounding/signal-integrity issue or the chip-2 output not driving a readable
  push-pull level. **Device *selection* itself is independent of this** and is
  validated by the transistor measurement, not by SOUT readback. Next debug step:
  scope the seven control/clock lines (SCLKP, SCLKN, SIN, SRST, SUPDATE, SENABLE,
  SOUT) at the chip pins during a `VERIFY` to confirm they toggle and that SOUT
  is a clean CMOS level.



