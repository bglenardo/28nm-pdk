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
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
pip install -e .
```

3. Edit serial settings and command strings in `instrument_list.yaml`:
  - Define each physical instrument once under `instruments`
  - Map logical roles like `gate_source`, `drain_source`, and `bulk_source` under `assignments`
  - Set each instrument `port` value like `COM3`, `COM4`
  - Replace command templates with the exact SCPI syntax your instruments expect

4. Run a sweep:

```powershell
iv-measure --config instrument_list.yaml
```

Or run all routines from a CSV table:

```powershell
iv-measure --config instrument_list.yaml --routines-csv "Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv" --output-csv data/nmos_routines.csv
```

5. Check results in `data/iv_curve.csv`.

## Config notes

Each physical instrument now has its own YAML entry. The measurement code still works with logical roles through the `assignments` section.

Change SCPI command strings like:

- `set_voltage_cmd`
- `measure_current_cmd`
- `output_on_cmd`
- `output_off_cmd`

`set_voltage_cmd` must include `{value}`.

If your routines vary body bias (`Vb`), assign `bulk_source` to one of the configured instruments.

Example layout:

```yaml
instruments:
  keithley_2400: ...
  keithley_e3631a_a: ...
  keithley_e3631a_b: ...
  bk_9132c: ...

assignments:
  gate_source: keithley_e3631a_a
  drain_source: keithley_2400
  bulk_source: bk_9132c
```

## CSV routine mode

Routine CSV mode reads rows with these fields:

- `Measurement`
- `Parameter to sweep`, `Sweep Start`, `Sweep Stop`, `Num Sweep Points`
- `Parameter to Step`, `Step Start`, `Step Stop`, `Num Step Points`
- `Vg Init`, `Vb Init`, `Vd Init`, `Vs Init`

Supported terminals are `Vs`, `Vd`, `Vg`, `Vb`.

For nMOS, the source is always grounded in execution. The runner enforces `Vs = 0 V` for every point.

## Safety notes

- Start with low voltage/current limits on your instruments.
- Confirm compliance/current limits manually before running automation.
- Keep a hardware emergency stop path available.

## Next upgrades

- Add compliance trip detection
- Add timestamp and temperature columns
- Add per-point averaging and retries
- Add plotting script for `ID-VDS` and `ID-VGS`
