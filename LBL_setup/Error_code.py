import numpy as np
import pandas as pd

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
    # 10   : "PMOS_LVT",
}

SIM_CSV = "iv_bank_817.csv"
MEAS_CSV = "Full_measurement.csv"

def load_iv_data(csv_path, w, l, nf, flavor,
                  vg_col='vg', vd_col='vd', id_col='id', round_decimals=6):
    """Load a CSV and filter to a single device (w, l, nf, flavor).
    inputs are csv path, w, l, nf, and flavor. Rounds decimals to 6 places
    outputs a dataframe    
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
    """Pull out a single Id-vs-sweep_col curve at one fixed bias point.
    given a dataframe, 
    """
    sub = df[np.isclose(df[fixed_col], fixed_val, atol=tol)]
    sub = sub.sort_values(sweep_col)
    return sub[sweep_col].values, sub['id'].values


def mean_relative_error(sim_x, sim_y, meas_x, meas_y, min_current_frac=0.75):
    """Interpolate sim onto measured's x-grid, then compute mean |relative error|.
    a set of x and y values (simulated), based on one of the measured x's, simulated
    is interpolated to its ideal value. 
    """

    sim_y_interp = np.interp(meas_x, sim_x, sim_y)
    rel_err_func = lambda a, b: np.abs(a - b) / ((np.abs(a) + np.abs(b)) / 2)
    rel_err = rel_err_func(sim_y_interp, meas_y)
    
    return np.mean(rel_err)


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


def compare_curves(sim_path, meas_path, w, l, nf,
                    sim_flavor, meas_flavor,
                    min_current_frac=0.01):

    sim_df = load_iv_data(sim_path, w, l, nf, sim_flavor)
    meas_df = load_iv_data(meas_path, w, l, nf, meas_flavor)

    
    if sim_df.empty:
        raise ValueError(f"No matching rows found in simulation files for this {w}/{l}/{nf}/{sim_flavor} combo.")
    if  meas_df.empty:
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
            'w' : w,
            'l' : l,
            'nf' :nf,
            'flavor': sim_flavor,
            'vg': vg,
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
            'w' : w,
            'l' : l,
            'nf' :nf,
            'flavor': sim_flavor,
            'vd': vd,
            'mean_rel_error': mean_relative_error(sim_vg, sim_id, meas_vg, meas_id, min_current_frac),
            'vth_error': np.abs(vth_vgs_sweep(sim_vg, sim_id) - vth_vgs_sweep(meas_vg, meas_id)),
            'measure_vth': vth,
            'ion': ion, 
            'ioff': ioff, 
            'peak_gm': peak_gm
        })



    vds_df = pd.DataFrame(vds_results)
    vgs_df = pd.DataFrame(vgs_results)

    return vds_df, vgs_df

def extract_params(vgs, id_curve, vth_current=1e-7):
    id_curve = np.abs(id_curve)  # in case of sign convention issues
    ion = id_curve[-1]   # current at max Vgs
    ioff = id_curve[0]   # current at min Vgs
    gm = np.gradient(id_curve, vgs)
    peak_gm = np.max(gm)
    
    return (ion, ioff, peak_gm)


def main():

    # df = pd.read_csv("measured_PMOS_runs_818.csv")
    # print(df.head(4))
    # mask = np.isclose(df['l'], 2.65e-06) & np.isclose(df['w'], 3e-06)
    # print(mask)
    # # Create new rows: copies of the matching rows, but with updated width
    # new_rows = df.loc[mask].copy()
    # new_rows['w'] = 2.65e-06
    # new_rows['l'] = 1e-06

    # # Append these new rows to the end of the same CSV file
    # new_rows.to_csv("measured_PMOS_runs_818.csv", mode='a', header=False, index=False)

    # print(f"Appended {len(new_rows)} new rows.")

    all_vds = []
    all_vgs = []

    for flavor in FLAVOR_TABLE.keys():
        print(f"Error for flavor {flavor}")
        rows = ROW_TABLE.values()
        if flavor == 3:
            rows = ROW_TABLE_NA.values()
        for w in rows:
            cols = COL_TABLE.values()
            if flavor == 3:
                cols = COL_TABLE_NA.values()
            for l, nf in cols:
                print(f"""
                    l = {l}; w = {w}; nf = {nf}; flavor = {flavor}
                """)
                if l == 1e-06 and w == 3e-06:
                    w_temp = 2.65e-06
                else:
                    w_temp = w
                vds_df, vgs_df = compare_curves(SIM_CSV, MEAS_CSV, w_temp, l, nf, flavor, flavor)


                all_vds.append(vds_df)
                all_vgs.append(vgs_df)

    combined_vds = pd.concat(all_vds, ignore_index=True) if all_vds else pd.DataFrame()
    combined_vgs = pd.concat(all_vgs, ignore_index=True) if all_vgs else pd.DataFrame()

    if not combined_vds.empty:
        combined_vds = combined_vds.sort_values('mean_rel_error', ascending=False).reset_index(drop=True)

    if not combined_vgs.empty:
        combined_vgs = combined_vgs.sort_values('mean_rel_error', ascending=False).reset_index(drop=True)

    combined_vds.to_csv("vds_comparison_results.csv", index=False)
    combined_vgs.to_csv("vgs_comparison_results.csv", index=False)


    print("Saved vds_comparison_results.csv and vgs_comparison_results.csv")

if __name__ == "__main__":
    main()