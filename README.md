# Transistor I-V Measurement Starter

This project gives you a clean baseline for automating transistor I-V measurements using instruments connected through USB-to-RS232 adapters.

## What it does

- Talks to two serial instruments:
  - `gate_source`: sets gate voltage
  - `drain_source`: sets drain voltage and reads drain current
- Sweeps `VDS` for each `VGS`
- Saves all measurement points to CSV
- Can run a full table of routines from a CSV file

## Quick Start (Windows)

1. Create a virtual environment:

```powershell
py -3 -m venv .venv
# Transistor I-V Measurement Starter

This project provides a Python interface for transistor I-V measurements using instruments connected through USB-to-RS232 adapters.

The main entry point for a single measurement routine is `run_first_routine.py`.

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

4. Run a single routine with `run_first_routine.py`.

## Running `run_first_routine.py`

The script accepts a routine index and several optional settings.

### Basic usage

```powershell
python run_first_routine.py --routine-index 0
```

### Copy/paste example

```powershell
python run_first_routine.py `
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
- `--no-live-plot`
  - Disables the live matplotlib plot.
- `--no-confirm-initial`
  - Skips the manual confirmation pause after the initial voltages are applied.
- `--ids-settle-s`
  - Delay in seconds before each `Ids` measurement.
  - Default: `1.0`

## Inputs

### 1. Instrument list YAML

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

### 2. Routine CSV file

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

## Arduino requirement

For now, the Arduino code must be loaded onto the board independently before running the Python scripts.

In other words:

1. Flash the Arduino separately using the code in [Arduino/](Arduino/)
2. Verify the board is running the expected firmware
3. Then run `run_first_routine.py` to operate the instruments

The Python code does not upload Arduino firmware for you.

