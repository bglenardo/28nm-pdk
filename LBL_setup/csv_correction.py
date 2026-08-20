import pandas as pd
import numpy as np
import shutil

# csv_measured = "PMOS_sweeps_818.csv"
# csv_baseline = "Baseline_all_off_PMOS.csv"

# shutil.copy(csv_measured, csv_measured.replace(".csv", "_backup.csv"))


# df1 = pd.read_csv(r'Full_measurement_runs\20260818_015256.csv')
# df2 = pd.read_csv(r'Full_measurement_runs\20260818_194845.csv')


# # Stack rows (same columns)
# combined = pd.concat([df1, df2], ignore_index=True)
# combined = combined.rename(columns={'id': 'id_2', 'id_2': 'id'})
# combined.to_csv('Full_measurement.csv', index=False)

import pandas as pd

df1 = pd.read_csv(r'Full_measurement.csv')

mask = (df1['l'] == 991.0)

df1.loc[mask, 'l'] = 1e-06

df1.to_csv(r'Full_measurement.csv', index=False)