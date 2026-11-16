# NMOS full Vg sweep (routine 1 "Accumulation to Inversion", 0.1 s settle,
# 300 rows/device) at 80 K -- RESUME #2 after the 2026-11-12 16:04 cooling loss.
#
# Already captured cold (do NOT redo):
#   - LVT full Vg: COMPLETE 150 (rows0-2 cold file + rows3-5 _part2 file).
#   - HVT full Vg: row 0 (25 devices, cols 0-24) captured cold before 16:04,
#       saved in ...NMOS_HVT_vgsweep_80K_part1_cold_row0.csv. Restart at row 1.
#   - Vds=+0.05 fast Vg sweep: ALL 6 flavors cold. Vd sweep: LVT/HVT/MID cold.
#
# This resume completes the stop-after-MID scope:
#   1. HVT rows 1-5 (125 devices) -> ...NMOS_HVT_vgsweep_80K_part2.csv
#      (combine with part1_cold_row0 for a full cold 150).
#   2. MID full 150              -> ...NMOS_MID_vgsweep_80K.csv (fresh cold).
# then STOP. NA/ULVT/DNW Vg and the deferred Vd sweep remain for a later fill.
#
# NMOS normal wiring (Keithley LO at ground): raw vg/vd ARE true Vgs/Vds, Id
# positive. Manual rails (0.9/1.8 V on COM6, vgxp/vgxn on BK COM10) stay ON;
# software never touches them.

$ErrorActionPreference = "Stop"
$log = "data/nmos_vg_resume2_80K.log"
function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    $line | Tee-Object -FilePath $log -Append
}

# routine 1, 300 rows/device throughout.
$jobs = @(
    @{ cli = 2; name = "NMOS_HVT"; rows = "1-5"; cols = "0-24"; out = "data/array_scan_board1_chip2_NMOS_HVT_vgsweep_80K_part2.csv"; expectedDevices = 125 },
    @{ cli = 3; name = "NMOS_MID"; rows = "0-5"; cols = "0-24"; out = "data/array_scan_board1_chip2_NMOS_MID_vgsweep_80K.csv";       expectedDevices = 150 }
)

$routine = 1
$settle  = 0.1
$rowsPerDevice = 300

Log "NMOS full Vg sweep resume #2 (80 K, after 16:04 cooling loss) started."

foreach ($j in $jobs) {
    # Resume support: skip a job whose CSV already holds all expected devices;
    # a partial file is re-run from scratch (the scan script overwrites it).
    if (Test-Path $j.out) {
        $dataRows = (Get-Content $j.out | Measure-Object -Line).Lines - 1
        $devicesDone = [math]::Floor($dataRows / $rowsPerDevice)
        if ($devicesDone -ge $j.expectedDevices) {
            Log "--- $($j.name) vgsweep already complete ($devicesDone/$($j.expectedDevices)); skipping. ---"
            continue
        }
        Log "$($j.name) vgsweep partial ($devicesDone/$($j.expectedDevices)); re-running from scratch."
    }

    Log "=== $($j.name) (cli=$($j.cli)) vgsweep rows=$($j.rows) cols=$($j.cols) -> $($j.out) ==="
    python run_routine_automated_scan.py `
        --device-flavors $($j.cli) `
        --device-rows $($j.rows) `
        --device-cols $($j.cols) `
        --device-chip 2 `
        --board 1 `
        --routine-indices $routine `
        --ids-settle-s $settle `
        --output-csv $j.out
    $code = $LASTEXITCODE
    Log "$($j.name) vgsweep finished (exit code $code)."
    if ($code -eq 130) {
        Log "Interrupted (Ctrl+C). Stopping resume; remaining work not started."
        Log "NMOS full Vg sweep resume #2 (80 K) halted."
        exit 130
    }
    if ($code -ne 0) {
        Log "Non-zero exit for $($j.name) vgsweep; stopping resume to avoid cascading failures."
        Log "NMOS full Vg sweep resume #2 (80 K) halted."
        exit $code
    }
}

Log "NMOS full Vg sweep resume #2 (80 K) done (HVT rows1-5 + MID)."
