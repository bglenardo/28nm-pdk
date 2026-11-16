# PMOS full scan: Vd sweep (all flavors) then Vg sweep (all flavors).
#
# Phase 1 = "Output WO Bulk" Vd sweep (routine index 0, 0.05 s settle).
# Phase 2 = "Accumulation to Inversion" Vg sweep (routine index 1, 0.1 s settle).
# One output CSV per flavor per routine so completion status is obvious from the
# data directory. All data taken at 175 K (encoded in the filename).
#
# PMOS NOTE: routine bias numbers are unchanged (0 -> 0.9). Correct PMOS polarity
# comes from the MANUAL wiring (Keithley LO / source referenced to +0.9 V). That
# wiring must stay set for PMOS for the whole run, and be reverted before any
# NMOS measurement.
#
# Manual rails (0.9 V / 1.8 V on COM6, vgxp/vgxn on BK COM10) must stay ON for
# the whole run; software never touches them.

$ErrorActionPreference = "Stop"
$log = "data/pmos_full_scan.log"
function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    $line | Tee-Object -FilePath $log -Append
}

# cliIndex is 1-based (as the scan script expects): PMOS flavors are 7-10.
# All PMOS flavors use the standard tables (6 rows x 25 cols = 150 devices).
$flavors = @(
    @{ cli = 7;  name = "PMOS_ULVT"; cols = "0-24"; expectedDevices = 150 },
    @{ cli = 8;  name = "PMOS_LVT";  cols = "0-24"; expectedDevices = 150 },
    @{ cli = 9;  name = "PMOS_MID";  cols = "0-24"; expectedDevices = 150 },
    @{ cli = 10; name = "PMOS_HVT";  cols = "0-24"; expectedDevices = 150 }
)

# Each phase: routine index, settle time (s), filename tag.
$phases = @(
    @{ routine = 0; settle = 0.05; tag = "vdsweep"; label = "Vd sweep (Output WO Bulk)" },
    @{ routine = 1; settle = 0.1;  tag = "vgsweep"; label = "Vg sweep (Accumulation to Inversion)" }
)

Log "PMOS full-scan campaign started."

foreach ($p in $phases) {
    Log "########## PHASE: $($p.label) [routine $($p.routine), settle $($p.settle)s] ##########"
    foreach ($f in $flavors) {
        $out = "data/array_scan_board1_chip2_$($f.name)_$($p.tag)_175K.csv"

        # Resume support: skip a flavor+phase whose CSV already holds all expected
        # devices (300 rows/device). A partial file is re-run from scratch (the
        # scan script overwrites it).
        if (Test-Path $out) {
            $dataRows = (Get-Content $out | Measure-Object -Line).Lines - 1
            $devicesDone = [math]::Floor($dataRows / 300)
            if ($devicesDone -ge $f.expectedDevices) {
                Log "--- $($f.name) $($p.tag) already complete ($devicesDone/$($f.expectedDevices)); skipping. ---"
                continue
            }
            Log "$($f.name) $($p.tag) partial ($devicesDone/$($f.expectedDevices)); re-running from scratch."
        }

        Log "=== $($f.name) (cli=$($f.cli)) $($p.tag) cols=$($f.cols) -> $out ==="
        python run_routine_automated_scan.py `
            --device-flavors $($f.cli) `
            --device-rows 0-5 `
            --device-cols $($f.cols) `
            --device-chip 2 `
            --board 1 `
            --routine-indices $($p.routine) `
            --ids-settle-s $($p.settle) `
            --output-csv $out
        $code = $LASTEXITCODE
        Log "$($f.name) $($p.tag) finished (exit code $code)."
        if ($code -eq 130) {
            Log "Interrupted (Ctrl+C). Stopping campaign; remaining work not started."
            Log "PMOS full-scan campaign halted."
            exit 130
        }
        if ($code -ne 0) {
            Log "Non-zero exit for $($f.name) $($p.tag); stopping campaign to avoid cascading failures."
            Log "PMOS full-scan campaign halted."
            exit $code
        }
    }
}

Log "PMOS full-scan campaign done."
