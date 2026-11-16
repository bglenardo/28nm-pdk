# PMOS full scan at 295 K: Vd sweep, Vg sweep, and the extra Vds=-0.05 Vg sweep,
# for every PMOS flavor.
#
# Phase 1 = "Output WO Bulk"          Vd sweep        (routine index 0, 0.05 s settle, 300 rows/dev).
# Phase 2 = "Accumulation to Inversion" Vg sweep      (routine index 1, 0.1 s settle,  300 rows/dev).
# Phase 3 = "Vg Sweep Vds m0p05"      Vg @ Vds=-0.05  (routine index 2, 0.1 s settle,   30 rows/dev).
# One output CSV per flavor per routine so completion status is obvious from the
# data directory. All data taken at 295 K (encoded in the filename).
#
# PMOS NOTE: routine bias numbers are unchanged (0 -> 0.9). Correct PMOS polarity
# comes from the MANUAL wiring (Keithley LO / source referenced to +0.9 V, LO
# floating). That wiring must stay set for PMOS for the whole run.
#
# Manual rails (0.9 V / 1.8 V on COM6, vgxp/vgxn on BK COM10) must stay ON for
# the whole run; software never touches them.

$ErrorActionPreference = "Stop"
$log = "data/pmos_full_scan_295K.log"
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

# Each phase: routine index, settle time (s), filename tag, rows-per-device
# (used for resume accounting).
$phases = @(
    @{ routine = 0; settle = 0.05; tag = "vdsweep";          rowsPerDevice = 300; label = "Vd sweep (Output WO Bulk)" },
    @{ routine = 1; settle = 0.1;  tag = "vgsweep";          rowsPerDevice = 300; label = "Vg sweep (Accumulation to Inversion)" },
    @{ routine = 2; settle = 0.1;  tag = "vgsweep_vdsm0p05"; rowsPerDevice = 30;  label = "Vg sweep @ Vds=-0.05" }
)

Log "PMOS full-scan campaign (295 K) started."

foreach ($p in $phases) {
    Log "########## PHASE: $($p.label) [routine $($p.routine), settle $($p.settle)s] ##########"
    foreach ($f in $flavors) {
        $out = "data/array_scan_board1_chip2_$($f.name)_$($p.tag)_295K.csv"

        # Resume support: skip a flavor+phase whose CSV already holds all expected
        # devices. A partial file is re-run from scratch (the scan script
        # overwrites it).
        if (Test-Path $out) {
            $dataRows = (Get-Content $out | Measure-Object -Line).Lines - 1
            $devicesDone = [math]::Floor($dataRows / $p.rowsPerDevice)
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
            Log "PMOS full-scan campaign (295 K) halted."
            exit 130
        }
        if ($code -ne 0) {
            Log "Non-zero exit for $($f.name) $($p.tag); stopping campaign to avoid cascading failures."
            Log "PMOS full-scan campaign (295 K) halted."
            exit $code
        }
    }
}

Log "PMOS full-scan campaign (295 K) done."
