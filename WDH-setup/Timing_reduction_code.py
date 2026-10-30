import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from Automated_code_UPDATE import IV_curve_runner 
from pathlib import Path
import time
from scipy.interpolate import interp1d
from datetime import datetime

# ---- Load data from CSV ----
def load_iv_data(csv_path, x_col="vd", y_col="id", vg_col="vg", vg_target=None, tol=1e-4):
    df = pd.read_csv(csv_path)
    
    if vg_target is not None:
        df = df[np.isclose(df[vg_col], vg_target, atol=tol)]
    
    x = df[x_col].to_numpy()
    y = df[y_col].to_numpy()
    return x, y

def compute_rmse(x1, y1, x2, y2, n_grid=500):
    # Common evaluation grid over the overlapping x-range
    lo = max(x1.min(), x2.min())
    hi = min(x1.max(), x2.max())
    x_grid = np.linspace(lo, hi, n_grid)

    # Interpolate BOTH curves onto this grid
    f1 = interp1d(x1, y1, kind='linear', bounds_error=False, fill_value='extrapolate')
    f2 = interp1d(x2, y2, kind='cubic', bounds_error=False, fill_value='extrapolate')

    y1_interp = f1(x_grid)
    y2_interp = f2(x_grid)

    rmse = np.sqrt(np.mean((y1_interp - y2_interp) ** 2))
    rel_rmse = rmse / (y2_interp.max() - y2_interp.min())
    return rmse, rel_rmse

# ---- Plot both curves ----
def plot_comparison(x1, y1, x2, y2, rmse, rel_rmse, sleep, label1, label2, points, time_taken, dir):
    plt.figure(figsize=(8, 5))
    plt.plot(x1, y1, 'b-', linewidth=1.5, label=label1)
    plt.plot(x2, y2, 'r--', linewidth=1.5, label=label2)
    plt.xlabel("vd")
    plt.ylabel("id")
    plt.title(f"RMSE = {rmse:.6f} | (Relative = {rel_rmse*100:.2f}%)\nSLEEP DURATION = {sleep} | NO OF STEPS = {points} | DURATION = {round(time_taken, 2)}")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    Path(dir).mkdir(exist_ok=True, parents=True)
    print("Saving figure")
    figure = f"{dir}/Sleep_value-{sleep}s_Points-{points}_time-{time_taken:.2f}s_error-{rel_rmse*100:.2f}%.png"
    plt.savefig(figure)
    print(f"Saved figure at ")

def plotter(inputs, sleep, points, time_taken, outpath):
    # ---- Main workflow ----
    x1, y1 = load_iv_data(inputs[0], x_col="vd", y_col="id", vg_target=0.9)
    x2, y2 = load_iv_data(inputs[1], x_col="vd", y_col="id", vg_target=0.9)

    rmse, rel_rmse = compute_rmse(x1, y1, x2, y2)

    print(f"RMSE: {rmse:.2g}")
    print(f"Relative RMSE: {rel_rmse*100:.3f}%")

    plot_comparison(x1, y1, x2, y2, rmse, rel_rmse, sleep, inputs[0], inputs[1], points, time_taken, outpath)
    return rmse, rel_rmse

import shutil

def plot_sweep_results(results, out_dir="Plots/timing_sweep_and_step_analysis"):
    """
    results: list of tuples (points, sleep, rmse, rel_rmse, time_taken)
    Produces four plots:
      1. Relative error vs number of points, one line per sleep value
      2. Relative error vs sleep value, one line per point count
      3. Time taken vs relative error (scatter, to find the efficiency frontier)
      4. A combined overview figure with all three plus a summary heatmap
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # unpack results into arrays for easier filtering
    points_arr = np.array([r[0] for r in results])
    sleep_arr = np.array([r[1] for r in results])
    rmse_arr = np.array([r[2] for r in results])
    rel_rmse_arr = np.array([r[3] for r in results]) * 100  # convert to %
    time_arr = np.array([r[4] for r in results])

    unique_points = sorted(set(points_arr))
    unique_sleeps = sorted(set(sleep_arr))

    # ---------- Plot 1: relative error vs number of points, per sleep ----------
    fig1, ax1 = plt.subplots(figsize=(8, 5))
    for sleep_val in unique_sleeps:
        mask = sleep_arr == sleep_val
        # sort by points so lines don't zig-zag
        order = np.argsort(points_arr[mask])
        ax1.plot(points_arr[mask][order], rel_rmse_arr[mask][order],
                  marker="o", label=f"settle={sleep_val}s")
    ax1.axhline(5, color="red", linestyle="--", linewidth=1, label="5% threshold")
    ax1.set_xlabel("Number of points")
    ax1.set_ylabel("Relative RMSE (%)")
    ax1.set_title("Error vs Number of Points")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)
    fig1.tight_layout()
    fig1.savefig(out_dir / "error_vs_points.png", dpi=200)
    plt.close(fig1)

    # ---------- Plot 2: relative error vs settle time, per point count ----------
    fig2, ax2 = plt.subplots(figsize=(8, 5))
    for pts_val in unique_points:
        mask = points_arr == pts_val
        order = np.argsort(sleep_arr[mask])
        ax2.plot(sleep_arr[mask][order], rel_rmse_arr[mask][order],
                  marker="o", label=f"points={pts_val}")
    ax2.axhline(5, color="red", linestyle="--", linewidth=1, label="5% threshold")
    ax2.set_xscale("log")
    ax2.set_xlabel("Settle time (s)")
    ax2.set_ylabel("Relative RMSE (%)")
    ax2.set_title("Error vs Settle Time")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3, which="both")
    fig2.tight_layout()
    fig2.savefig(out_dir / "error_vs_settle.png", dpi=200)
    plt.close(fig2)

    # ---------- Plot 3: time taken vs error (the efficiency frontier) ----------
    fig3, ax3 = plt.subplots(figsize=(8, 5))
    scatter = ax3.scatter(time_arr, rel_rmse_arr, c=points_arr, cmap="viridis", s=60)
    ax3.axhline(5, color="red", linestyle="--", linewidth=1, label="5% threshold")
    cbar = fig3.colorbar(scatter, ax=ax3)
    cbar.set_label("Number of points")
    ax3.set_xlabel("Time taken (s)")
    ax3.set_ylabel("Relative RMSE (%)")
    ax3.set_title("Time Taken vs Error (colored by point count)")
    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.3)
    fig3.tight_layout()
    fig3.savefig(out_dir / "time_vs_error.png", dpi=200)
    plt.close(fig3)

    # ---------- Plot 4: combined overview (2x2 grid) ----------
    fig4, axs = plt.subplots(2, 2, figsize=(13, 10))

    # top-left: error vs points, per sleep
    for sleep_val in unique_sleeps:
        mask = sleep_arr == sleep_val
        order = np.argsort(points_arr[mask])
        axs[0, 0].plot(points_arr[mask][order], rel_rmse_arr[mask][order],
                        marker="o", label=f"settle={sleep_val}s")
    axs[0, 0].axhline(5, color="red", linestyle="--", linewidth=1)
    axs[0, 0].set_xlabel("Number of points")
    axs[0, 0].set_ylabel("Relative RMSE (%)")
    axs[0, 0].set_title("Error vs Points")
    axs[0, 0].legend(fontsize=7)
    axs[0, 0].grid(True, alpha=0.3)

    # top-right: error vs sleep, per points
    for pts_val in unique_points:
        mask = points_arr == pts_val
        order = np.argsort(sleep_arr[mask])
        axs[0, 1].plot(sleep_arr[mask][order], rel_rmse_arr[mask][order],
                        marker="o", label=f"points={pts_val}")
    axs[0, 1].axhline(5, color="red", linestyle="--", linewidth=1)
    axs[0, 1].set_xscale("log")
    axs[0, 1].set_xlabel("Settle time (s)")
    axs[0, 1].set_ylabel("Relative RMSE (%)")
    axs[0, 1].set_title("Error vs Settle Time")
    axs[0, 1].legend(fontsize=7)
    axs[0, 1].grid(True, alpha=0.3, which="both")

    # bottom-left: time vs error scatter
    sc = axs[1, 0].scatter(time_arr, rel_rmse_arr, c=points_arr, cmap="viridis", s=60)
    axs[1, 0].axhline(5, color="red", linestyle="--", linewidth=1)
    fig4.colorbar(sc, ax=axs[1, 0], label="Number of points")
    axs[1, 0].set_xlabel("Time taken (s)")
    axs[1, 0].set_ylabel("Relative RMSE (%)")
    axs[1, 0].set_title("Time vs Error")
    axs[1, 0].grid(True, alpha=0.3)

    # bottom-right: heatmap of error across points x sleep
    grid = np.full((len(unique_points), len(unique_sleeps)), np.nan)
    for p_i, pts_val in enumerate(unique_points):
        for s_i, sleep_val in enumerate(unique_sleeps):
            mask = (points_arr == pts_val) & (sleep_arr == sleep_val)
            if mask.any():
                grid[p_i, s_i] = rel_rmse_arr[mask][0]
    im = axs[1, 1].imshow(grid, aspect="auto", cmap="viridis_r",
                            extent=[0, len(unique_sleeps), 0, len(unique_points)])
    axs[1, 1].set_xticks(np.arange(len(unique_sleeps)) + 0.5)
    axs[1, 1].set_xticklabels(unique_sleeps, rotation=45)
    axs[1, 1].set_yticks(np.arange(len(unique_points)) + 0.5)
    axs[1, 1].set_yticklabels(unique_points[::-1])
    axs[1, 1].set_xlabel("Settle time (s)")
    axs[1, 1].set_ylabel("Number of points")
    axs[1, 1].set_title("Error Heatmap (%)")
    fig4.colorbar(im, ax=axs[1, 1], label="Relative RMSE (%)")

    fig4.suptitle("Settle Time / Point Count Sweep Overview", fontsize=14)
    fig4.tight_layout()
    fig4.savefig(out_dir / "overview.png", dpi=200)
    plt.close(fig4)

    print(f"Saved 4 plots to: {out_dir.resolve()}")

def timing_runner(outpath=f"Timing_plots/"):
    today = datetime.now()
    comparison = r'Plots\runs\8-26-2026_Board_1_Chip_1_Temp_300K\NMOS_HVT\W_100n\L_1u_NF_1\csv\VDS_comparison.csv'
    SLEEP_VALS = np.linspace(0.01, 0.0001, 20)
    number_of_points = [50, 40, 30, 20, 10]

    results = []
    best_rating = None
    best_vals = None

    baseline = rf'Baselines\baseline_points_200.csv'
    # Path(baseline).parent.mkdir(parents=True, exist_ok=True)
    # shutil.copy(comparison, baseline)

    for points in number_of_points:
        # baseline = None  # reset the reference curve for each point-count group

        for SLEEP in SLEEP_VALS:
            start = time.time()
            IV_curve_runner("VDS", SLEEP, SLEEP, SLEEP, points)
            end = time.time()
            time_taken = end - start


            # if SLEEP == 1:
            #     # This is the slowest/most accurate run for this point count --
            #     # copy its output to a stable path so later runs don't overwrite it.
            #     baseline = rf'Baselines\baseline_points_{points}.csv'
            #     Path(baseline).parent.mkdir(parents=True, exist_ok=True)
            #     shutil.copy(comparison, baseline)
            #     print(f"  Baseline set for points={points}: {baseline}")
            #     # continue  # nothing meaningful to compare the baseline against itself

            rmse, rel_rmse = plotter([comparison, baseline], SLEEP, points, time_taken, outpath)
            rating = rel_rmse * time_taken
            if best_rating is None or rating < best_rating:
                best_rating = rating
                best_vals = (points, SLEEP, rmse, rel_rmse, time_taken)

            results.append((points, SLEEP, rmse, rel_rmse, time_taken))
            plot_sweep_results(results)
    # results: list of (points, sleep, rmse, rel_rmse, time_taken, csv_path)
    print(best_vals)

def main():
    timing_runner()

if __name__ == '__main__':
    main()