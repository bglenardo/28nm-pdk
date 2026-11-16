# NMOS Vg sweep at a SINGLE drain bias Vds = +0.05 V, all 6 NMOS flavors.
#
# Routine index 3 = "Vg Sweep Vds p0p05": Vg swept 0 -> 0.9 (30 pts), Vd held at
# a single step of 0.05 V. NMOS NORMAL wiring (Keithley LO / source at ground),
# so the raw setpoints ARE the true device biases: V_GS = vg (0 -> 0.9),
# V_DS = vd = 0.05 V. Id is positive (NMOS).
#
# 30 points/device (single Vd step), 0.1 s Vg settle. ~7 s/device, so all
# ~834 NMOS devices take roughly 1.5 h.
#
# Temperature is now 295 K (coolant exhausted) -> filenames carry _295K.
#
# *** BEFORE RUNNING: revert the source-reference wiring back to NMOS ***
#   - Keithley LO / SOURCE back to ground (remove the +0.9 V tie used for PMOS)
#   - Re-instate the rear-panel LO-to-chassis ground jumper if it was removed.
# Manual rails (0.9 V / 1.8 V on COM6, vgxp/vgxn on BK COM10) must stay ON;
# software never touches them.

$ErrorActionPreference = "Stop"
$log = "data/nmos_vds_p0p05_scan.log"
function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    $line | Tee-Object -FilePath $log -Append
}

# cliIndex is 1-based (as the scan script expects): NMOS flavors are 1-6.
# NMOS_NA (cli 4) has only 14 columns (0-13 -> 84 devices); the rest use the
# standard 6 rows x 25 cols = 150 devices.
$flavors = @(
    @{ cli = 1; name = "NMOS_LVT";  cols = "0-24"; expectedDevices = 150 },
    @{ cli = 2; name = "NMOS_HVT";  cols = "0-24"; expectedDevices = 150 },
    @{ cli = 3; name = "NMOS_MID";  cols = "0-24"; expectedDevices = 150 },
    @{ cli = 4; name = "NMOS_NA";   cols = "0-13"; expectedDevices = 84  },
    @{ cli = 5; name = "NMOS_ULVT"; cols = "0-24"; expectedDevices = 150 },
    @{ cli = 6; name = "NMOS_DNW";  cols = "0-24"; expectedDevices = 150 }
)

$routineIndex = 3     # "Vg Sweep Vds p0p05"
$settle       = 0.1   # Vg-sweep settle time (s)
$tag          = "vgsweep_vdsp0p05"

Log "NMOS Vds=+0.05 Vg-sweep campaign started (295 K)."

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
        Log "NMOS Vds=+0.05 campaign halted."
        exit 130
    }
    if ($code -ne 0) {
        Log "Non-zero exit for $($f.name) $tag; stopping campaign to avoid cascading failures."
        Log "NMOS Vds=+0.05 campaign halted."
        exit $code
    }
}

Log "NMOS Vds=+0.05 Vg-sweep campaign done."
