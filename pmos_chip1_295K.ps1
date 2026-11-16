# Room-temperature (295 K) full PMOS scan of BOARD 1 / CHIP 1, for comparison
# against the chip-2 dataset. Uses the REDUCED routines CSV (same grid as the
# chip-1 NMOS scan, points land exactly on the chip-2 full-resolution grid).
#
#   Routine 0 "Output WO Bulk"            : sweep Vd(15) x step Vg(4)  = 60 pts/device
#   Routine 1 "Accumulation to Inversion": sweep Vg(15) x step Vd(4)  = 60 pts/device
#   Routine 3 "Vg Sweep Vds m0p05"        : sweep Vg(15) @ raw Vd=0.85 = 15 pts/device
#   (REDUCED CSV order: 2 = NMOS +0.05, 3 = PMOS -0.05 -- reverse of full-res CSV)
#                                                                    = 135 pts/device
#
# Scope (600 devices): PMOS_ULVT(7), PMOS_LVT(8), PMOS_MID(9), PMOS_HVT(10), 150 each.
#
# PMOS wiring REQUIRED: Keithley LO/source tied to +0.9 V rail, so
# V_GS = vg - 0.9 and V_DS = vd - 0.9 (raw vd 0.85 = true -0.05). Id is negative.
# Manual rails (0.9/1.8 V on COM6, vgxp/vgxn on BK COM10) must already be ON.
#
# Resumable: a flavor whose CSV already holds all expected devices is skipped; a
# partial file is re-run from scratch (scan script overwrites from row 0).

$ErrorActionPreference = "Stop"
$log = "data/pmos_chip1_295K.log"
function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    $line | Tee-Object -FilePath $log -Append
}

$routinesCsv   = "Routines/Cryo PDK DC measurement routines - nMOS 28nm REDUCED.csv"
$routines      = "0,1,3"
$settle        = 0.1
$rowsPerDevice = 135  # 60 (Output) + 60 (Transfer) + 15 (Vg @ Vds-0.05)

$jobs = @(
    @{ cli = 7;  name = "PMOS_ULVT"; out = "data/array_scan_board1_chip1_PMOS_ULVT_295K.csv"; expectedDevices = 150 },
    @{ cli = 8;  name = "PMOS_LVT";  out = "data/array_scan_board1_chip1_PMOS_LVT_295K.csv";  expectedDevices = 150 },
    @{ cli = 9;  name = "PMOS_MID";  out = "data/array_scan_board1_chip1_PMOS_MID_295K.csv";  expectedDevices = 150 },
    @{ cli = 10; name = "PMOS_HVT";  out = "data/array_scan_board1_chip1_PMOS_HVT_295K.csv";  expectedDevices = 150 }
)

Log "PMOS chip-1 room-temp (295 K) reduced-grid scan starting (routines $routines, 135 pts/device)."

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

    Log "=== $($j.name) (cli=$($j.cli)) chip1 routines=$routines rows=0-5 cols=0-24 -> $($j.out) ==="
    python run_routine_automated_scan.py `
        --routines-csv $routinesCsv `
        --device-flavors $($j.cli) `
        --device-rows 0-5 `
        --device-cols 0-24 `
        --device-chip 1 `
        --board 1 `
        --routine-indices $routines `
        --ids-settle-s $settle `
        --output-csv $j.out
    $code = $LASTEXITCODE
    Log "$($j.name) finished (exit code $code)."
    if ($code -eq 130) {
        Log "Interrupted (Ctrl+C). Stopping; remaining work not started."
        Log "PMOS chip-1 295 K scan halted."
        exit 130
    }
    if ($code -ne 0) {
        Log "Non-zero exit for $($j.name); stopping to avoid cascading failures."
        Log "PMOS chip-1 295 K scan halted."
        exit $code
    }
}

Log "PMOS chip-1 room-temp (295 K) reduced-grid scan done (all 4 flavors)."
