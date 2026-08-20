#!/usr/bin/env python3
"""
Device-array sweep: iterates over Flavor x Row x Column device selections
(via Arduino-controlled scan chain), and for each selected physical device
runs a configurable Vgs or Vds electrical sweep on the Keithley 2401.

For each device:
  - Arduino selects the device (flavor/row/col enable bits)
  - Keithley + PSU run the electrical sweep (VDS or VGS mode, family of curves)
  - Measured Id is corrected by subtracting a baseline ("all devices off")
    leakage sweep, matched point-by-point on (Vgs_set, Vds_set)
  - Results (raw + corrected Id) are tagged with device metadata
    (W, L, NF, Flavor) and saved to CSV
  - A plot of the corrected Id is generated immediately after that device's
    sweep finishes, labeled with W, L, NF, and Flavor.
"""

import csv
import time
from pathlib import Path

import pyvisa
import serial
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime
import plotter_chat as pc



# ========================== USER CONFIG ==========================

SWEEP_MODE = "VDS"   # "VDS" or "VGS" -- electrical sweep type run on each device
vgsweep = SWEEP_MODE == "VGS"

# --- Rigol PSU addresses (VISA resource strings) ---
PSU1_ADDR = 'USB0::0x1AB1::0x0E11::DP8F262800251::INSTR'
PSU2_ADDR = 'USB0::0x1AB1::0x0E11::DP8F261000066::INSTR'

# --- Fixed bias voltages (set once, held constant regardless of mode) ---
# PSU1_CH1 = dict(volt=0.9, curr=0.1, volt_prot=1.0,  curr_prot=0.01)
# PSU1_CH2 = dict(volt=1.8, curr=0.1, volt_prot=1.9,  curr_prot=0.01)
PSU2_CH1 = dict(volt=1, curr=0.1, volt_prot=1.1,  curr_prot=0.1)
PSU2_CH3 = dict(volt=-0.1, curr=0.1, volt_prot=-0.2, curr_prot=0.1)

# --- Vgs settings (PSU2 CH2) ---
VGS_LIST = np.arange(0, 1, 0.3)
VGS_CURR_LIMIT = 0.1
VGS_VOLT_PROT  = 1.0
VGS_CURR_PROT  = 0.1
VGS_SETTLE_S   = 1.0


# --- Vds settings (Keithley 2401) ---
V_START   = 0.0
V_STOP    = 0.9
N_POINTS  = 10
SETTLE_S  = 1

VDS_LIST = np.linspace(V_START, V_STOP, N_POINTS)
print(VDS_LIST)

VGS_LIST_VGS_SWEEP = np.linspace(0, 0.9, N_POINTS)
VDS_LIST_VGS_SWEEP = np.linspace(V_START, V_STOP, 3)


# --- Keithley 2401 / Prologix config ---
PROLOGIX_PORT = "COM5"
PROLOGIX_BAUD = 115200
GPIB_ADDR     = 24
USE_REMOTE_SENSE = False
I_COMPLIANCE_A = 0.3

# --- Arduino (device-array scan chain control) ---
ARDUINO_PORT = "COM7" ## << NEED TO SET <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
ARDUINO_BAUD = 9600 ## << NEED TO SET <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
DEVICE_SETTLE_S = 0.5

OUTPUT_CSV = "device_array_sweep" ## << NEED TO SET <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
OUTPUT_DIR = "Plots" ## << NEED TO SET <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

# --- Baseline ("all devices off") subtraction ---
ENABLE_BASELINE_SUBTRACTION = True
BASELINE_PMOS_CSV = "Baseline_all_off_PMOS.csv"   # must have columns: Vgs_set_V, Vds_set_V, Id_A
BASELINE_NMOS_CSV = "Baseline_all_off_NMOS.csv"
BASELINE_MATCH_DECIMALS = 6             # rounding precision used to match setpoints
# ===================================================================


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
    9:   (30e-9,   8),
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
    0:  (300e-9,   1),
    1:  (500e-9,   1),
    2:  (600e-9,   1),
    3:  (900e-9,   1),
    4:  (1000e-9,  1),
    5:  (300e-9,  2),
    6:  (300e-9, 4),
    7:  (300e-9,   8),
    8:  (500e-9,   2),
    9:  (500e-9,   4),
    10: (500e-9,   8),
    11: (1000e-9,   2),
    12: (1000e-9,   4),
    13: (1000e-9,   8),
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
    10   : "PMOS_LVT",
}


def _prompt_int_list(prompt: str, valid_values: list[int]) -> list[int]:
    while True:
        raw = input(f"{prompt} (comma-separated, or 'all'): ").strip()

        if raw.lower() == "all":
            return list(valid_values)

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

FLAVORS_TO_TEST = _prompt_int_list("Flavor index/indices to test", list(FLAVOR_TABLE.keys()))
ROWS_TO_TEST = _prompt_int_list("Row index/indices to test", list(ROW_TABLE.keys()))
COLS_TO_TEST = _prompt_int_list("Column index/indices to test", list(COL_TABLE.keys()))
# ===================================================================


# ----------------------- Baseline subtraction helpers ------------------
def load_baseline(csv_path: str, decimals: int) -> dict:
    """
    Load an 'all devices off' baseline sweep and build a lookup table keyed
    by (round(vg, decimals), round(vd, decimals)) -> baseline Id (A).

    Expects a CSV with at least the columns: vg, vd, id.
    Returns an empty dict (with a warning) if the file can't be found or
    parsed, so callers can gracefully fall back to no correction.
    """
    path = Path(csv_path)
    if not path.exists():
        print(f"WARNING: baseline file '{csv_path}' not found. "
              f"Proceeding WITHOUT baseline subtraction.")
        return {}

    lookup = {}
    with path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        required = {"vg", "vd", "id"}
        if not required.issubset(reader.fieldnames or []): # Checks and make sure in piece and if not throws error and it doesn't work
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
    """
    Look up the baseline leakage current for a given (vgs, vds) pair.
    Returns 0.0 (no correction) and tallies a miss if the exact setpoint
    isn't found in the baseline data -- this usually means the baseline
    sweep grid doesn't match the current sweep grid.
    """
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


def set_vgs(psu2, channel: str, voltage: float) -> None:
    psu2.write(f':INST {channel}')
    psu2.write(f':VOLT {voltage}')


def turn_off_channel(psu, channel: str) -> None:
    try:
        psu.write(f':OUTP {channel}, OFF')
    except Exception:
        pass
# ---------------------------------------------------------------------


# ----------------------- Prologix / Keithley helpers ------------------
def plx_write(ser: serial.Serial, cmd: str, delay: float = 0.0) -> None:
    ser.write((cmd + "\n").encode("ascii"))
    ser.reset_output_buffer()
    if delay:
        time.sleep(delay)


def plx_query(ser: serial.Serial, cmd: str, read_timeout: float = 3.0) -> str:
    plx_write(ser, cmd)
    plx_write(ser, "++read eoi")

    deadline = time.time() + read_timeout
    buf = b""
    while time.time() < deadline:
        if ser.in_waiting > 0:
            chunk = ser.read(ser.in_waiting)
            buf += chunk
            if b"\n" in chunk:
                break
        else:
            time.sleep(0.01)

    return buf.decode(errors="ignore").strip()


def init_prologix(ser: serial.Serial, addr: int) -> None:
    plx_write(ser, "++mode 1")
    plx_write(ser, "++ifc")
    plx_write(ser, "++auto 0")
    plx_write(ser, "++eoi 1")
    plx_write(ser, "++eos 2")
    plx_write(ser, "++read_tmo_ms 5000")
    plx_write(ser, f"++addr {addr}")
    time.sleep(0.5)
    ser.reset_input_buffer()


def configure_k2401_vsrc_imeas(ser: serial.Serial, i_comp_a: float, use_rsen: bool) -> None:
    plx_write(ser, "*RST")
    time.sleep(0.3)
    plx_write(ser, ":ROUT:TERM FRONT")
    plx_write(ser, f":SYST:RSEN {'ON' if use_rsen else 'OFF'}")
    plx_write(ser, ":SOUR:FUNC VOLT")
    plx_write(ser, ":SOUR:VOLT:RANG:AUTO ON")
    plx_write(ser, ":SENS:FUNC 'CURR'")
    plx_write(ser, ":SENS:CURR:RANG:AUTO ON")
    plx_write(ser, f":SENS:CURR:PROT {i_comp_a:.6g}")
    plx_write(ser, ":FORM:ELEM VOLT,CURR,TIME")
    plx_write(ser, ":TRIG:COUN 1")
    plx_write(ser, ":INIT:CONT OFF")
    plx_write(ser, ":OUTP ON")
    time.sleep(0.3)


def measure_once(ser: serial.Serial):
    resp = plx_query(ser, ":READ?")
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
def select_device(ard: serial.Serial, flavor_idx: int, row_idx: int, col_idx: int,
                   ack_timeout: float = 2.0) -> str:
    cmd = f"SEL,{flavor_idx},{row_idx},{col_idx}\n"
    print(cmd)
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
def run_vds_sweep_family(ser, psu2, vds_points, vgs_list, baseline_lookup, missing_counter, PMOS):
    """
    VDS mode: for each Vgs in vgs_list, sweep Vds and measure Id.
    Each point's baseline leakage current is subtracted using the
    (Vgs_set, Vds_set) lookup. Returns rows of
    (vgs, vds_set, vds_meas, id_raw, id_corrected, t).
    """
    results = []
    for vgs in vgs_list:
        set_vgs(psu2, 'CH2', vgs)
        time.sleep(VGS_SETTLE_S)
        for vset in vds_points:
            plx_write(ser, f":SOUR:VOLT {vset:.6f}")
            time.sleep(SETTLE_S)
            vs, i_raw, t = measure_once(ser)
            if PMOS:
                vset = np.abs(vset - 0.90)
            i_base = get_baseline_current(baseline_lookup, vgs,  vset, ## IF NOT ENABLE (I.E. FIRST RUN, RETURNS 0)
                                           BASELINE_MATCH_DECIMALS, missing_counter)
            i_corr = i_raw - i_base ## FIX LATER ===============================================================
            # i_corr = i_raw - 0
            results.append((vgs, vset, vs, i_raw, i_corr, t))
    return results


def run_vgs_sweep_family(ser, psu2, vgs_list, vds_list, baseline_lookup, missing_counter, PMOS):
    """
    VGS mode: for each fixed Vds in vds_list, sweep Vgs and measure Id.
    Baseline-corrected the same way as the VDS routine above.
    """
    results = []
    for vds_fixed in vds_list:
        plx_write(ser, f":SOUR:VOLT {vds_fixed:.6f}")
        time.sleep(SETTLE_S)
        for vgs in vgs_list:
            set_vgs(psu2, 'CH2', vgs)
            time.sleep(VGS_SETTLE_S)
            if PMOS:
                vgs = np.abs(vgs - 0.90)
            vs, i_raw, t = measure_once(ser)
            i_base = get_baseline_current(baseline_lookup, vgs, vds_fixed, ## IF NOT ENABLE (I.E. FIRST RUN, RETURNS 0)
                                           BASELINE_MATCH_DECIMALS, missing_counter)
            i_corr = i_raw - i_base
            results.append((vgs, vds_fixed, vs, i_raw, i_corr, t))
    return results
# ------------------------------------------------------------------

def plot_device_family(results, mode, flavor_name, width, length, nf, out_path: Path):
    """
    Save a plot for one device's family-of-curves sweep, using the
    baseline-corrected current (index 4 in each result tuple), labeled
    with device info (width, length, number of fingers, flavor).
    """
    device_label = f"W={width}m, L={length}m, NF={nf}, Flavor={flavor_name}"

    plt.figure()
    if mode == "VDS":
        vgs_values = sorted(set(r[0] for r in results))
        for vgs in vgs_values:
            subset = [r for r in results if r[0] == vgs]
            vds_list = [r[1] for r in subset]
            id_list = [r[4] for r in subset]   # corrected Id
            plt.plot(vds_list, id_list, marker="o", label=f"Vgs={vgs:.2f} V")
        plt.xlabel("Vds (V)")
        plt.title(f"Id vs Vds (baseline-subtracted)\n{device_label}")
    else:
        vds_values = sorted(set(r[1] for r in results))
        for vds_fixed in vds_values:
            subset = [r for r in results if r[1] == vds_fixed]
            vgs_list = [r[0] for r in subset]
            id_list = [r[4] for r in subset]   # corrected Id

            plt.plot(vgs_list, id_list, marker="o", label=f"Vds={vds_fixed:.2f} V")
        plt.xlabel("Vgs (V)")
        plt.title(f"Id vs Vgs (baseline-subtracted)\n{device_label}")

    plt.ylabel("Id (A)")
    plt.legend(bbox_to_anchor=(1.05, 1), loc="upper left", borderaxespad=0.)
    plt.grid(True)
    out_path = fr"{out_path}.png"
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  Saved plot -> {out_path}")


def main():
    if SWEEP_MODE not in ("VDS", "VGS"):
        raise ValueError(f"SWEEP_MODE must be 'VDS' or 'VGS', got {SWEEP_MODE!r}")

    out_csv = Path(OUTPUT_CSV).resolve()
    out_dir = Path(OUTPUT_DIR).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load the "all devices off" baseline sweep, if enabled.
    baseline_lookup = {}
    missing_counter = {}  # tallies (Vgs, Vds) points with no matching baseline entry

    rm = pyvisa.ResourceManager()
    print(rm.list_resources())

    # psu = rm.open_resource(PSU1_ADDR)
    psu2 = rm.open_resource(PSU2_ADDR)
    # print(psu.query('*IDN?'))
    print(psu2.query('*IDN?'))

    # configure_psu_channel(psu, 'CH1', **PSU1_CH1)
    # configure_psu_channel(psu, 'CH2', **PSU1_CH2)
    configure_psu_channel(psu2, 'CH1', **PSU2_CH1)
    configure_psu_channel(psu2, 'CH3', **PSU2_CH3)
    configure_psu_channel(
        psu2, 'CH2',
        volt=VGS_LIST[0], curr=VGS_CURR_LIMIT,
        volt_prot=VGS_VOLT_PROT, curr_prot=VGS_CURR_PROT,
    )

    arduino = serial.Serial(ARDUINO_PORT, ARDUINO_BAUD, timeout=1)
    time.sleep(2)

    all_rows = []

    with serial.Serial(PROLOGIX_PORT, PROLOGIX_BAUD, timeout=0.5) as ser:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        time.sleep(0.3)

        init_prologix(ser, GPIB_ADDR)

        idn = plx_query(ser, "*IDN?")
        print(f"*IDN? -> {idn}")
        if not idn or "KEITHLEY" not in idn.upper():
            print("ERROR: Did not receive a valid Keithley *IDN? response.")
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

                        print(f"\n=== Device: Flavor={flavor_name} (idx {flavor_idx}), "
                              f"Row={row_idx} (W={width}m), Col={col_idx} (L={length}m, NF={nf}) ===")
                        
                        ack = select_device(arduino, flavor_idx + 1, row_idx, col_idx)
                        print(f"  Arduino ack: {ack!r}")
                        time.sleep(DEVICE_SETTLE_S)
                        if SWEEP_MODE == "VDS":
                            device_results = run_vds_sweep_family(
                                ser, psu2, VDS_LIST, VGS_LIST, baseline_lookup, missing_counter, (flavor_idx > 5)
                            )
                        else:
                            device_results = run_vgs_sweep_family(
                                ser, psu2, VGS_LIST_VGS_SWEEP, VDS_LIST_VGS_SWEEP, baseline_lookup, missing_counter, (flavor_idx > 5)
                            )
                        singular = []
                        for (vgs, vds, vds_meas, i_raw, i_corr, t) in device_results:
                            all_rows.append([
                                flavor_idx, row_idx, col_idx, flavor_name,
                                width, length, nf,
                                vgs, vds, vds_meas, i_corr, i_raw, t
                            ])
                            singular.append([
                                                            flavor_idx,
                                                            width, length, nf,
                                                            vgs, vds, i_corr, 
                                                        ])
                        flavor = Path(out_dir / f"{flavor_name}" / f"W_{width}" / fr"L_{length}_NF_{nf}" )
                        flavor.mkdir(parents=True, exist_ok=True)
                        fname = f"{SWEEP_MODE}_singular"
                        out_path = flavor / fname
                        plot_device_family(
                            device_results, f"{SWEEP_MODE}", flavor_name, width, length, nf, out_path
                        )

                        csv_save = Path(f"{flavor}/csv")
                        csv_save.mkdir(parents=True, exist_ok=True)
                        comparison_path = rf"{SWEEP_MODE}_comparison.csv"
                        comparison_path = Path(csv_save / comparison_path)
                        with comparison_path.open("w", newline="") as f:
                                w = csv.writer(f)
                                w.writerow([
                                    "flavor", "w", "l", "nf",
                                    "vg", "vd", "id",
                                ])
                                w.writerows(singular)
                        bias = VDS_LIST_VGS_SWEEP if vgsweep else VGS_LIST
                        pc.plot_simulated_vs_measured([r"iv_bank_817.csv", comparison_path], flavor, width, length, nf, flavor_idx, vg_sweep=vgsweep, biases=bias)

        finally:
            plx_write(ser, ":OUTP OFF")
            turn_off_channel(psu2, 'CH3')
            turn_off_channel(psu2, 'CH1')
            turn_off_channel(psu2, 'CH2')
            # turn_off_channel(psu, 'CH1')
            # turn_off_channel(psu, 'CH2')

    psu2.close()
    # psu2.close()
    arduino.close()

    if ENABLE_BASELINE_SUBTRACTION and missing_counter.get("count", 0) > 0:
        print(f"\nWARNING: {missing_counter['count']} measurement points had no matching "
              f"baseline entry (treated as 0 correction). This usually means the baseline "
              f"sweep grid doesn't exactly match VGS_LIST/VDS_LIST used here.")

    if not all_rows:
        print("No data collected. Exiting.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(FLAVORS_TO_TEST, ROWS_TO_TEST, COLS_TO_TEST)
    comp = Path(f"Full_measurement_runs")
    comp.mkdir(parents=True, exist_ok=True)
    out_csv = fr"{comp}/{timestamp}.csv"
    out_csv = Path(out_csv)
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "flavor", "Row_idx", "Col_idx", "Flavor_name",
            "w", "l", "nf",
            "vg", "vd", "Vds_meas_V",
            "id", "id_2", "time_s"
        ])
        w.writerows(all_rows)
    print(f"\nSaved CSV -> {out_csv}")


if __name__ == "__main__":
    main()