# NMOS full Vg transfer sweep (routine 1 "Accumulation to Inversion", 0.1 s
# settle, 300 rows/device = 30 Vg x 10 Vd) at 295 K (room temperature).
#
# This is the only remaining 295 K gap: NMOS transfer (full Vg) sweep is missing
# for ALL 6 flavors. NMOS 295 K output + fast-Vg are complete; all PMOS 295 K is
# complete.
#
# Scope (834 devices total, ~14 h at ~60 s/device):
#   LVT  (cli=1) 150  -> ...NMOS_LVT_vgsweep_295K.csv
#   HVT  (cli=2) 150  -> ...NMOS_HVT_vgsweep_295K.csv
#   MID  (cli=3) 150  -> ...NMOS_MID_vgsweep_295K.csv
#   NA   (cli=4)  84  -> ...NMOS_NA_vgsweep_295K.csv   (cols 0-13 only)
#   ULVT (cli=5) 150  -> ...NMOS_ULVT_vgsweep_295K.csv
#   DNW  (cli=6) 150  -> ...NMOS_DNW_vgsweep_295K.csv
#
# Starts after a 20-minute equilibration delay (devices re-settling at 295 K).
#
# NMOS normal wiring (Keithley LO at ground): raw vg/vd ARE true Vgs/Vds, Id
# positive. Manual rails (0.9/1.8 V on COM6, vgxp/vgxn on BK COM10) are already
# ON and stay ON; software never touches them.
# Resumable: a job whose CSV already holds all expected devices is skipped; a
# partial file is re-run from scratch (scan script overwrites from row 0).

$ErrorActionPreference = "Stop"
$log = "data/nmos_vg_transfer_295K.log"
function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    $line | Tee-Object -FilePath $log -Append
}

$routine       = 1
$settle        = 0.1
$rowsPerDevice = 300

$jobs = @(
    @{ cli = 1; name = "NMOS_LVT";  rows = "0-5"; cols = "0-24"; out = "data/array_scan_board1_chip2_NMOS_LVT_vgsweep_295K.csv";  expectedDevices = 150 },
    @{ cli = 2; name = "NMOS_HVT";  rows = "0-5"; cols = "0-24"; out = "data/array_scan_board1_chip2_NMOS_HVT_vgsweep_295K.csv";  expectedDevices = 150 },
    @{ cli = 3; name = "NMOS_MID";  rows = "0-5"; cols = "0-24"; out = "data/array_scan_board1_chip2_NMOS_MID_vgsweep_295K.csv";  expectedDevices = 150 },
    @{ cli = 4; name = "NMOS_NA";   rows = "0-5"; cols = "0-13"; out = "data/array_scan_board1_chip2_NMOS_NA_vgsweep_295K.csv";   expectedDevices = 84  },
    @{ cli = 5; name = "NMOS_ULVT"; rows = "0-5"; cols = "0-24"; out = "data/array_scan_board1_chip2_NMOS_ULVT_vgsweep_295K.csv"; expectedDevices = 150 },
    @{ cli = 6; name = "NMOS_DNW";  rows = "0-5"; cols = "0-24"; out = "data/array_scan_board1_chip2_NMOS_DNW_vgsweep_295K.csv";  expectedDevices = 150 }
)

$delayMinutes = 20
Log "NMOS transfer sweep (295 K) scheduled; waiting $delayMinutes min for device equilibration."
Start-Sleep -Seconds ($delayMinutes * 60)
Log "Equilibration delay complete. Starting NMOS transfer sweep (295 K)."

foreach ($j in $jobs) {
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
        Log "Interrupted (Ctrl+C). Stopping; remaining work not started."
        Log "NMOS transfer sweep (295 K) halted."
        exit 130
    }
    if ($code -ne 0) {
        Log "Non-zero exit for $($j.name) vgsweep; stopping to avoid cascading failures."
        Log "NMOS transfer sweep (295 K) halted."
        exit $code
    }
}

Log "NMOS transfer sweep (295 K) done (all 6 flavors)."
