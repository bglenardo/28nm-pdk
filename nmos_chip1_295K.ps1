# Room-temperature (295 K) full NMOS scan of BOARD 1 / CHIP 1, for comparison
# against the chip-2 dataset. Uses the REDUCED routines CSV (dramatically fewer
# points):
#
#   Reduced grid design (see Routines/...REDUCED.csv). Points land EXACTLY on the
#   original full-resolution grid (via [::stride] decimation) for easy comparison:
#     * Vg/Vd sweeps -> 30-pt grid, stride 2 -> 15 pts: {0, 0.0621, ..., 0.869}
#     * Vd/Vg steps  -> 10-pt grid, stride 3 -> {0, 0.3, 0.6, 0.9}  (4 values)
#
#   Routine 0 "Output WO Bulk"            : sweep Vd(15) x step Vg(4)  = 60 pts/device
#   Routine 1 "Accumulation to Inversion": sweep Vg(15) x step Vd(4)  = 60 pts/device
#   Routine 2 "Vg Sweep Vds p0p05"        : sweep Vg(15) @ Vd=0.05     = 15 pts/device
#   All three routines run per device                                = 135 pts/device
#
# Scope (834 devices total): three routines per device, one combined CSV/flavor:
#   LVT  (cli=1) 150  -> ...chip1_NMOS_LVT_295K.csv
#   HVT  (cli=2) 150  -> ...chip1_NMOS_HVT_295K.csv
#   MID  (cli=3) 150  -> ...chip1_NMOS_MID_295K.csv
#   NA   (cli=4)  84  -> ...chip1_NMOS_NA_295K.csv   (cols 0-13 only)
#   ULVT (cli=5) 150  -> ...chip1_NMOS_ULVT_295K.csv
#   DNW  (cli=6) 150  -> ...chip1_NMOS_DNW_295K.csv
#
# Chip 1 is addressed through the Arduino scan-chain chip index (--device-chip 1);
# no physical swap is needed. NMOS normal wiring (Keithley LO at ground): raw
# vg/vd ARE true Vgs/Vds, Id positive. Manual rails (0.9/1.8 V on COM6, vgxp/vgxn
# on BK COM10) are user-controlled and must already be ON; software never toggles
# them.
#
# Resumable: a flavor whose CSV already holds all expected devices is skipped; a
# partial file is re-run from scratch (scan script overwrites from row 0).

$ErrorActionPreference = "Stop"
$log = "data/nmos_chip1_295K.log"
function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    $line | Tee-Object -FilePath $log -Append
}

$routinesCsv   = "Routines/Cryo PDK DC measurement routines - nMOS 28nm REDUCED.csv"
$routines      = "0,1,2"
$settle        = 0.1
$rowsPerDevice = 135  # 60 (Output) + 60 (Transfer) + 15 (Vg @ Vds+0.05)

$jobs = @(
    @{ cli = 1; name = "NMOS_LVT";  rows = "0-5"; cols = "0-24"; out = "data/array_scan_board1_chip1_NMOS_LVT_295K.csv";  expectedDevices = 150 },
    @{ cli = 2; name = "NMOS_HVT";  rows = "0-5"; cols = "0-24"; out = "data/array_scan_board1_chip1_NMOS_HVT_295K.csv";  expectedDevices = 150 },
    @{ cli = 3; name = "NMOS_MID";  rows = "0-5"; cols = "0-24"; out = "data/array_scan_board1_chip1_NMOS_MID_295K.csv";  expectedDevices = 150 },
    @{ cli = 4; name = "NMOS_NA";   rows = "0-5"; cols = "0-13"; out = "data/array_scan_board1_chip1_NMOS_NA_295K.csv";   expectedDevices = 84  },
    @{ cli = 5; name = "NMOS_ULVT"; rows = "0-5"; cols = "0-24"; out = "data/array_scan_board1_chip1_NMOS_ULVT_295K.csv"; expectedDevices = 150 },
    @{ cli = 6; name = "NMOS_DNW";  rows = "0-5"; cols = "0-24"; out = "data/array_scan_board1_chip1_NMOS_DNW_295K.csv";  expectedDevices = 150 }
)

Log "NMOS chip-1 room-temp (295 K) reduced-grid scan starting (routines $routines, 135 pts/device)."

foreach ($j in $jobs) {
    if (Test-Path $j.out) {
        $dataRows = (Get-Content $j.out | Measure-Object -Line).Lines - 1
        $devicesDone = [math]::Floor($dataRows / $rowsPerDevice)
        if ($devicesDone -ge $j.expectedDevices) {
            Log "--- $($j.name) already complete ($devicesDone/$($j.expectedDevices)); skipping. ---"
            continue
        }
        Log "$($j.name) partial ($devicesDone/$($j.expectedDevices)); re-running from scratch."
    }

    Log "=== $($j.name) (cli=$($j.cli)) chip1 routines=$routines rows=$($j.rows) cols=$($j.cols) -> $($j.out) ==="
    python run_routine_automated_scan.py `
        --routines-csv $routinesCsv `
        --device-flavors $($j.cli) `
        --device-rows $($j.rows) `
        --device-cols $($j.cols) `
        --device-chip 1 `
        --board 1 `
        --routine-indices $routines `
        --ids-settle-s $settle `
        --output-csv $j.out
    $code = $LASTEXITCODE
    Log "$($j.name) finished (exit code $code)."
    if ($code -eq 130) {
        Log "Interrupted (Ctrl+C). Stopping; remaining work not started."
        Log "NMOS chip-1 295 K scan halted."
        exit 130
    }
    if ($code -ne 0) {
        Log "Non-zero exit for $($j.name); stopping to avoid cascading failures."
        Log "NMOS chip-1 295 K scan halted."
        exit $code
    }
}

Log "NMOS chip-1 room-temp (295 K) reduced-grid scan done (all 6 flavors)."
