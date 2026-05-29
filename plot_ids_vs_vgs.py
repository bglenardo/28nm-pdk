from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt


DATA_PATH = Path("data/first_routine_measurements.csv")
OUT_PATH = Path("data/ids_vs_vgs.png")


def main() -> None:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Missing input CSV: {DATA_PATH}")

    vgs_values: list[float] = []
    ids_values: list[float] = []

    with DATA_PATH.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            vgs_values.append(float(row["vg_v"]))
            ids_values.append(float(row["drain_i_a"]))

    if not vgs_values:
        raise ValueError("No rows found in CSV; cannot plot Ids vs Vgs.")

    plt.figure(figsize=(7, 5), constrained_layout=True)
    plt.plot(vgs_values, ids_values, marker="o", linewidth=1.8, markersize=4)
    plt.xlabel("Vgs (V)")
    plt.ylabel("Ids (A)")
    plt.title("Ids vs Vgs")
    plt.grid(True, alpha=0.3)
    plt.savefig(OUT_PATH, dpi=180)
    print(f"Saved plot: {OUT_PATH}")


if __name__ == "__main__":
    main()
