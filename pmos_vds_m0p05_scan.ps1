# PMOS Vg sweep at a SINGLE drain bias Vds = -0.05 V, all 4 PMOS flavors.
#
# Routine index 2 = "Vg Sweep Vds m0p05": Vg swept 0 -> 0.9 (30 pts), Vd held at
# a single step of 0.85 V. In the PMOS source-reference wiring (Keithley LO tied
# to +0.9 V) the true device biases are V_GS = vg - 0.9 (0 -> -0.9) and
# V_DS = vd - 0.9 = 0.85 - 0.9 = -0.05 V. Id is negative (PMOS).
#
# 30 points/device (single Vd step), 0.1 s Vg settle. ~7 s/device, so all
# 600 PMOS devices take roughly 70 min.
#
# Temperature is now 295 K (coolant exhausted) -> filenames carry _295K, keeping
# this dataset distinct from the completed 175 K campaign.
#
# PMOS wiring (Keithley LO / source referenced to +0.9 V, LO floating) must stay
# set for the whole run. Manual rails (0.9 V / 1.8 V on COM6, vgxp/vgxn on BK
# COM10) must stay ON; software never touches them.

$ErrorActionPreference = "Stop"
$log = "data/pmos_vds_m0p05_scan.log"
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

$routineIndex = 2     # "Vg Sweep Vds m0p05"
$settle       = 0.1   # Vg-sweep settle time (s)
$tag          = "vgsweep_vdsm0p05"

Log "PMOS Vds=-0.05 Vg-sweep campaign started (295 K)."

foreach ($f in $flavors) {
    $out = "data/array_scan_board1_chip2_$($f.name)_$($tag)_295K.csv"

    # Resume support: skip a flavor whose CSV already holds all expected devices
    # (30 rows/device here). A partial file is re-run from scratch (the scan
    # script overwrites it).
    if (Test-Path $out) {
        $dataRows = (Get-Content $out | Measure-Object -Line).Lines - 1
        $devicesDone = [math]::Floor($dataRows / 30)
        if ($devicesDone -ge $f.expectedDevices) {
            Log "--- $($f.name) already complete ($devicesDone/$($f.expectedDevices)); skipping. ---"
            continue
        }
        Log "$($f.name) partial ($devicesDone/$($f.expectedDevices)); re-running from scratch."
    }

    Log "=== $($f.name) (cli=$($f.cli)) $tag cols=$($f.cols) -> $out ==="
    python run_routine_automated_scan.py `
        --device-flavors $($f.cli) `
        --device-rows 0-5 `
        --device-cols $($f.cols) `
        --device-chip 2 `
        --board 1 `
        --routine-indices $routineIndex `
        --ids-settle-s $settle `
        --output-csv $out
    $code = $LASTEXITCODE
    Log "$($f.name) $tag finished (exit code $code)."
    if ($code -eq 130) {
        Log "Interrupted (Ctrl+C). Stopping campaign; remaining work not started."
        Log "PMOS Vds=-0.05 campaign halted."
        exit 130
    }
    if ($code -ne 0) {
        Log "Non-zero exit for $($f.name) $tag; stopping campaign to avoid cascading failures."
        Log "PMOS Vds=-0.05 campaign halted."
        exit $code
    }
}

Log "PMOS Vds=-0.05 Vg-sweep campaign done."
