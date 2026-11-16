#!/usr/bin/env bash
# Re-scan the edge devices (physical row 0 and column 0) that the pre-firmware-fix
# overnight run could not reach. With the corrected unified_scan_select firmware,
# label 0 now selects physical row 0 / col 0.
#
# The missed devices form an "L" along two edges:
#   - row 0, all columns   (row0_scan_std / row0_scan_na)
#   - col 0, all rows       (col0_scan)
# The col-0 run uses rows 1-5 so the (row 0, col 0) corner is not measured twice.
#
# Manual supply rails (0.9/1.8 V, vgxp/vgxn) are skipped in software automatically.
#
# Usage: ./rescan_edge_devices.sh [BOARD] [CHIP]
set -euo pipefail

BOARD="${1:-1}"
CHIP="${2:-2}"
SETTLE=0.05
OUT="data"

echo "=== Edge re-scan: board ${BOARD}, chip ${CHIP} ==="

# Row 0, standard flavors (6x25 grid -> cols 0-24)
python run_routine_automated_scan.py \
  --device-flavors 1,2,3,5,6 \
  --device-rows 0 \
  --device-cols 0-24 \
  --device-chip "${CHIP}" \
  --board "${BOARD}" \
  --ids-settle-s "${SETTLE}" \
  --output-csv "${OUT}/array_scan_board${BOARD}_chip${CHIP}_row0_scan_std.csv"

# Row 0, NMOS_NA (6x14 grid -> cols 0-13)
python run_routine_automated_scan.py \
  --device-flavors 4 \
  --device-rows 0 \
  --device-cols 0-13 \
  --device-chip "${CHIP}" \
  --board "${BOARD}" \
  --ids-settle-s "${SETTLE}" \
  --output-csv "${OUT}/array_scan_board${BOARD}_chip${CHIP}_row0_scan_na.csv"

# Col 0, all flavors, rows 1-5 (corner already covered by the row-0 runs)
python run_routine_automated_scan.py \
  --device-flavors 1,2,3,4,5,6 \
  --device-rows 1-5 \
  --device-cols 0 \
  --device-chip "${CHIP}" \
  --board "${BOARD}" \
  --ids-settle-s "${SETTLE}" \
  --output-csv "${OUT}/array_scan_board${BOARD}_chip${CHIP}_col0_scan.csv"

echo "=== Edge re-scan complete ==="
