from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SIMULATION_FILEPATH = "iv_bank_817.csv"
MEASUREMENT_FILEPATH = "Full_measurement.csv"
VG_SWEEP = True
# W_list = [100e-9, 200e-9, 400e-9, 800e-9, 1600e-9, 3000e-9]
# W_list_NA = [100e-8, 200e-8, 400e-8, 800e-8, 1600e-8, 3000e-8]
# L_list = [30e-9, 40e-9, 60e-9, 90e-9, 200e-9, 500e-9, 1000e-9]
# L_list_NA = [30e-8, 40e-8, 60e-8, 90e-9, 200e-9, 500e-9, 1000e-9]
# NF_list = [1, 2, 4]
# FLAVORS -- 0:NMOS_lvt, 1:NMOS_hvt, 2:NMOS, 3:NMOS_Na, 4:NMOS_ulvt, 
# 5:NMOS_dnw, 6:PMOS_ulvt, 7:PMOS_lvt, 8:PMOS, 9:PMOS_hvt

VG = 0.9; VD = 0;
LINESTYLES = ["-", "--", ":", "-."]

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
    idx = np.where((np.abs(x) >= 0.6) & (np.abs(x) <= 0.7))[0]
    ref = y[idx].max() if idx.size else y.max()
    thresh = frac * ref + y.min()
    order = np.argsort(y)                 # np.interp requires increasing xp
    return float(np.interp(thresh, y[order], x[order])), thresh


def _draw_source(ax, path, prefix, ls, vg_sweep, annotate, idx, W, L, NF, FLAVOR, biases=None):
    df = pd.read_csv(path)
    biases = _bias_list(path, vg_sweep) if biases is None else np.asarray(biases)
    x_col, bias_col = ("vg", "vd") if vg_sweep else ("vd", "vg")
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    is_pmos = FLAVOR >= 6
    ann_at = 0 if is_pmos else len(biases) - 1
    frac = 0.02 if vg_sweep else 0.75

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


def plot_simulated_vs_measured(inputs, output_dir, W, L, NF, FLAVOR, vg_sweep=VG_SWEEP, annotate=True, biases=None, **kwargs):
    """inputs: a path, a list of paths, or {label: path}."""
    if isinstance(inputs, (str, Path)):
        inputs = [inputs]
    if not isinstance(inputs, dict):
        inputs = {Path(p).stem: p for p in inputs}

    fig, ax = plt.subplots(figsize=(8, 5))
    for k, (label, path) in enumerate(inputs.items()):
        _draw_source(ax, path, f"{label}: ", LINESTYLES[k % len(LINESTYLES)],
                     vg_sweep, annotate, k, W, L, NF, FLAVOR, biases)

    ax.set_xlabel("Vg (V)" if vg_sweep else "Vd (V)")
    ax.set_ylabel("Id (A)")
    if kwargs:
        ax.set_title(f"W={W:g} L={L:g} nf={NF:g} flavor={FLAVOR}, {kwargs}")
    else:
        ax.set_title(f"W={W:g} L={L:g} nf={NF:g} flavor={FLAVOR}")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=7, ncol=2, bbox_to_anchor=(1.05, 1), loc="upper left", borderaxespad=0.)

    Path(f"{output_dir}").mkdir(parents=True, exist_ok=True)
    out = f"{output_dir}/{'VGS' if vg_sweep else 'VDS'}_sweep_comparison.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")
    return out


def main():
    print("running curve plotter...")
    W = 100e-9; L = 30e-9; NF = 1; FLAVOR = 0; 
    outdir = "Plots/Single_measurement"
    Path(outdir).mkdir(parents=True, exist_ok=True)
    plot_simulated_vs_measured([SIMULATION_FILEPATH, MEASUREMENT_FILEPATH], outdir, W, L, NF, FLAVOR)
    print("finished")

if __name__ == "__main__":
    main()