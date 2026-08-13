"""test_pmos_plot.py -- offline check of the PMOS plot axes. NO INSTRUMENTS.

Exercises ONLY run_device_loop.save_iv_plot with synthetic data: no serial
port, no Keithley/E3631A, no run_single_routine_from_csv. It imports the
plotting function, feeds it fake pMOS points (drain current physically
NEGATIVE, Vd swept 0.9 -> 0), and writes a PNG so the axes can be eyeballed.

Run from the repo root with the venv active:
    python test_pmos_plot.py
It writes pmos_synth_check.png in the current directory.
"""
import sys
from pathlib import Path

# Same import shim as run_device_loop.py so iv_measure resolves from src/.
sys.argv = ["test_pmos_plot"]  # keep run_device_loop's --live-plot argv peek quiet
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from iv_measure.routines import RoutineMeasurement  # dataclass only, no hardware
import run_device_loop  # importing is safe: nothing runs until main() is called


def main() -> None:
    # Synthetic pMOS "Output WO Bulk": Vd swept 0.9 -> 0, Vg stepped.
    # A real pMOS drain current is NEGATIVE, so drain_i_a is negative here.
    points = []
    for vg in (0.3, 0.6, 0.9):
        for i in range(30):
            vd = 0.9 - i * (0.9 / 29)
            id_mag = (0.9 - vg) * (0.9 - vd) * 6e-5  # bigger |Id| at lower Vg
            points.append(RoutineMeasurement(
                "Output WO Bulk", "Vg", vg, "Vd", vd,
                vg_v=vg, vd_v=vd, vb_v=0.0, vs_v=0.9, vgxp_v=0.95, vgxn_v=0.1,
                drain_i_a=-id_mag))  # NEGATIVE, as a real pMOS measures

    out = Path("pmos_synth_check.png")
    run_device_loop.save_iv_plot(
        points, "Output WO Bulk", "Vd", "Vg", out,
        subtitle="SYNTHETIC pMOS test -- x:0.9->0, true (negative) current",
        pmos=True)
    print(f"wrote {out.resolve()}")
    print("expect: linear panel x-axis 0.9 (left) -> 0 (right), current NEGATIVE")


if __name__ == "__main__":
    main()
