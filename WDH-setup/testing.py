import numpy as np

Vgs_SWEEP_NMOS = np.concatenate((
    np.linspace(0.000, 0.175,  4),   # 0.150 V steps
    np.linspace(0.2, 0.600, 18),   # 0.025 V steps
    np.linspace(0.625, 0.900, 8),   # 0.025 V steps
))

Vgs_SWEEP_PMOS = np.concatenate((
    np.linspace(0.9, 0.8,  4),   # 0.150 V steps
    np.linspace(0.75, 0.4, 18),   # 0.025 V steps
    np.linspace(0.35, 0.0, 8),   # 0.025 V steps
))

print(f"""
Vgs_SWEEP_NMOS = {Vgs_SWEEP_NMOS},
Vgs_SWEEP_PMOS = {Vgs_SWEEP_PMOS}
""")