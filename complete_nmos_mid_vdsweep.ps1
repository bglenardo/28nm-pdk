# Completion run for the interrupted NMOS_MID Vd sweep at 80 K.
#
# The standard file data/array_scan_board1_chip2_NMOS_MID_vdsweep_80K.csv holds
# exactly 85 devices (indices 0-84; last measured = row 3, col 9). This script
# measures ONLY the remaining 65 devices and writes them to a NEW file, WITHOUT
# touching the existing 85-device file.
#
# Remaining devices (row-major, row outer / col inner), 0-based index 85..149:
#   Chunk A: row 3,    cols 10-24  (15 devices)
#   Chunk B: rows 4-5, cols 0-24   (50 devices)
# Each python invocation overwrites its own --output-csv, so the two chunks go to
# temp files and are then concatenated into one remainder CSV.

$ErrorActionPreference = "Stop"
$log = "data/nmos_mid_vdsweep_complete.log"
function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    $line | Tee-Object -FilePath $log -Append
}

$tmpA      = "data/_mid_vdsweep_chunkA.csv"
$tmpB      = "data/_mid_vdsweep_chunkB.csv"
$remainder = "data/array_scan_board1_chip2_NMOS_MID_vdsweep_80K_part2.csv"

Log "NMOS_MID Vd sweep completion run started (devices 85-149)."

# Chunk A: row 3, cols 10-24
Log "=== Chunk A: NMOS_MID row 3 cols 10-24 -> $tmpA ==="
python run_routine_automated_scan.py `
    --device-flavors 3 `
    --device-rows 3 `
    --device-cols 10-24 `
    --device-chip 2 `
    --board 1 `
    --routine-indices 0 `
    --ids-settle-s 0.05 `
    --output-csv $tmpA
$code = $LASTEXITCODE
Log "Chunk A finished (exit code $code)."
if ($code -ne 0) { Log "Chunk A non-zero exit; stopping."; exit $code }

# Chunk B: rows 4-5, cols 0-24
Log "=== Chunk B: NMOS_MID rows 4-5 cols 0-24 -> $tmpB ==="
python run_routine_automated_scan.py `
    --device-flavors 3 `
    --device-rows 4-5 `
    --device-cols 0-24 `
    --device-chip 2 `
    --board 1 `
    --routine-indices 0 `
    --ids-settle-s 0.05 `
    --output-csv $tmpB
$code = $LASTEXITCODE
Log "Chunk B finished (exit code $code)."
if ($code -ne 0) { Log "Chunk B non-zero exit; stopping."; exit $code }

# Merge: header from A, then data rows from A and B.
$headerA = Get-Content $tmpA -TotalCount 1
$dataA   = Get-Content $tmpA | Select-Object -Skip 1
$dataB   = Get-Content $tmpB | Select-Object -Skip 1
$all     = @($headerA) + $dataA + $dataB
Set-Content -Path $remainder -Value $all
$remCount = [math]::Floor((($all.Count - 1)) / 300)
Log "Merged remainder written: $remainder ($remCount devices)."

Remove-Item $tmpA, $tmpB -ErrorAction SilentlyContinue
Log "Temp chunk files removed. NMOS_MID Vd sweep completion run done."
