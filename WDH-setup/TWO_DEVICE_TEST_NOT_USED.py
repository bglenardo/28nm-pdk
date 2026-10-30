#!/usr/bin/env python3
"""
Device-array sweep: iterates over Flavor x Row x Column device selections
(via Arduino-controlled scan chain), and for each selected physical device
runs a configurable Vgs or Vds electrical sweep on the Keithley 2401.

For each device:
  - Arduino selects the device (flavor/row/col enable bits)
  - Keithley + PSU run the electrical sweep (Vds or Vgs mode, family of curves)
  - Measured Id is corrected by subtracting a baseline ("all devices off")
    leakage sweep, matched point-by-point on (Vgs_set, Vds_set)
  - Results (raw + corrected Id) are tagged with device metadata
    (W, L, NF, Flavor) and saved to CSV
  - A plot of the corrected Id is generated immediately after that device's
    sweep finishes, labeled with W, L, NF, and Flavor.

Keithley connection backends:
  - SLAC setup: real NI-VISA GPIB card, addressed directly via PyVISA
    (KEITHLEY_ADDR_SLAC = "GPIB1::24::INSTR").
  - LBNL setup: Keithley reached through a Prologix GPIB-USB controller,
    which requires the "++" command framing protocol over plain serial
    rather than a direct VISA resource -- handled by the PrologixGPIB
    class below, which exposes .write()/.query()/.close() so it's a
    drop-in replacement for the PyVISA instrument handle everywhere else
    in this file.

NOTE: This file is a merge of the standalone automation script and the
plotter_chat2.py module -- all plotting functions (plot_simulated_vs_measured,
plot_device_family, plot_device_family_leaksub, and their helpers) now live
directly in this file instead of being imported, so `import plotter_chat2 as pc`
and every `pc.` prefix have been removed.
"""

import csv
import time
from pathlib import Path

import pyvisa
import serial
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from datetime import datetime
from engineering_notation import EngNumber
from scipy.interpolate import interp1d
import seaborn as sns
import math

import socket
import sys
from DC_SRS import DC215


# ==================== DEVICE ARRAY LOOKUP TABLES ====================
ROW_TABLE = {
    0: 100e-9,
    1: 200e-9,
    2: 400e-9,
    3: 800e-9,
    4: 1600e-9,
    5: 3000e-9,
}

COL_TABLE = {
    0:  (30e-9,   1),
    1:  (40e-9,   1),
    2:  (60e-9,   1),
    3:  (90e-9,   1),
    4:  (200e-9,  1),
    5:  (500e-9,  1),
    6:  (1000e-9, 1),
    7:  (30e-9,   2),
    8:  (30e-9,   4),
    9:  (30e-9,   8),
    10: (40e-9,   2),
    11: (40e-9,   4),
    12: (40e-9,   8),
    13: (60e-9,   2),
    14: (60e-9,   4),
    15: (60e-9,   8),
    16: (90e-9,   2),
    17: (90e-9,   4),
    18: (90e-9,   8),
    19: (500e-9,  2),
    20: (500e-9,  4),
    21: (500e-9,  8),
    22: (1000e-9, 2),
    23: (1000e-9, 4),
    24: (1000e-9, 8),
}

ROW_TABLE_NA = {
    0: 500e-9,
    1: 750e-9,
    2: 1000e-9,
    3: 1500e-9,
    4: 2000e-9,
    5: 2500e-9,
}

COL_TABLE_NA = {
    0:  (300e-9,  1),
    1:  (500e-9,  1),
    2:  (600e-9,  1),
    3:  (900e-9,  1),
    4:  (1000e-9, 1),
    5:  (300e-9,  2),
    6:  (300e-9,  4),
    7:  (300e-9,  8),
    8:  (500e-9,  2),
    9:  (500e-9,  4),
    10: (500e-9,  8),
    11: (1000e-9, 2),
    12: (1000e-9, 4),
    13: (1000e-9, 8),
}

FLAVOR_TABLE = {
    0: "NMOS_LVT",
    1: "NMOS_HVT",
    2: "NMOS_MID",
    3: "NMOS_NA",
    4: "NMOS_ULVT",
    5: "NMOS_DNW",
    6: "PMOS_ULVT",
    7: "PMOS_LVT",
    8: "PMOS_MID",
    9: "PMOS_HVT",
}
TEMPS_AND_COMPLIANCE = {
    10 : 14e-6,
    100 : 400e-6,
    4: 3000e-3,
    77: 100e-3,
    300: 100e-3
    }

def _prompt_int_list(prompt: str, valid_values: list[int], default: list[int]) -> list[int]:
    while True:
        raw = input(f"{prompt} (comma-separated, or 'all'): ").strip()

        if raw.lower() == "":
            return default

        if raw.lower() == "all":
            return list(valid_values)

        if raw.lower() == "nmos":
            return list(valid_values[:6])

        if raw.lower() == "pmos":
            return list(valid_values[6:])
        

        try:
            values = [int(part.strip()) for part in raw.split(",") if part.strip() != ""]
        except ValueError:
            print(f"  Could not parse '{raw}' as integers. Try again.")
            continue

        invalid = [v for v in values if v not in valid_values]
        if invalid:
            print(f"  These values are not valid: {invalid}. Valid options are: {valid_values}")
            continue

        if not values:
            print("  You must enter at least one value.")
            continue

        return values

def _prompt_note_list(prompt: str):
    while True:
        raw = input(f"{prompt} (comma-separated, or 'all'): ").strip()

        if raw.lower() == "":
            return ""

        values = f"{raw.upper()}"


        invalid = raw is None 
        if invalid:
            print(f"  These values are not valid: {invalid}")
            continue

        return values
    
NOTE = _prompt_note_list("Any notes")
SWEEP_MODE = _prompt_int_list(f"Sweep mode (0 for Vds AND 1 for Vgs)", [0, 1], [0])
SWEEP_MODE = "Vgs" if SWEEP_MODE[0] == 1 else "Vds"
vgsweep = SWEEP_MODE == "Vgs"

# --- IMPORTANT: keep the raw 0/1 answer in its own variable. The old
# script overwrote Vgs_INSTRUMENT with the string "E3631A"/"RIGOL" and then
# kept indexing Vgs_INSTRUMENT[0] afterward, which silently always
# evaluated False (indexing a string's first *character*, never == 1).
# That bug made KEITHLEY_ADDR and ARDUINO_PORT always fall through to the
# LBNL branch regardless of what was actually selected here.
Vgs_INSTRUMENT_SEL = _prompt_int_list("Vgs supply (0 = Rigol PSU2 CH2, 1 = Agilent/HP E3631A)", [0, 1], [0])

TEMPERATURE = _prompt_int_list("Temperature in Kelvin", list(TEMPS_AND_COMPLIANCE.keys()), [4])
CHIP_BOARD = _prompt_int_list("Chip board ID", [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [5])
CHIP = _prompt_int_list("Keithley connected Chip", [1, 2], [2])
FLAVORS_TO_TEST = _prompt_int_list(
    "Flavor index/indices to test",
    [value + 1 for value in FLAVOR_TABLE.keys()],
    [1]
)
ROWS_TO_TEST = _prompt_int_list("Row index/indices to test", list(ROW_TABLE.keys()), [0])
COLS_TO_TEST = _prompt_int_list("Column index/indices to test", list(COL_TABLE.keys()), [6])
FLAVORS_TO_TEST = [value - 1 for value in FLAVORS_TO_TEST]
# ========================== USER CONFIG ==========================

# --- Rigol PSU addresses (VISA resource strings) ---
PSU1_ADDR = 'USB0::0x1AB1::0x0E11::DP8F262800251::INSTR'
PSU2_ADDR = 'USB0::0x1AB1::0x0E11::DP8F261000066::INSTR'

# # --- Fixed bias voltages (set once, held constant regardless of mode) ---
VGXP = 1; VGXN = 0

PSU2_CH1 = dict(volt=VGXP, curr=0.1, volt_prot=1.1,  curr_prot=0.1) #VGXP
PSU2_CH3 = dict(volt=VGXN, curr=0.1, volt_prot=-0.2, curr_prot=0.1) #VGXN
# PSU2_CH1 = dict(volt=0.9, curr=0.1, volt_prot=1.1,  curr_prot=0.1)
# PSU2_CH3 = dict(volt=0, curr=0.1, volt_prot=-0.2, curr_prot=0.1)

# --- Vgs settings (PSU2 CH2, or Agilent/HP E3631A -- selected below) ---
Vgs_CURR_LIMIT = 0.1
Vgs_VOLT_PROT  = 1.0
Vgs_CURR_PROT  = 0.1

# --- Agilent/HP E3631A: alternate Vgs source, selected at run-config time ---
RIGOL_Vgs_CHANNEL = "CH2"
E3631A_GPIB_ADDR = "GPIB0::5::INSTR"   # <-- set to your E3631A's actual GPIB address
E3631A_CHANNEL  = "P25V"   # per instrument_list.yaml (P25V -> Vg on the bench E3631A)

# --- Vds settings (Keithley 2401) ---
V_START   = 0
V_STOP    = 0.9
N_POINTS  = 25

pmos_list = np.concatenate((np.arange(0.0, 0.6, 0.05), np.array([0.6, 0.9])))
Vgs_LIST = np.concatenate((np.array([0, 0.3]), np.arange(0.35, 0.95, 0.05, float)))
Vds_LIST = np.geomspace(1e-2, 0.9, N_POINTS)

Vgs_LIST_Vgs_SWEEP = Vds_LIST
Vds_LIST_Vgs_SWEEP = Vgs_LIST

# --- Settle times ---
STEP_SETTLE_S    = 0.1
SWEEP_SETTLE_S   = 0.1
ARDUINO_SETTLE_S = 5

# --- Keithley 2401 config ---
# SLAC: real NI-VISA GPIB card, addressed directly via PyVISA.
KEITHLEY_ADDR_SLAC = "GPIB1::24::INSTR"

# LBNL: Keithley is reached through a Prologix GPIB-USB controller on a
# plain serial port -- NOT a direct VISA resource. See PrologixGPIB below.
PROLOGIX_PORT_LBNL = "COM5"   ## << NEED TO SET <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
PROLOGIX_BAUD_LBNL = 115200
GPIB_ADDR_LBNL     = 24

USE_REMOTE_SENSE = False
I_COMPLIANCE_A = 0.020

# --- Arduino (device-array scan chain control) ---
ARDUINO_PORT_SLAC = "COM13"  ## << NEED TO SET <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
ARDUINO_PORT_LBNL = "COM7"   ## << NEED TO SET <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
ARDUINO_BAUD = 9600          ## << NEED TO SET <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

# --- Baseline ("all devices off") subtraction ---
ENABLE_BASELINE_SUBTRACTION = False
BASELINE_PMOS_CSV = "Baseline_all_off_PMOS.csv"
BASELINE_NMOS_CSV = "Baseline_all_off_NMOS.csv"
BASELINE_MATCH_DECIMALS = 6
# ===================================================================


Vgs_INSTRUMENT = "E3631A" if Vgs_INSTRUMENT_SEL[0] == 1 else "RIGOL"
Vgs_CHANNEL = E3631A_CHANNEL if Vgs_INSTRUMENT == "E3631A" else RIGOL_Vgs_CHANNEL
print(f"Vgs instrument: {Vgs_INSTRUMENT} (channel {Vgs_CHANNEL})")

# True -> SLAC setup (E3631A + direct VISA GPIB Keithley), False -> LBNL
# setup (Rigol + Prologix-connected Keithley). Fixed to use the raw
# 0/1 selection instead of the shadowed Vgs_INSTRUMENT string.
USE_SLAC_SETUP = (Vgs_INSTRUMENT_SEL[0] == 1)
KEITHLEY_BACKEND = "VISA_GPIB" if USE_SLAC_SETUP else "PROLOGIX"
print(f"Keithley backend: {KEITHLEY_BACKEND}")

ARDUINO_PORT = ARDUINO_PORT_SLAC if USE_SLAC_SETUP else ARDUINO_PORT_LBNL
print(f"Arduino port: {ARDUINO_PORT}")


# ==================== PLOTTING CONFIG (merged from plotter_chat2.py) ====================
SIMULATION_FILEPATH = "Simulation_at_300K.csv"
MEASUREMENT_FILEPATH = "Full_measurement.csv"
COMPARISON_FP = "vgs_comparison_results.csv"
COMPARISON_FP_VDS = "vds_comparison_results.csv"
VG_SWEEP = False

# W_list = [100e-9, 200e-9, 400e-9, 800e-9, 1600e-9, 3000e-9]
# W_list_NA = [100e-8, 200e-8, 400e-8, 800e-8, 1600e-8, 3000e-8]
# L_list = [30e-9, 40e-9, 60e-9, 90e-9, 200e-9, 500e-9, 1000e-9]
# L_list_NA = [30e-8, 40e-8, 60e-8, 90e-9, 200e-9, 500e-9, 1000e-9]
# NF_list = [1, 2, 4]
# FLAVORS -- 0:NMOS_lvt, 1:NMOS_hvt, 2:NMOS, 3:NMOS_Na, 4:NMOS_ulvt,
# 5:NMOS_dnw, 6:PMOS_ulvt, 7:PMOS_lvt, 8:PMOS, 9:PMOS_hvt

VG = 0.9; VD = 0
LINESTYLES = ["-", "--", ":", "-."]
# ==========================================================================================


def write_settings_file(path: Path, step_settle_s: float, sweep_settle_s: float,
                         arduino_settle_s: float, n_points) -> None:
    """
    Write a human-readable summary of all instrument settings and
    device geometry being tested to a text file, for record-keeping
    alongside the CSV/plot outputs.
    """
    lines = []
    lines.append(f"Run timestamp: {datetime.now().isoformat()}")
    lines.append("=== Run metadata ===")
    lines.append(f"Sweep mode: {SWEEP_MODE}")
    lines.append(f"Chip board: {CHIP_BOARD}")
    lines.append(f"Chip: {CHIP}")
    lines.append(f"Temperature(s) (K): {TEMPERATURE}")
    lines.append(f"Flavors tested: {[FLAVOR_TABLE[f] for f in FLAVORS_TO_TEST]}")
    lines.append(f"Widths tested (Rows): {[ROW_TABLE[f] for f in ROWS_TO_TEST]}")
    lines.append(f"Lengths tested (Columns): {[COL_TABLE[f] for f in COLS_TO_TEST]}")

    if 3 in FLAVORS_TO_TEST:
        lines.append(f"NMOS_NA INCLUDED, THESE ALSO TESTED")
        lines.append(f"NA Widths tested (Rows): {[ROW_TABLE_NA[f] for f in ROWS_TO_TEST if f <= 13]}")
        lines.append(f"NA Lengths tested (Columns): {[COL_TABLE_NA[f] for f in COLS_TO_TEST if f <= 13]}")

    lines.append("=== Device geometry tested (W, L, NF) ===")
    lines.append("")

    lines.append(f"=== Keithley 2401 (backend: {KEITHLEY_BACKEND}) ===")
    if KEITHLEY_BACKEND == "VISA_GPIB":
        lines.append(f"VISA resource: {KEITHLEY_ADDR_SLAC}")
    else:
        lines.append(f"Prologix port: {PROLOGIX_PORT_LBNL}")
        lines.append(f"Prologix baud: {PROLOGIX_BAUD_LBNL}")
        lines.append(f"GPIB address: {GPIB_ADDR_LBNL}")
    lines.append(f"Remote sense (4-wire): {USE_REMOTE_SENSE}")
    lines.append(f"Current compliance (A): {I_COMPLIANCE_A}")
    lines.append(f"Step settle time (s): {step_settle_s}")
    lines.append(f"Sweep settle time (s): {sweep_settle_s}")
    lines.append(f"Arduino/device settle time (s): {arduino_settle_s}")
    lines.append(f"Number of sweep points (override, None = use default list): {n_points}")
    lines.append(f"Sweep Mode: {SWEEP_MODE}")
    if vgsweep:
        lines.append(f"Vds stepped points (Vgs sweep mode): {list(Vds_LIST_Vgs_SWEEP)}")
        lines.append(f"Vgs sweep points: {list(Vgs_LIST_Vgs_SWEEP)}")
    else:
        lines.append(f"Vgs stepped points (Vds sweep mode): {list(Vgs_LIST)}")
        lines.append(f"Vds sweep points: {list(Vds_LIST)}")
    lines.append("")

    lines.append("=== Vgs source ===")
    lines.append(f"Instrument: {Vgs_INSTRUMENT} (channel {Vgs_CHANNEL})")
    if Vgs_INSTRUMENT == "E3631A":
        lines.append(f"E3631A GPIB address: {E3631A_GPIB_ADDR}")
    lines.append("")

    lines.append("=== Rigol PSU2 (Vgs bias, CH2) ===")
    lines.append(f"Address: {PSU2_ADDR}")
    lines.append(f"Vgs sweep points (V): {list(Vgs_LIST)}")
    lines.append(f"Current limit (A): {Vgs_CURR_LIMIT}")
    lines.append(f"Voltage protection (V): {Vgs_VOLT_PROT}")
    lines.append(f"Current protection (A): {Vgs_CURR_PROT}")
    lines.append("")

    lines.append("=== Rigol PSU2 VGXP VALUES (fixed bias) ===")
    lines.extend(f"{key}: {val} " for key, val in PSU2_CH1.items())

    lines.append("=== Rigol PSU2 VGXN VALUES ===")
    lines.extend(f"{key}: {val} " for key, val in PSU2_CH3.items())
    lines.append("")

    lines.append("=== Baseline subtraction ===")
    lines.append(f"Enabled: {ENABLE_BASELINE_SUBTRACTION}")
    lines.append(f"NMOS baseline file: {BASELINE_NMOS_CSV}")
    lines.append(f"PMOS baseline file: {BASELINE_PMOS_CSV}")
    lines.append(f"Match precision (decimals): {BASELINE_MATCH_DECIMALS}")

    with open(path, "w") as f:
        f.write("\n".join(lines))


# =====================================================================================================================================
today = datetime.now()
formatted = f"{today.month}-{today.day}-{today.year}_{today.hour}h-{today.minute}m"
chip_no = f"{CHIP[0]}"
if chip_no == "3":
    chip_no = "1&2"

OUTPUT_DIR = f"Plots/runs/{formatted}_{NOTE}_Board_{CHIP_BOARD[0]}_Chip_{chip_no}_Temp_{TEMPERATURE[0]}K_VGXP_{VGXP}_VGXN_{VGXN}"
# ============================================================================================================================================


# ----------------------- Baseline subtraction helpers ------------------
def load_baseline(csv_path: str, decimals: int) -> dict:
    path = Path(csv_path)
    if not path.exists():
        print(f"WARNING: baseline file '{csv_path}' not found. "
              f"Proceeding WITHOUT baseline subtraction.")
        return {}

    lookup = {}
    with path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        required = {"vg", "vd", "id"}
        if not required.issubset(reader.fieldnames or []):
            print(f"WARNING: baseline file '{csv_path}' missing required columns "
                  f"{required}. Found: {reader.fieldnames}. "
                  f"Proceeding WITHOUT baseline subtraction.")
            return {}

        for row in reader:
            try:
                vgs = round(float(row["vg"]), decimals)
                vds = round(float(row["vd"]), decimals)
                i_base = float(row["id"])
            except (ValueError, KeyError):
                continue
            lookup[(vgs, vds)] = i_base

    print(f"Loaded {len(lookup)} baseline points from '{csv_path}'.")
    return lookup


def get_baseline_current(baseline_lookup: dict, vgs: float, vds_set: float,
                          decimals: int, missing_counter: dict) -> float:
    key = (round(vgs, 2), round(vds_set, 2))
    if key in baseline_lookup:
        return baseline_lookup[key]
    missing_counter["count"] = missing_counter.get("count", 0) + 1
    return 0.0
# ------------------------------------------------------------------


# ----------------------- PSU (pyvisa) helpers -----------------------
def configure_psu_channel(psu, channel: str, volt: float, curr: float,
                           volt_prot: float, curr_prot: float) -> None:
    psu.write(f':INST {channel}')
    psu.write(f':VOLT {volt}')
    psu.write(f':CURR {curr}')
    psu.write(f':VOLT:PROT {volt_prot}')
    psu.write(':VOLT:PROT:STAT ON')
    psu.write(f':CURR:PROT {curr_prot}')
    psu.write(':CURR:PROT:STAT ON')
    psu.write(f':OUTP {channel}, ON')


def set_vgs(vgs_dev, channel: str, voltage: float) -> None:
    """
    Set the Vgs sweep voltage on whichever instrument was selected via the
    Vgs_INSTRUMENT prompt. `vgs_dev` is the Rigol PSU2 VISA handle when
    Vgs_INSTRUMENT == "RIGOL", or the E3631A VISA handle when
    Vgs_INSTRUMENT == "E3631A" -- callers don't need to change.
    """
    if Vgs_INSTRUMENT == "E3631A":
        configure_e3631a_channel(vgs_dev, channel, voltage, Vgs_CURR_LIMIT)
    else:
        vgs_dev.write(f':INST {channel}')
        vgs_dev.write(f':VOLT {voltage}')


def turn_off_channel(psu, channel: str) -> None:
    try:
        psu.write(f':OUTP {channel}, OFF')
    except Exception:
        pass
# ---------------------------------------------------------------------


# ----------------- Agilent/HP E3631A helpers (alternate Vgs source) -----------------
def e3631a_write(dev, cmd: str) -> None:
    dev.write(cmd)

def configure_e3631a_channel(dev, channel: str, volt: float, curr: float) -> None:
    e3631a_write(dev, f"APPL {channel}, {volt:.6f}, {curr:.6f}")
    e3631a_write(dev, "OUTP ON")

def turn_off_e3631a(dev) -> None:
    try:
        e3631a_write(dev, "OUTP OFF")
    except Exception:
        pass
# ------------------------------------------------------------------


# ----------------------- Prologix GPIB-USB adapter ------------------
class PrologixGPIB:
    """
    Wraps a Prologix GPIB-USB controller (a plain USB-serial device using
    the Prologix '++' command framing) so it behaves like a PyVISA
    instrument handle everywhere else in this script -- it only needs to
    expose .write(cmd), .query(cmd), .timeout, and .close().

    This is the piece that makes the LBNL Keithley (reached through a
    Prologix adapter) work with the exact same configure_k2401_vsrc_imeas /
    measure_once / run_vds_sweep_family / run_vgs_sweep_family functions
    that were originally written assuming a direct VISA GPIB connection.
    """

    def __init__(self, port: str, baud: int, gpib_addr: int, timeout: float = 5.0):
        self._ser = serial.Serial(port, baud, timeout=0.5)
        self._ser.reset_input_buffer()
        self._ser.reset_output_buffer()
        time.sleep(0.3)
        self.timeout = timeout
        self._gpib_addr = gpib_addr
        self._init_prologix()

    def _plx_write(self, cmd: str) -> None:
        self._ser.write((cmd + "\n").encode("ascii"))
        self._ser.reset_output_buffer()

    def _init_prologix(self) -> None:
        self._plx_write("++mode 1")
        self._plx_write("++ifc")
        self._plx_write("++auto 0")
        self._plx_write("++eoi 1")
        self._plx_write("++eos 2")
        self._plx_write(f"++read_tmo_ms {int(self.timeout * 1000)}")
        self._plx_write(f"++addr {self._gpib_addr}")
        time.sleep(0.5)
        self._ser.reset_input_buffer()

    def write(self, cmd: str) -> None:
        self._plx_write(cmd)

    def query(self, cmd: str, read_timeout: float = None) -> str:
        read_timeout = self.timeout if read_timeout is None else read_timeout
        self._plx_write(cmd)
        self._plx_write("++read eoi")

        deadline = time.time() + read_timeout
        buf = b""
        while time.time() < deadline:
            if self._ser.in_waiting > 0:
                chunk = self._ser.read(self._ser.in_waiting)
                buf += chunk
                if b"\n" in chunk:
                    break
            else:
                time.sleep(0.01)
        return buf.decode(errors="ignore").strip()

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass
# ------------------------------------------------------------------
dc215 = DC215(ip="192.168.1.50", i_compliance_a=I_COMPLIANCE_A)


# ----------------------- Keithley 2401 helpers ------------------
# These work unchanged against EITHER backend (PyVISA GPIB resource or
# PrologixGPIB instance) since both expose the same .write()/.query() API.
def configure_k2401_vsrc_imeas(keithley, i_comp_a: float, use_rsen: bool) -> None:
    keithley.write("*RST")
    time.sleep(0.2)
    keithley.write(":ROUT:TERM FRONT")
    keithley.write(f":SYST:RSEN {'ON' if use_rsen else 'OFF'}")
    keithley.write(":SOUR:FUNC VOLT")
    keithley.write(":SOUR:VOLT:RANG:AUTO ON")
    keithley.write(":SENS:FUNC 'CURR'")
    keithley.write(":SENS:CURR:RANG:AUTO ON")
    keithley.write(f":SENS:CURR:PROT {i_comp_a:.6g}")
    keithley.write(":FORM:ELEM VOLT,CURR,TIME")
    keithley.write(":TRIG:COUN 1")
    keithley.write(":OUTP ON")
    time.sleep(0.3)


def measure_once(keithley):
    resp = keithley.query(":READ?").strip()
    try:
        parts = resp.split(",")
        v = float(parts[0])
        i = float(parts[1])
        t = float(parts[2])
    except Exception:
        v, i, t = float("nan"), float("nan"), float("nan")
    return v, i, t
# ------------------------------------------------------------------


# ----------------------- Arduino device-select helper ------------------
def select_device(ard: serial.Serial, flavor_idx: int, row_idx: int, col_idx: int, chip_num: int,
                   ack_timeout: float = 2.0) -> str:
    cmd = f"SEL,{flavor_idx},{row_idx},{col_idx},{chip_num}\n"
    ard.write(cmd.encode("ascii"))
    ard.flush()

    deadline = time.time() + ack_timeout
    buf = b""
    while time.time() < deadline:
        if ard.in_waiting > 0:
            buf += ard.read(ard.in_waiting)
            if b"\n" in buf:
                break
        else:
            time.sleep(0.01)
    return buf.decode(errors="ignore").strip()
# ------------------------------------------------------------------


# ----------------------- Electrical sweep routines ------------------
def run_vds_sweep_family(ser, srs, vgs_dev, vds_points, vgs_list, baseline_lookup, missing_counter, PMOS,
                          step_settle_s: float = STEP_SETTLE_S,
                          sweep_settle_s: float = SWEEP_SETTLE_S,
                          n_points=None):
    if n_points is not None:
        vds_points = np.linspace(np.min(vds_points), np.max(vds_points), n_points)

    results = []
    baseline = {}
    min_curr = 0
    if PMOS:
        vgs_list = vgs_list[::-1]
    for vgs in vgs_list:
        set_vgs(vgs_dev, Vgs_CHANNEL, vgs)
        time.sleep(step_settle_s)
        is_baseline_sweep = (vgs == 0.0 and not PMOS) or (PMOS and np.isclose(vgs, 0.90))
        for vset in vds_points:
            srs.set_voltage(vset)
            ser.write(f":SOUR:VOLT {vset:.6f}")
            time.sleep(sweep_settle_s)
            vs, i_raw, t = measure_once(ser)
            vsrs, isrs = srs.read_both()
            if vs * i_raw + vsrs * isrs >= TEMPS_AND_COMPLIANCE[TEMPERATURE[0]]:
                continue 
            if PMOS:
                vset = np.abs(vset - 0.90)
            key = (round(vset, BASELINE_MATCH_DECIMALS))
            if vset == 0:
                min_curr = i_raw if i_raw < 0 else 0
            if is_baseline_sweep:
                baseline[key] = i_raw
                i_corr = 0.0
            else:
                i_base = baseline[key]
                i_corr = i_raw - i_base

            results.append((vgs, vset, vs, i_raw, i_corr, t, vsrs, isrs))
    return results


def run_vgs_sweep_family(ser, srs, vgs_dev, vgs_list, vds_list, baseline_lookup, missing_counter, PMOS,
                          step_settle_s: float = STEP_SETTLE_S,
                          sweep_settle_s: float = SWEEP_SETTLE_S,
                          n_points=None):
    if n_points is not None:
        vgs_list = np.linspace(np.min(vgs_list), np.max(vgs_list), n_points)

    results = []
    baseline = {}
    min_curr = 0
    for vds_fixed in vds_list:
        srs.set_voltage(vds_fixed)
        ser.write(f":SOUR:VOLT {vds_fixed:.6f}")
        time.sleep(step_settle_s)
        is_baseline_sweep = (vds_fixed == 0)
        for vgs in vgs_list:
            set_vgs(vgs_dev, Vgs_CHANNEL, vgs)
            time.sleep(sweep_settle_s)
            if PMOS:
                vgs = np.abs(vgs - 0.90)
            vs, i_raw, t = measure_once(ser)
            vsrs, isrs = srs.read_both()
            if vgs == 0:
                min_curr = i_raw

            key = round(vgs, BASELINE_MATCH_DECIMALS)
            if is_baseline_sweep:
                baseline[key] = i_raw
                i_corr = 0.0
            else:
                i_base = baseline.get(key, 0.0)
                if i_base < 0:
                    i_base = 0
                i_corr = i_raw - i_base - min_curr

            results.append((vgs, vds_fixed, vs, i_raw, i_corr, t, vsrs, isrs))

    return results
# ------------------------------------------------------------------


# ==================== PLOTTING FUNCTIONS (merged from plotter_chat2.py) ====================
def near(col, df, val, rtol=1e-6):
    return np.isclose(df[col], val, rtol=rtol, atol=0)


def _bias_list(path, vg_sweep):
    """Bias points to slice at, for one data source."""
    if not vg_sweep:
        return np.array(np.arange(0, 1, 0.3))
    if "measure" in str(path):
        return np.array(np.arange(0, 1, 0.3))
    return np.linspace(0, 0.9, 51)[1::16]


def _v_at_fraction(x, y, frac=0.02):
    """V where |Id| crosses frac*max|Id|. Works for NMOS and PMOS."""
    x = np.asarray(x, dtype=float)
    y = np.abs(np.asarray(y, dtype=float))
    ref = y.max()
    thresh = frac * ref
    order = np.argsort(y)                 # np.interp requires increasing xp
    return float(np.interp(thresh, y[order], x[order])), thresh


def compute_rmse(x1, y1, x2, y2, n_grid=500):
    """
    RMSE (and relative RMSE) between two curves, evaluated on a common
    grid over their overlapping x-range. x1/y1 is interpolated linearly,
    x2/y2 is interpolated cubically (falls back to linear if x2 has < 4
    points, since cubic interpolation requires at least 4).
    """
    x1 = np.asarray(x1, dtype=float)
    y1 = np.asarray(y1, dtype=float)
    x2 = np.asarray(x2, dtype=float)
    y2 = np.asarray(y2, dtype=float)

    lo = max(x1.min(), x2.min())
    hi = min(x1.max(), x2.max())
    x_grid = np.linspace(lo, hi, n_grid)

    f1 = interp1d(x1, y1, kind='linear', bounds_error=False, fill_value='extrapolate')
    kind2 = 'cubic' if len(x2) >= 4 else 'linear'
    f2 = interp1d(x2, y2, kind=kind2, bounds_error=False, fill_value='extrapolate')

    y1_interp = f1(x_grid)
    y2_interp = f2(x_grid)

    diff = np.abs(y1_interp - y2_interp)
    error_metric = np.max(diff)
    # error_metric = np.sqrt(np.mean((y1_interp - y2_interp) ** 2))
    span = y2_interp.max() - y2_interp.min()
    rel_error_metric = error_metric / span if span != 0 else float('nan')
    return error_metric, rel_error_metric

def _draw_source(ax, path, prefix, ls, vg_sweep, annotate, idx, W, L, NF, FLAVOR, biases=None):
    df = pd.read_csv(path)
    biases = _bias_list(path, vg_sweep) if biases is None else np.asarray(biases)
    x_col, bias_col = ("vg", "vd") if vg_sweep else ("vd", "vg")
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    is_pmos = FLAVOR >= 6
    ann_at = 0 if is_pmos else len(biases) - 1
    frac = 0.02 if vg_sweep else 0.75

    curves = {}  # bias_val -> (x_array, y_array), used for RMSE comparisons

    for i, bias in enumerate(biases):
        sub = df[near("w", df, W)
                 & near("l", df, L)
                 & near("nf", df, NF)
                 & near("flavor", df, FLAVOR)
                 & near(bias_col, df, bias)]

        for (w, l, nf, bias_val, flavor), g in sub.groupby(
                ["w", "l", "nf", bias_col, "flavor"]):
            g = g.sort_values(x_col)
            color = colors[i % len(colors)]
            ax.plot(g[x_col], g["id"], color=color, ls=ls,
                    label=f"{prefix}{bias_col}={bias_val:.2f} ")

            curves[round(float(bias_val), 6)] = (g[x_col].to_numpy(dtype=float),
                                                  g["id"].to_numpy(dtype=float))

            if annotate and i == ann_at:
                v_cross, thresh = _v_at_fraction(g[x_col], g["id"], frac=frac)

                # Short marker line: only up to the curve, not the full axis
                ax.vlines(v_cross, ymin=0, ymax=thresh, color=color, ls=ls, lw=1)
                ax.plot(v_cross, thresh, "o", color=color, markersize=3)

                # Stagger labels along the right edge (axes-fraction), connected by an arrow
                y_frac = 0.95 - 0.08 * idx
                x_frac = 0.98 if is_pmos else 0.02
                ha = "right" if is_pmos else "left"

                ax.annotate(
                    f"{prefix}\nVth={v_cross:.2f} V",
                    xy=(v_cross, thresh), xycoords="data",
                    xytext=(x_frac, y_frac), textcoords="axes fraction",
                    ha=ha, va="top", fontsize=8, color=color,
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="white",
                              edgecolor=color, alpha=0.85),
                    arrowprops=dict(arrowstyle="-", color=color, alpha=0.6, lw=2,
                                     connectionstyle="arc3,rad=0.1"),
                )

    return curves


def plot_simulated_vs_measured(inputs, output_dir, W, L, NF, FLAVOR, FLAVOR_NAME,
                                temp, board, chip, pmos, vg_sweep=VG_SWEEP, annotate=True,
                                biases=None, **kwargs):
    """inputs: a path, a list of paths, or {label: path}."""
    if isinstance(inputs, (str, Path)):
        inputs = [inputs]
    if not isinstance(inputs, dict):
        inputs = {Path(p).stem: p for p in inputs}

    fig, ax = plt.subplots(figsize=(8, 5))
    source_curves = {}
    for k, (label, path) in enumerate(inputs.items()):
        source_curves[label] = _draw_source(
            ax, path, f"{label}: ", LINESTYLES[k % len(LINESTYLES)],
            vg_sweep, annotate, k, W, L, NF, FLAVOR, biases
        )

    ax.set_xlabel("Vg (V)" if vg_sweep else "Vd (V)")
    ax.set_ylabel("Id (A)")

    today_ = datetime.now()
    formatted_ = f"{today_.month}-{today_.day}-{today_.year}"
    routine_name = "Accumulation to Inversion" if vg_sweep else "Output WO Bulk"

    title = (f"{routine_name} (Comparison)\nflavor={FLAVOR + 1} {FLAVOR_NAME} | "
             f"W={EngNumber(W)} L={EngNumber(L)} nf={NF:g} | Measured on {formatted_} | "
             f"Temp={temp}K | Board-Chip={board}-{chip} | VGXP = {VGXP} | VGXN = {VGXN}")

    # --- Error measurement: RMSE between the first two data sources ---
    # (assumes inputs are ordered [simulated, measured], matching the call
    # site: [Simulation_at_300K.csv, comparison_path])
    labels = list(source_curves.keys())
    if len(labels) >= 2:
        sim_curves, meas_curves = source_curves[labels[0]], source_curves[labels[1]]
        rmses, rel_rmses = [], []
        for bias_val, (x_meas, y_meas) in meas_curves.items():
            if not sim_curves or len(x_meas) < 2:
                continue
            nearest_bias = min(sim_curves.keys(), key=lambda b: abs(b - bias_val))
            x_sim, y_sim = sim_curves[nearest_bias]
            if len(x_sim) < 2:
                continue
            rmse, rel_rmse = compute_rmse(x_sim, y_sim, x_meas, y_meas)
            rmses.append(rmse)
            rel_rmses.append(rel_rmse)
        if rmses:
            if pmos: 
                mean_rmse = float((rmses[0]))
                mean_rel_rmse = float(np.nanmean(rel_rmses[0])) * 100
                title += f"\nRMSE={EngNumber(mean_rmse)}A ({mean_rel_rmse:.2f}% of range)"
            else:
                mean_rmse = float((rmses[-1]))
                mean_rel_rmse = float(np.nanmean(rel_rmses[-1])) * 100
                title += f"\nRMSE={EngNumber(mean_rmse)}A ({mean_rel_rmse:.2f}% of range)"

    if kwargs:
        title += f" | {kwargs}"
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=7, ncol=2, bbox_to_anchor=(1.05, 1), loc="upper left", borderaxespad=0.)

    Path(f"{output_dir}").mkdir(parents=True, exist_ok=True)
    out = f"{output_dir}/Id{'Vgs' if vg_sweep else 'Vds'}_sweep_comparison.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out

def plot_device_family(results, mode, flavor_name, width, length, nf, out_path, temp, board, chip,
                        pmos: bool = False) -> str:
    """
    Save a linear + log Ids plot for one device's family-of-curves sweep
    (Vds or Vgs mode), in the same side-by-side linear/log style used by
    save_iv_plot() in the GitHub repo's run_device_loop.py: one curve per
    step value, |Drain current| labeling for PMOS devices, and a subtitle
    with device info (flavor, width, length, number of fingers, date, temp).

    results: list of (vgs, vds, vds_meas, i_raw, i_corr, t) tuples -- the
             same row format produced by run_vds_sweep_family /
             run_vgs_sweep_family in the automation script. Only vgs, vds,
             and i_corr (indices 0, 1, 4) are used.
    mode: "Vds" or "Vgs" -- which variable was swept vs. stepped.
    pmos: when True, y-axis is labeled "|Drain current| (A)" and the log
          panel plots abs(current); this function does NOT mirror the
          x-axis -- if the caller's sweep already reflects PMOS Vgs/Vds
          into physical, left-to-right values (as the automation script's
          run_vds_sweep_family/run_vgs_sweep_family do), no further
          transform is needed here.

    Returns the path the plot was saved to.
    """
    today_ = datetime.now()
    formatted_ = f"{today_.month}-{today_.day}-{today_.year}"
    device_label = (f"Flavor={flavor_name} | W={EngNumber(width)}m, "
                     f"L={EngNumber(length)}m, NF={nf} | Date = {formatted_} | "
                     f"Temp = {temp}K | Board-Chip = {board}-{chip} | VGXP = {VGXP} | VGXN = {VGXN}")

    step_param  = "Vgs" if mode == "Vds" else "Vds"

    by_step = {}
    for (vgs, vds, vs, i_raw, i_corr, t, vsrs, isrs) in results:
        step_v, sweep_v = (vgs, vsrs) if mode == "Vds" else (vsrs, vgs)
        xs, ys = by_step.setdefault(step_v, ([], []))
        xs.append(sweep_v)
        ys.append(isrs)

    fig, (ax_lin, ax_log) = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    for step_v in sorted(by_step):
        xs, ys = by_step[step_v]
        label = f"{step_param}={step_v:.3f} V"
        ax_lin.plot(xs, ys, marker="o", ms=3, lw=1.2, label=label)
        ax_log.plot(xs, [abs(y) + 1e-15 for y in ys], marker="o", ms=3, lw=1.2, label=label)

    routine_name = "Output WO Bulk" if mode == "Vds" else "Accumulation to Inversion"
    fig.suptitle(device_label, fontsize=10)
    ax_lin.set_title(f"{routine_name} (Linear)")
    ax_log.set_title(f"{routine_name} (Log)")
    ax_log.set_yscale("log")

    xlabel = f"{mode} (V)"
    ylabel = "|Drain current| (A)" if pmos else "Drain current (A)"
    for ax in (ax_lin, ax_log):
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)

    out_path = f"{out_path}.png"
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    print(f"  Saved plot -> {out_path}")
    return out_path

def plot_device_family_2(results, mode, flavor_name, width, length, nf, out_path, temp, board, chip,
                        pmos: bool = False) -> str:
    """
    Save a linear + log Ids plot for one device's family-of-curves sweep
    (Vds or Vgs mode), in the same side-by-side linear/log style used by
    save_iv_plot() in the GitHub repo's run_device_loop.py: one curve per
    step value, |Drain current| labeling for PMOS devices, and a subtitle
    with device info (flavor, width, length, number of fingers, date, temp).

    results: list of (vgs, vds, vds_meas, i_raw, i_corr, t) tuples -- the
             same row format produced by run_vds_sweep_family /
             run_vgs_sweep_family in the automation script. Only vgs, vds,
             and i_corr (indices 0, 1, 4) are used.
    mode: "Vds" or "Vgs" -- which variable was swept vs. stepped.
    pmos: when True, y-axis is labeled "|Drain current| (A)" and the log
          panel plots abs(current); this function does NOT mirror the
          x-axis -- if the caller's sweep already reflects PMOS Vgs/Vds
          into physical, left-to-right values (as the automation script's
          run_vds_sweep_family/run_vgs_sweep_family do), no further
          transform is needed here.

    Returns the path the plot was saved to.
    """
    today_ = datetime.now()
    formatted_ = f"{today_.month}-{today_.day}-{today_.year}"
    device_label = (f"Flavor={flavor_name} | W={EngNumber(width)}m, "
                     f"L={EngNumber(length)}m, NF={nf} | Date = {formatted_} | "
                     f"Temp = {temp}K | Board-Chip = {board}-{chip} | VGXP = {VGXP} | VGXN = {VGXN}")

    step_param  = "Vgs" if mode == "Vds" else "Vds"

    by_step = {}
    for (vgs, vds, vs, i_raw, i_corr, t, vsrs, isrs) in results:
        step_v, sweep_v = (vgs, vds) if mode == "Vds" else (vds, vgs)
        xs, ys = by_step.setdefault(step_v, ([], []))
        xs.append(sweep_v)
        ys.append(i_raw)

    fig, (ax_lin, ax_log) = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    for step_v in sorted(by_step):
        xs, ys = by_step[step_v]
        label = f"{step_param}={step_v:.3f} V"
        ax_lin.plot(xs, ys, marker="o", ms=3, lw=1.2, label=label)
        ax_log.plot(xs, [abs(y) + 1e-15 for y in ys], marker="o", ms=3, lw=1.2, label=label)

    routine_name = "Output WO Bulk" if mode == "Vds" else "Accumulation to Inversion"
    fig.suptitle(device_label, fontsize=10)
    ax_lin.set_title(f"{routine_name} (Linear)")
    ax_log.set_title(f"{routine_name} (Log)")
    ax_log.set_yscale("log")

    xlabel = f"{mode} (V)"
    ylabel = "|Drain current| (A)" if pmos else "Drain current (A)"
    for ax in (ax_lin, ax_log):
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)

    out_path = f"{out_path}.png"
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    print(f"  Saved plot -> {out_path}")
    return out_path

def plot_device_family_leaksub(results, mode, flavor_name, width, length, nf, out_path,
                                temp, board, chip, pmos: bool = False) -> str:
    """
    Save a 2x2 raw-vs-subtracted comparison plot for one device's
    family-of-curves sweep, matching plot_before_after() in the GitHub
    repo's leakage_subtract.py: top row = raw current (linear/log), bottom
    row = baseline-corrected current (linear/log), one line per step value.

    This only changes how the already-computed values are PLOTTED and
    SAVED -- it uses i_raw (index 3) and i_corr (index 4) straight out of
    the result tuples produced by run_vds_sweep_family/run_vgs_sweep_family,
    with no change to how those values are calculated.

    Returns the path the plot was saved to.
    """
    today_ = datetime.now()
    formatted_ = f"{today_.month}-{today_.day}-{today_.year}"
    device_label = (f"Flavor={flavor_name} | W={EngNumber(width)}m, "
                     f"L={EngNumber(length)}m, NF={nf} | Date = {formatted_} | "
                     f"Temp = {temp}K | Board-Chip = {board}-{chip} | VGXP = {VGXP} | VGXN = {VGXN}")

    step_param  = "Vgs" if mode == "Vds" else "Vds"

    by_step = {}
    for (vgs, vds, vs, i_raw, i_corr, t, vsrs, isrs) in results:
        step_v, sweep_v = (vgs, vds) if mode == "Vds" else (vds, vgs)
        xs, raw_ys, cor_ys = by_step.setdefault(step_v, ([], [], []))
        xs.append(sweep_v)
        raw_ys.append(i_raw)
        cor_ys.append(i_corr)

    fig, axes = plt.subplots(2, 2, figsize=(13, 10), constrained_layout=True)
    (ax_lin_raw, ax_log_raw), (ax_lin_cor, ax_log_cor) = axes

    for step_v in sorted(by_step):
        xs, raw_ys, cor_ys = by_step[step_v]
        label = f"{step_param}={step_v:.3f} V"
        ax_lin_raw.plot(xs, raw_ys, marker="o", ms=3, lw=1.2, label=label)
        ax_log_raw.plot(xs, [abs(y) + 1e-15 for y in raw_ys], marker="o", ms=3, lw=1.2, label=label)
        ax_lin_cor.plot(xs, cor_ys, marker="o", ms=3, lw=1.2, label=label)
        if (step_v == 0.0 and not pmos) or (pmos and np.isclose(step_v, 0.90)):
            continue
        ax_log_cor.plot(xs, [abs(y) + 1e-15 for y in cor_ys], marker="o", ms=3, lw=1.2, label=label)

    max_curr = np.max(raw_ys)
    max_power = max_curr * 0.9
    routine_name = "Output WO Bulk " if mode == "Vds" else "Accumulation to Inversion"
    ax_lin_raw.set_title(f"{routine_name} (Raw) (Linear) | Max power = {EngNumber(max_power)}W")
    ax_log_raw.set_title(f"{routine_name} (Raw) (Log)")
    ax_lin_cor.set_title(f"{routine_name} (Subtracted Leakage) (Linear)")
    ax_log_cor.set_title(f"{routine_name} (Subtracted Leakage) (Log)")
    for ax in (ax_log_raw, ax_log_cor):
        ax.set_yscale("log")

    xlabel = f"{mode} (V)"
    ylabel = "|Drain current| (A)" if pmos else "Drain current (A)"
    for ax in axes.flat:
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)

    fig.suptitle(device_label, fontsize=11)
    out_path = f"{out_path}.png"
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    print(f"  Saved leaksub plot -> {out_path}")
    return out_path


# ==================== END PLOTTING FUNCTIONS ====================

# ==================== ERROR / SIM-VS-MEASURED COMPARISON (merged from error-code script) ====================
def load_iv_data(csv_path, w, l, nf, flavor,
                  vg_col='vg', vd_col='vd', id_col='id', round_decimals=6):
    """Load a CSV and filter to a single device (w, l, nf, flavor).
    Rounds vg/vd to `round_decimals` places for consistent matching.
    """
    df = pd.read_csv(csv_path)
    mask = (
        np.isclose(df['w'], w) &
        np.isclose(df['l'], l) &
        np.isclose(df['nf'], nf) &
        np.isclose(df['flavor'], flavor)
    )
    df = df.loc[mask, [vg_col, vd_col, id_col]].copy()
    df['vg'] = df['vg'].round(round_decimals)
    df['vd'] = df['vd'].round(round_decimals)
    return df


def extract_sweep(df, fixed_col, fixed_val, sweep_col, tol=1e-6):
    """Pull out a single Id-vs-sweep_col curve at one fixed bias point."""
    sub = df[np.isclose(df[fixed_col], fixed_val, atol=tol)]
    sub = sub.sort_values(sweep_col)
    return sub[sweep_col].values, sub['id'].values


# def mean_relative_error(sim_x, sim_y, meas_x, meas_y, min_current_frac=0.75):
#     """Interpolate sim onto measured's x-grid, then compute mean |relative error|."""
#     sim_y_interp = np.interp(meas_x, sim_x, sim_y)
#     rel_err_func = lambda a, b: np.abs(a - b) / ((np.abs(a) + np.abs(b)) / 2)
#     rel_err = rel_err_func(sim_y_interp, meas_y)
#     return np.mean(rel_err)

def mean_relative_error(sim_x, sim_y, meas_x, meas_y, min_current_frac=0.75):
    """Interpolate sim onto measured's x-grid, then compute mean |relative error|."""
    sim_y_interp = np.interp(meas_x, sim_x, sim_y)
    abs_max = np.abs(sim_y_interp - meas_y)
    rel_err_func = lambda a, b: np.abs(a - b) / (np.max(a) - np.min(a))
    rel_err = rel_err_func(sim_y_interp, meas_y)
    return np.max(rel_err)


def vth_vds_sweep(x_vd, y_id, frac=0.75):
    """Vd at which |Id| first reaches frac * max(|Id|), for a fixed-Vg sweep."""
    y = np.abs(y_id)
    target = frac * np.max(y)
    order = np.argsort(y)
    return np.interp(target, y[order], x_vd[order])


def vth_vgs_sweep(x_vg, y_id, frac=0.02):
    """Vg at which |Id| first reaches min(|Id|) + frac * max(|Id|), for a fixed-Vd sweep."""
    y = np.abs(y_id)
    target = np.min(y) + frac * np.max(y)
    order = np.argsort(y)
    return np.interp(target, y[order], x_vg[order])


def extract_params(vgs, id_curve, vth_current=1e-7):
    id_curve = np.abs(id_curve)  # in case of sign convention issues
    ion = id_curve[-1]   # current at max Vgs
    ioff = id_curve[0]   # current at min Vgs
    gm = np.gradient(id_curve, vgs)
    peak_gm = np.max(gm)
    return (ion, ioff, peak_gm)


def compare_curves(sim_path, meas_path, w, l, nf,
                    sim_flavor, meas_flavor,
                    min_current_frac=0.01):

    sim_df = load_iv_data(sim_path, w, l, nf, sim_flavor)
    meas_df = load_iv_data(meas_path, w, l, nf, meas_flavor)

    if sim_df.empty:
        raise ValueError(f"No matching rows found in simulation files for this {w}/{l}/{nf}/{sim_flavor} combo.")
    if meas_df.empty:
        raise ValueError(f"No matching rows found in measurements files for this {w}/{l}/{nf}/{sim_flavor} combo.")

    vds_results = []
    meas_vg_values = sorted(meas_df['vg'].unique())
    sim_vg_values = sim_df['vg'].unique()

    for vg in meas_vg_values:
        meas_vd, meas_id = extract_sweep(meas_df, 'vg', vg, 'vd')
        nearest_vg = sim_vg_values[np.argmin(np.abs(sim_vg_values - vg))]
        sim_vd, sim_id = extract_sweep(sim_df, 'vg', nearest_vg, 'vd')

        if len(sim_vd) < 2 or len(meas_vd) < 2:
            continue

        vds_results.append({
            'w': w, 'l': l, 'nf': nf, 'flavor': sim_flavor, 'vg': vg,
            'mean_rel_error': mean_relative_error(sim_vd, sim_id, meas_vd, meas_id, min_current_frac),
            'vth_error': (vth_vds_sweep(sim_vd, sim_id) - vth_vds_sweep(meas_vd, meas_id)),
        })

    vgs_results = []
    meas_vd_values = sorted(meas_df['vd'].unique())
    sim_vd_values = sim_df['vd'].unique()

    for vd in meas_vd_values:
        meas_vg, meas_id = extract_sweep(meas_df, 'vd', vd, 'vg')
        nearest_vd = sim_vd_values[np.argmin(np.abs(sim_vd_values - vd))]
        sim_vg, sim_id = extract_sweep(sim_df, 'vd', nearest_vd, 'vg')

        if len(sim_vg) < 2 or len(meas_vg) < 2:
            continue
        vth = vth_vgs_sweep(meas_vg, meas_id)
        id_curr = np.interp(vth, meas_vg, meas_id)
        ion, ioff, peak_gm = extract_params(meas_vg, meas_id, id_curr)
        vgs_results.append({
            'w': w, 'l': l, 'nf': nf, 'flavor': sim_flavor, 'vd': vd,
            'mean_rel_error': mean_relative_error(sim_vg, sim_id, meas_vg, meas_id, min_current_frac),
            'vth_error': np.abs(vth_vgs_sweep(sim_vg, sim_id) - vth_vgs_sweep(meas_vg, meas_id)),
            'vth': vth,
            'ion': ion, 'ioff': ioff, 'peak_gm': peak_gm,
        })

    vds_df = pd.DataFrame(vds_results)
    vgs_df = pd.DataFrame(vgs_results)
    return vds_df, vgs_df


def generate_error_comparison(sim_csv=SIMULATION_FILEPATH, meas_csv=MEASUREMENT_FILEPATH,
                               vds_out="vds_comparison_results.csv",
                               vgs_out="vgs_comparison_results.csv",
                               flavors=None, rows=None, cols=None):
    """
    Compare simulated vs. measured Id curves for every device tested this
    run, and write the combined per-device error metrics out to
    vds_comparison_results.csv / vgs_comparison_results.csv. This MUST run
    before error_viz()/max_min_plots()/error_vizualize(), since those all
    read from those two CSVs.

    By default only iterates over the flavors/rows/cols you actually
    selected for this run (FLAVORS_TO_TEST/ROWS_TO_TEST/COLS_TO_TEST),
    since meas_csv will only contain those devices. Pass explicit lists
    if you want to compare against a different subset.
    """
    flavors = FLAVORS_TO_TEST if flavors is None else flavors
    rows = ROWS_TO_TEST if rows is None else rows
    cols = COLS_TO_TEST if cols is None else cols

    all_vds = []
    all_vgs = []

    for flavor_idx in flavors:
        flavor_name = FLAVOR_TABLE.get(flavor_idx)

        for row_idx in rows:
            w = ROW_TABLE_NA.get(row_idx) if flavor_name == "NMOS_NA" else ROW_TABLE.get(row_idx)

            for col_idx in cols:
                col_entry = COL_TABLE_NA.get(col_idx) if flavor_name == "NMOS_NA" else COL_TABLE.get(col_idx)
                l, nf = col_entry
                w_temp = w
                if (w == 3000e-9) and (l == 1000e-9):
                    w_temp = 2650e-9
                if (w == 2650e-9) and (l != 1000e-9):
                    w_temp = 3000e-9

                try:
                    vds_df, vgs_df = compare_curves(sim_csv, meas_csv, w_temp, l, nf, flavor_idx, flavor_idx)
                except ValueError as e:
                    print(f"  Skipping w={w_temp}, l={l}, nf={nf}, flavor={flavor_idx}: {e}")
                    continue

                all_vds.append(vds_df)
                all_vgs.append(vgs_df)

    combined_vds = pd.concat(all_vds, ignore_index=True) if all_vds else pd.DataFrame()
    combined_vgs = pd.concat(all_vgs, ignore_index=True) if all_vgs else pd.DataFrame()

    if not combined_vds.empty:
        combined_vds = combined_vds.sort_values('mean_rel_error', ascending=False).reset_index(drop=True)
        combined_vds.to_csv(vds_out, index=False)

    if not combined_vgs.empty:
        combined_vgs = combined_vgs.sort_values('mean_rel_error', ascending=False).reset_index(drop=True)
        combined_vgs.to_csv(vgs_out, index=False)

    if combined_vds.empty and combined_vgs.empty:
        print("DID NOT SAVE")

    print(f"Saved {vds_out} and {vgs_out}")
    return combined_vds, combined_vgs
    # ==================== END ERROR / COMPARISON ====================

def IV_curve_runner(SWEEP_MODE, step_settle_s: float = STEP_SETTLE_S,
                     sweep_settle_s: float = SWEEP_SETTLE_S,
                     arduino_settle_s: float = ARDUINO_SETTLE_S,
                     n_points=None):

    start = time.time()
    if SWEEP_MODE not in ("Vds", "Vgs"):
        raise ValueError(f"SWEEP_MODE must be 'Vds' or 'Vgs', got {SWEEP_MODE!r}")

    out_dir = Path(OUTPUT_DIR).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline_lookup = {}
    missing_counter = {}

    psu2 = None
    vgs_dev = None
    rm = pyvisa.ResourceManager()
    if Vgs_INSTRUMENT == "RIGOL":
        psu2 = rm.open_resource(PSU2_ADDR)
        print(psu2.query('*IDN?'))

        configure_psu_channel(psu2, 'CH1', **PSU2_CH1)
        configure_psu_channel(psu2, 'CH3', **PSU2_CH3)

        vgs_dev = psu2
        configure_psu_channel(
            vgs_dev, Vgs_CHANNEL,
            volt=Vgs_LIST[0], curr=Vgs_CURR_LIMIT,
            volt_prot=Vgs_VOLT_PROT, curr_prot=Vgs_CURR_PROT,
        )
    elif Vgs_INSTRUMENT == "E3631A":
        vgs_dev = rm.open_resource(E3631A_GPIB_ADDR)
        print(vgs_dev.query('*IDN?'))
        configure_e3631a_channel(vgs_dev, Vgs_CHANNEL, Vgs_LIST[0], Vgs_CURR_LIMIT)
    else:
        raise ValueError(f"Unknown Vgs_INSTRUMENT")

    settings_path = Path.joinpath(out_dir, "SETTINGS.txt")
    write_settings_file(settings_path, step_settle_s, sweep_settle_s, arduino_settle_s, n_points)

    arduino = serial.Serial(ARDUINO_PORT, ARDUINO_BAUD, timeout=1)
    time.sleep(2)

    all_rows = []

    # --- Keithley connection: branch on backend ---
    rm_keithley = None
    if KEITHLEY_BACKEND == "VISA_GPIB":
        rm_keithley = pyvisa.ResourceManager()
        print("VISA resources:")
        print(rm_keithley.list_resources())
        ser = rm_keithley.open_resource(KEITHLEY_ADDR_SLAC)
        ser.timeout = 5000
    else:
        print(f"Connecting to Keithley via Prologix on {PROLOGIX_PORT_LBNL} "
              f"@ GPIB addr {GPIB_ADDR_LBNL}...")
        ser = PrologixGPIB(PROLOGIX_PORT_LBNL, PROLOGIX_BAUD_LBNL, GPIB_ADDR_LBNL, timeout=5.0)

    idn = ser.query("*IDN?").strip()
    print(f"*IDN? -> {idn}")
    if not idn or "KEITHLEY" not in idn.upper():
        print("ERROR: Did not receive a valid Keithley *IDN? response.")
        ser.close()
        if rm_keithley is not None:
            rm_keithley.close()
        if dc215 is not None:
            dc215.close()
        return

    configure_k2401_vsrc_imeas(ser, I_COMPLIANCE_A, USE_REMOTE_SENSE)

    try:
        for flavor_idx in FLAVORS_TO_TEST:
            if ENABLE_BASELINE_SUBTRACTION:
                if flavor_idx > 5:
                    baseline_lookup = load_baseline(BASELINE_PMOS_CSV, BASELINE_MATCH_DECIMALS)
                else:
                    baseline_lookup = load_baseline(BASELINE_NMOS_CSV, BASELINE_MATCH_DECIMALS)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            flavor_name = FLAVOR_TABLE.get(flavor_idx)
            PMOS = flavor_idx > 5
            if flavor_name is None:
                print(f"WARNING: flavor index {flavor_idx} not in FLAVOR_TABLE, skipping.")
                continue

            for row_idx in ROWS_TO_TEST:
                if flavor_name == "NMOS_NA":
                    width = ROW_TABLE_NA.get(row_idx)
                else:
                    width = ROW_TABLE.get(row_idx)

                if width is None:
                    print(f"WARNING: row index {row_idx} not in ROW_TABLE, skipping.")
                    continue

                for col_idx in COLS_TO_TEST:
                    if flavor_name == "NMOS_NA":
                        col_entry = COL_TABLE_NA.get(col_idx)
                    else:
                        col_entry = COL_TABLE.get(col_idx)

                    if col_entry is None:
                        print(f"WARNING: col index {col_idx} not in COL_TABLE, skipping.")
                        continue
                    length, nf = col_entry

                    if (width == 3000e-9) and (length == 1000e-9):
                        width = 2650e-9
                    if (width == 2650e-9) and (length != 1000e-9):
                        width = 3000e-9

                    print(f"\n=== Device: Flavor={flavor_name} (idx {flavor_idx}), "
                          f"Row={row_idx} (W={EngNumber(width)}), Col={col_idx} (L={EngNumber(length)}, NF={nf}) ===")

                    ack = select_device(arduino, flavor_idx + 1, row_idx, col_idx, chip_num=CHIP[0])
                    print(f"  Arduino ack: {ack!r}")
                    ST = time.time()
                    time.sleep(arduino_settle_s)

                    if SWEEP_MODE == "Vds":
                        if PMOS:
                            device_results = run_vds_sweep_family(
                                                        ser, dc215, vgs_dev, Vds_LIST, pmos_list, baseline_lookup, missing_counter, PMOS,
                                                        step_settle_s=step_settle_s, sweep_settle_s=sweep_settle_s, n_points=n_points
                                                    )
                        else:
                            device_results = run_vds_sweep_family(
                                ser, dc215, vgs_dev, Vds_LIST, Vgs_LIST, baseline_lookup, missing_counter, PMOS,
                                step_settle_s=step_settle_s, sweep_settle_s=sweep_settle_s, n_points=n_points
                            )
                    else:
                        if PMOS:
                            PMOS_LIST = np.concatenate((np.arange(0.0, 0.6, 0.05), np.array([0.6, 0.9])))
                            device_results = run_vgs_sweep_family(
                                                        ser, dc215, vgs_dev, Vgs_LIST_Vgs_SWEEP, Vgs_LIST_Vgs_SWEEP, baseline_lookup, missing_counter, PMOS,
                                                        step_settle_s=step_settle_s, sweep_settle_s=sweep_settle_s, n_points=n_points
                                                    )
                        else:
                            device_results = run_vgs_sweep_family(
                                ser, dc215, vgs_dev, Vds_LIST_Vgs_SWEEP, Vgs_LIST_Vgs_SWEEP, baseline_lookup, missing_counter, PMOS,
                                step_settle_s=step_settle_s, sweep_settle_s=sweep_settle_s, n_points=n_points
                            )
                    singular = []
                    for (vgs, vds, vds_meas, i_raw, i_corr, t, vsrs, isrs) in device_results:
                        all_rows.append([
                            flavor_idx, row_idx, col_idx, flavor_name,
                            width, length, nf,
                            round(vgs, 6), round(vds, 6), vds_meas, i_corr, i_raw, t, vsrs, isrs,
                            TEMPERATURE[0], CHIP_BOARD[0], CHIP[0],
                        ])
                        singular.append([
                            flavor_idx,
                            width, length, nf,
                            vgs, vds, i_corr, i_raw,
                            TEMPERATURE[0], CHIP_BOARD[0], CHIP[0],
                        ])
                    flavor = Path(out_dir / f"{flavor_name}" / f"W_{EngNumber(width)}" / fr"L_{EngNumber(length)}_NF_{nf}")
                    flavor.mkdir(parents=True, exist_ok=True)
                    fname = f"Id{SWEEP_MODE}_CHIP1"
                    out_path = flavor / fname

                    ET = time.time()
                    print(f"runtime = {ET - ST} seconds")

                    plot_device_family(
                        device_results, SWEEP_MODE, flavor_name, width, length, nf, out_path,
                        TEMPERATURE[0], CHIP_BOARD[0], 1,
                        pmos=PMOS
                    )
                    leaksub_out_path = flavor / f"Id{SWEEP_MODE}_CHIP2"
                    plot_device_family_2(
                        device_results, SWEEP_MODE, flavor_name, width, length, nf, leaksub_out_path,
                        TEMPERATURE[0], CHIP_BOARD[0], 2,
                        pmos=PMOS
                    )

                    csv_save = Path(f"{flavor}/csv")
                    csv_save.mkdir(parents=True, exist_ok=True)
                    comparison_path = f"{SWEEP_MODE}_measurement_at_{TEMPERATURE[0]}K.csv"
                    comparison_path = Path(csv_save / comparison_path)
                    with comparison_path.open("w", newline="") as f:
                        w = csv.writer(f)
                        w.writerow([
                            "flavor", "w", "l", "nf",
                            "vg", "vd", "id", "id_raw",
                            "temperature_K", "chip_board", "chip",
                        ])
                        w.writerows(singular)
                    bias = Vds_LIST_Vgs_SWEEP if vgsweep else Vgs_LIST
                    plot_simulated_vs_measured(
                        [r"Simulation_at_300K.csv", comparison_path], flavor, width, length, nf, flavor_idx,
                        FLAVOR_TABLE.get(flavor_idx), TEMPERATURE[0], CHIP_BOARD[0], CHIP[0], pmos=PMOS,
                        vg_sweep=vgsweep, biases=bias
                    )
    except KeyboardInterrupt:
        # NEW: Ctrl-C during testing -- stop the loop but DON'T let the
        # exception propagate. Falling through normally means the
        # cleanup code below and the final CSV save still happen with
        # whatever's in all_rows so far.
        interrupted = True
        print("\n*** Ctrl-C received -- stopping sweep early and saving "
              "whatever data has been collected so far. ***")
        
    finally:
        try:
            ser.write(":OUTP OFF")
        except Exception:
            pass
        ser.close()
        if rm_keithley is not None:
            rm_keithley.close()
        if dc215 is not None:
            dc215.close()

        if Vgs_INSTRUMENT == "RIGOL" and psu2 is not None:
            print("Keep on")
            # turn_off_channel(psu2, 'CH3')
            # turn_off_channel(psu2, 'CH1')
            # turn_off_channel(psu2, 'CH2')
        elif Vgs_INSTRUMENT == "E3631A" and vgs_dev is not None:
            turn_off_e3631a(vgs_dev)

    # if psu2 is not None:
    #     psu2.close()

    if Vgs_INSTRUMENT == "E3631A" and vgs_dev is not None:
        vgs_dev.close()
    arduino.close()

    if ENABLE_BASELINE_SUBTRACTION and missing_counter.get("count", 0) > 0:
        print(f"\nWARNING: {missing_counter['count']} measurement points had no matching "
              f"baseline entry (treated as 0 correction). This usually means the baseline "
              f"sweep grid doesn't exactly match Vgs_LIST/Vds_LIST used here.")

    if not all_rows:
        print("No data collected. Exiting.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(FLAVORS_TO_TEST, ROWS_TO_TEST, COLS_TO_TEST)
    comp = Path(f"{OUTPUT_DIR}/Full_measurement_csv")
    comp.mkdir(parents=True, exist_ok=True)
    out_csv = fr"{comp}/{timestamp}.csv"
    out_csv = Path(out_csv)
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "flavor", "Row_idx", "Col_idx", "Flavor_name",
            "w", "l", "nf",
            "vg", "vd", "Vds_meas_V",
            "id", "id_raw", "time_s", "vsrs", "isrs",
            "temperature_K", "chip_board", "chip",
        ])
        w.writerows(all_rows)
    end = time.time()
    total = end - start
    print(f"\nSaved CSV -> {out_csv}, time taken = {total}")

    time_taken = [f"Time taken = {total}"]
    with open(settings_path, "a") as f:
        f.write("\n".join(time_taken) + "\n")

    return out_dir, out_csv

def error_viz(iteration, idx, col, out_dir, comparison_fp=COMPARISON_FP):
    combined_vds = pd.read_csv(comparison_fp)

    vmin = combined_vds['mean_rel_error'].min()
    vmax = combined_vds['mean_rel_error'].max()

    iterable = sorted(combined_vds[iteration].unique())

    nrows = 2
    ncols = math.ceil(len(iterable) / nrows)
    fig, axes = plt.subplots(nrows, ncols, figsize=(3 * nrows, 5 * ncols))
    axes = np.array(axes).flatten()

    for ax, flavor in zip(axes, iterable):
        subset = combined_vds[combined_vds[iteration] == flavor]
        pivot = subset.pivot_table(index=idx, columns=col, values='mean_rel_error', aggfunc='mean')
        sns.heatmap(pivot, annot=True, fmt='.2f', cmap='Reds', ax=ax, vmin=vmin, vmax=vmax)
        ax.set_title(f'{iteration} = {flavor}')

    plt.tight_layout()
    out_dir = f"{out_dir}/mean_rel_error"
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    fig.savefig(f'{out_dir}/it_{iteration}_row_{idx}_col_{col}.png', dpi=300, bbox_inches='tight')
    plt.close(fig)

def max_min_plots(out_csv, out_dir, comparison_fp=COMPARISON_FP_VDS):
    combined_vds = pd.read_csv(comparison_fp)

    nmos_mask = (combined_vds['flavor'] <= 5) & np.isclose(combined_vds['vg'], 0.9)
    pmos_mask = (combined_vds['flavor'] > 5) & np.isclose(combined_vds['vg'], 0.0)

    filtered_vds = combined_vds[nmos_mask | pmos_mask]

    worst_row = filtered_vds.loc[filtered_vds['mean_rel_error'].idxmax()]
    best_row = filtered_vds.loc[filtered_vds['mean_rel_error'].idxmin()]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    for ax, row, label in zip(axes, [best_row, worst_row], [f"{out_dir}/Best_worse_error_plots/Best_plot", f"{out_dir}/Best_worse_error_plots/Worst_plot"]):
        w = row['w']
        l = row['l']
        nf = row['nf']
        flavor = row['flavor']
        vg = row['vg']
        bias = Vds_LIST_Vgs_SWEEP if vgsweep else Vgs_LIST
        if label == 'Best_plot':
            error = combined_vds['mean_rel_error'].min()
            plot_simulated_vs_measured([SIMULATION_FILEPATH, out_csv], label, w, l, nf, flavor, FLAVOR_TABLE.get(flavor), TEMPERATURE[0], CHIP_BOARD[0], CHIP[0], pmos=(flavor > 5), vg_sweep=VG_SWEEP, biases=bias)
        else:
            error = combined_vds['mean_rel_error'].max()
            plot_simulated_vs_measured([SIMULATION_FILEPATH, out_csv], label, w, l, nf, flavor, FLAVOR_TABLE.get(flavor),TEMPERATURE[0], CHIP_BOARD[0], CHIP[0], pmos=(flavor > 5), vg_sweep=VG_SWEEP, biases=bias)

        
def plot_metric_bar(csv_path, metric, group_cols, out_dir=".", agg="mean"):
    """
    Bar chart of `metric` aggregated (default: mean) over one or more
    grouping columns. Error bars show the std dev across rows in each group.

    group_cols: str or list of str, e.g. "flavor" or ["flavor", "w"]
    """
    df = pd.read_csv(csv_path)
    if isinstance(group_cols, str):
        group_cols = [group_cols]

    grouped = (
        df.groupby(group_cols)
          .agg(mean=(metric, agg), std_val=(metric, "std"))
          .reset_index()
    )
    labels = grouped[group_cols].astype(str).agg("/".join, axis=1)
    labels = [EngNumber(label) for label in labels]
    fig, ax = plt.subplots(figsize=(max(6, 0.6 * len(grouped)), 5))
    ax.bar(labels, grouped[agg], yerr=grouped["std_val"].fillna(0),
           capsize=4, color="steelblue", alpha=0.85)
    ax.set_ylabel(metric)
    ax.set_xlabel("/".join(group_cols))
    ax.set_title(f"{metric} ({agg}) by {', '.join(group_cols)}")
    ax.grid(True, axis="y", alpha=0.3)
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()

    out_dir = f"{out_dir}/{metric}"
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    out_path = Path(out_dir) / f"{metric}_by_{'_'.join(group_cols)}.png"
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    Path(f"{out_dir}/csv").mkdir(parents=True, exist_ok=True)
    out_path_csv = f"{out_dir}/csv/{metric}_by_{'_'.join(group_cols)}.csv"
    grouped.to_csv(out_path_csv)
    print(f"Saved -> {out_path}")
    return out_path


def plot_metric_heatmap(csv_path, metric, iterate_col, row_col, col_col,
                         out_dir=".", nrows=1, cmap="viridis", agg="mean"):
    """
    Faceted heatmaps of `metric`:
      - one subplot per unique value of `iterate_col` (e.g. flavor)
      - heatmap rows = `row_col` (e.g. w)
      - heatmap columns = `col_col` (e.g. l)

    Useful for seeing how a metric (vth, peak_gm, etc.) varies across
    device geometry, split out per flavor.
    """
    df = pd.read_csv(csv_path)

    vmin = df[metric].min()
    vmax = df[metric].max()

    iterable = sorted(df[iterate_col].unique())
    ncols = math.ceil(len(iterable) / nrows)

    fig, axes = plt.subplots(nrows, ncols, figsize=(3.5 * ncols, 4.5 * nrows))
    axes = np.array(axes).reshape(-1)

    all_sub = []
    for ax, val in zip(axes, iterable):
        subset = df[df[iterate_col] == val]
        pivot = subset.pivot_table(index=row_col, columns=col_col,
                                    values=metric, aggfunc=agg)
        sns.heatmap(pivot, annot=True, fmt=".3g", cmap=cmap, ax=ax,
                    vmin=vmin, vmax=vmax)
        ax.set_title(f"{iterate_col}={val}")

        all_sub.append(subset)

    for ax in axes[len(iterable):]:
        ax.axis("off")

    fig.suptitle(f"{metric} ({agg}) by {row_col}/{col_col}, "
                 f"faceted by {iterate_col}", y=1.02)
    plt.tight_layout()
    out_dir = f"{out_dir}/{metric}"
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    out_path = Path(out_dir) / f"{metric}_by_{row_col}_{col_col}_per_{iterate_col}.png"
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    Path(f"{out_dir}/csv").mkdir(parents=True, exist_ok=True)
    out_path_csv = f"{out_dir}/csv/{metric}_by_{row_col}_{col_col}_per_{iterate_col}.csv"
    grouped = pd.concat(all_sub, ignore_index=True)
    grouped.to_csv(out_path_csv)
    print(f"Saved -> {out_path}")
    return out_path

def compute_device_max_power(csv_path,
                              group_cols=("flavor", "w", "l", "nf"),
                              v_col="vd", i_col="id_raw"):
    """
    Load a measurement CSV and compute the max power (|V * I|) seen for
    each device, where a "device" is identified by group_cols.
    """
    df = pd.read_csv(csv_path)
    df["power_W"] = (df[v_col] * df[i_col]).abs()  # per-point power
    max_power = (
        df.groupby(list(group_cols))["power_W"]
          .max()
          .reset_index()
          .rename(columns={"power_W": "max_power_W"})
    )
    return max_power


def _format_device_label(row, group_cols, geometry_cols=("w", "l")):
    """
    Build a human-readable device label from one row of grouped columns,
    using engineering notation (e.g. 1u, 500n) for geometry columns
    (width/length) instead of raw floats/scientific notation.
    """
    parts = []
    for col in group_cols:
        val = row[col]
        if col in geometry_cols:
            parts.append(f"{EngNumber(val)}m")
        else:
            parts.append(str(val))
    return "/".join(parts)


def plot_max_power_summary(max_power_df, group_cols=("flavor", "w", "l", "nf"),
                            out_dir="."):
    """
    Plot each device's max power output (one point per device on the
    x-axis), with reference threshold lines at 14 uW, 400 uW, and 10 mW.
    """
    labels = max_power_df.apply(lambda row: _format_device_label(row, group_cols), axis=1)
    powers = max_power_df["max_power_W"]

    fig, ax = plt.subplots(figsize=(max(8, 0.4 * len(labels)), 6))
    ax.plot(labels, powers, marker="o", ls="-", color="black", label="Max power")

    thresholds = [(14e-6, "14 uW", "tab:blue"),
                  (400e-6, "400 uW", "tab:orange"),
                  (10e-3, "10 mW", "tab:red")]
    for val, lbl, color in thresholds:
        ax.axhline(val, color=color, ls="--", lw=1.5, label=lbl)

    ax.set_xlabel("/".join(group_cols))
    ax.set_ylabel("Max power (W)")
    ax.set_yscale("log")
    ax.set_title("Max Power Output per Device")
    plt.xticks(rotation=90, ha="right", fontsize=7)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8)
    plt.tight_layout()

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    out_path = Path(out_dir) / "max_power_summary.png"
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved -> {out_path}")
    return out_path

def error_vizualize(meas_csv, out_dir):
    out_dir = str(out_dir)
    vds_out = f"{out_dir}/vds_comparison_results.csv"
    vgs_out = f"{out_dir}/vgs_comparison_results.csv"

    generate_error_comparison(sim_csv=SIMULATION_FILEPATH, meas_csv=meas_csv,
                               vds_out=vds_out, vgs_out=vgs_out)

    metrics = ["vth", "vth_error", "peak_gm"] 
    error_viz('flavor', 'w', 'l', out_dir, comparison_fp=vds_out)
    error_viz('vg', 'w', 'l', out_dir, comparison_fp=vds_out)
    error_viz('nf', 'w', 'l', out_dir, comparison_fp=vds_out)
    print("running curve plotter...")
    max_min_plots(meas_csv, out_dir, comparison_fp=vds_out)

    if vgs_out is not None:
        for metric in metrics:
                plot_metric_bar(vgs_out, metric, group_cols="flavor", out_dir=out_dir)
                plot_metric_bar(vgs_out, metric, group_cols=["flavor", "w"], out_dir=out_dir)
                plot_metric_heatmap(vgs_out, metric, iterate_col="flavor",
                                    row_col="w", col_col="l", out_dir=out_dir)
                print("finished")

    max_power_df = compute_device_max_power(meas_csv, group_cols=("flavor", "w", "l", "nf"))
    plot_max_power_summary(max_power_df, group_cols=("flavor", "w", "l", "nf"), out_dir=out_dir)

def main():
    measurement_dir, measurement_csv = IV_curve_runner(SWEEP_MODE)
    if not measurement_csv:
        print("No measurement data was produced; skipping error visualization.")
        return
    metrics_out_dir = (f"{OUTPUT_DIR}/metric_plots")
    Path(metrics_out_dir).mkdir(parents=True, exist_ok=True)
    error_vizualize(meas_csv=measurement_csv, out_dir=metrics_out_dir)

if __name__ == "__main__":
    main()
