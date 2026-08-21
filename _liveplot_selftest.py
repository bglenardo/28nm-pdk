"""Throwaway: does LiveRoutinePlot actually pop a window on THIS machine?

Exercises run_routine.py's LiveRoutinePlot exactly the way run_device_loop.py
does -- construct, feed synthetic points via .update() with the same
draw_idle+pause path, then close -- but with NO hardware and NO Agg override.
If a window appears here, the plotting stack is fine and the loop's problem is
timing/lifecycle. If it doesn't, it's the class/backend itself.

Run:  python _liveplot_selftest.py
"""
import sys
import time

# Do NOT force Agg -- mimic a --live-plot run (matplotlib picks tkagg here).
import matplotlib
print("BACKEND:", matplotlib.get_backend())

sys.path.insert(0, "src")
from iv_measure.routines import RoutineMeasurement
from run_routine import LiveRoutinePlot

live = LiveRoutinePlot("SELFTEST", step_param="Vg", sweep_param="Vd")

# 3 step curves x 12 sweep points, ~5 s total so a window has time to map/paint.
for step in (0.3, 0.6, 0.9):
    for i in range(12):
        vd = i * 0.08
        idv = (step - 0.2) * vd * 3e-5   # fake but fanned, monotonic
        m = RoutineMeasurement(
            routine="SELFTEST", step_param="Vg", step_value_v=step,
            sweep_param="Vd", sweep_value_v=vd,
            vg_v=step, vd_v=vd, vb_v=0.0, vs_v=0.0,
            vgxp_v=0.9, vgxn_v=-0.1, drain_i_a=idv)
        live.update(m)
        time.sleep(0.05)

print("sweep done; holding window 3 s (loop would plt.close here)")
time.sleep(3.0)
import matplotlib.pyplot as plt
plt.close(live._figure)
print("closed. If you never saw a window, that's the bug.")
