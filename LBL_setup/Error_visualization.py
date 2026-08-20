import seaborn as sns
from matplotlib import pyplot as plt
import pandas as pd
import plotter_chat as pc
import numpy as np
import math
from pathlib import Path

iteration = 'flavor'
idx = 'w'
col = 'l'
SIMULATION_FILEPATH = "iv_bank_817.csv"
MEASUREMENT_FILEPATH = "Full_measurement.csv"
COMPARISON_FP = "vds_comparison_results.csv"

def error_viz(iteration, idx, col, out_dir):
    combined_vds = pd.read_csv(COMPARISON_FP)

    vmin = combined_vds['mean_rel_error'].min()
    vmax = combined_vds['mean_rel_error'].max()

    iterable = sorted(combined_vds[iteration].unique())

    nrows = 2
    ncols = math.ceil(len(iterable) / nrows)
    fig, axes = plt.subplots(nrows, ncols, figsize=(3 * nrows , 5 * ncols))
    axes = np.array(axes).flatten()  # guarantees a flat 1D array of single Axes objects

    if len(iterable) == 1:
        axes = [axes]

    for ax, flavor in zip(axes, iterable):
        subset = combined_vds[combined_vds[iteration] == flavor]
        pivot = subset.pivot_table(index=idx, columns=col, values='mean_rel_error', aggfunc='mean')
        sns.heatmap(pivot, annot=True, fmt='.2f', cmap='Reds', ax=ax, vmin=vmin, vmax=vmax)
        ax.set_title(f'{iteration} = {flavor}')

    plt.tight_layout()
    plt.show()
    out_dir = f"{out_dir}/mean_rel_error"
    Path(out_dir).mkdir(parents=True, exist_ok=True)


    fig.savefig(f'{out_dir}/it_{iteration}_row_{idx}_col_{col}.png', dpi=300, bbox_inches='tight')
    plt.close()

def max_min_plots():
    combined_vds = pd.read_csv(COMPARISON_FP)

    worst_row = combined_vds.loc[combined_vds['mean_rel_error'].idxmax()]
    best_row = combined_vds.loc[combined_vds['mean_rel_error'].idxmin()]
    
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    for ax, row, label in zip(axes, [best_row, worst_row], ['Plots/metric_plots/Best_plot', 'Plots/metric_plots/Worst_plot']):
        w = row['w']
        l = row['l']
        nf = row['nf']
        flavor = row['flavor']
        vg = row['vg']
        if label == 'Best_plot':
            error = combined_vds['mean_rel_error'].min()
        else:
            error = combined_vds['mean_rel_error'].max()
        pc.plot_simulated_vs_measured([SIMULATION_FILEPATH, MEASUREMENT_FILEPATH], label, W = w, L = l, NF = nf, FLAVOR = flavor, vg_sweep=False, error=f"{error:.4f}")

def plot_metric_bar(csv_path, metric, group_cols, out_dir=".", agg="mean"):
    """
    Bar chart of `metric` aggregated (default: mean) over one or more
    grouping columns. Error bars show the std dev across rows in each group.

    group_cols: str or list of str, e.g. "flavor" or ["flavor", "w"]
    """
    df = pd.read_csv(csv_path)
    if isinstance(group_cols, str):
        group_cols = [group_cols]

    print(df.columns.tolist())
    print(df.columns.duplicated().any())  # True if there are duplicate column names
    grouped = (
        df.groupby(group_cols)
          .agg(mean=(metric, agg), std_val=(metric, "std"))
          .reset_index()
    )
    print(grouped.head(11))
    labels = grouped[group_cols].astype(str).agg("/".join, axis=1)

    fig, ax = plt.subplots(figsize=(max(6, 0.6 * len(grouped)), 5))
    ax.bar(labels, grouped[agg], yerr=grouped["std_val"].fillna(0),
           capsize=4, color="steelblue", alpha=0.85)
    ax.set_ylabel(metric)
    ax.set_xlabel("/".join(group_cols))
    ax.set_title(f"{metric} ({agg}) by {', '.join(group_cols)}")
    ax.grid(True, axis="y", alpha=0.3)
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()

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

def main():
    csv_path = "vgs_comparison_results.csv"   # <-- update to your actual CSV path
    out_dir = "Plots/metric_plots"

    metrics = ["vth", "vth_error", "peak_gm"]
    # error_viz('flavor', 'w', 'l')
    # error_viz('vg', 'w', 'l')
    # error_viz('nf', 'w', 'l')
    print("running curve plotter...")
    max_min_plots()
    # Simple bar chart: average metric per flavor
    for metric in metrics:

        plot_metric_bar(csv_path, metric, group_cols="flavor", out_dir=out_dir)

        # Bar chart broken down further by flavor + width
        plot_metric_bar(csv_path, metric, group_cols=["flavor", "w"], out_dir=out_dir)

        # Heatmap: metric across w/l geometry, one subplot per flavor
        plot_metric_heatmap(csv_path, metric, iterate_col="flavor",
                                row_col="w", col_col="l", out_dir=out_dir)
        print("finished")

if __name__ == "__main__":
    main()