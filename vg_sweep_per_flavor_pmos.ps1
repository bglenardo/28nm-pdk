# PMOS Vg-sweep campaign, one output CSV per flavor (data taken at 175 K).
#
# Runs the full "Accumulation to Inversion" Vg sweep (routine index 1, 0.1 s
# settle) on every PMOS flavor, writing a separate file per flavor so that
# completion status is obvious from the data directory. Mirrors
# vg_sweep_per_flavor.ps1 (the NMOS campaign) for flavors 7-10.
#
# PMOS NOTE: the routine bias numbers are unchanged (0 -> 0.9). Correct PMOS
# polarity comes from the MANUAL hardware change of which supply the source
# voltage is referenced to -- that reference switch must be set for PMOS before
# running this, and must be reverted before resuming the NMOS campaign.
#
# Manual rails (0.9 V / 1.8 V on COM6, vgxp/vgxn on BK COM10) must stay ON for
# the whole run; software never touches them.

$ErrorActionPreference = "Stop"
$log = "data/vg_sweep_per_flavor_pmos.log"
function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    $line | Tee-Object -FilePath $log -Append
}

# cliIndex is 1-based (as the scan script expects): PMOS flavors are 7-10.
# All PMOS flavors use the standard tables (6 rows x 25 cols = 150 devices).
# expectedDevices lets the script skip a flavor whose output CSV is already
# complete, so the campaign can be safely re-run to resume after an interruption
# without redoing finished flavors.
$flavors = @(
    @{ cli = 7;  name = "PMOS_ULVT"; cols = "0-24"; expectedDevices = 150 },
    @{ cli = 8;  name = "PMOS_LVT";  cols = "0-24"; expectedDevices = 150 },
    @{ cli = 9;  name = "PMOS_MID";  cols = "0-24"; expectedDevices = 150 },
    @{ cli = 10; name = "PMOS_HVT";  cols = "0-24"; expectedDevices = 150 }
)

Log "PMOS Vg-sweep per-flavor campaign started."

foreach ($f in $flavors) {
    # All measurements in this campaign are taken at 175 K; encode that in the
    # filename (the temperature is not a column in the LBL-format CSV).
    $out = "data/array_scan_board1_chip2_$($f.name)_vgsweep_175K.csv"

    # Resume support: skip a flavor whose CSV already holds all expected devices
    # (300 rows/device for routine 1). A partial file is treated as incomplete
    # and re-run from scratch (the scan script overwrites it).
    if (Test-Path $out) {
        $dataRows = (Get-Content $out | Measure-Object -Line).Lines - 1
        $devicesDone = [math]::Floor($dataRows / 300)
        if ($devicesDone -ge $f.expectedDevices) {
            Log "--- Flavor $($f.name) already complete ($devicesDone/$($f.expectedDevices) devices); skipping. ---"
            continue
        }
        Log "Flavor $($f.name) partial ($devicesDone/$($f.expectedDevices) devices); re-running from scratch."
    }

    Log "=== Flavor $($f.name) (cli=$($f.cli)) cols=$($f.cols) -> $out ==="
    python run_routine_automated_scan.py `
        --device-flavors $($f.cli) `
        --device-rows 0-5 `
        --device-cols $($f.cols) `
        --device-chip 2 `
        --board 1 `
        --routine-indices 1 `
        --ids-settle-s 0.1 `
        --output-csv $out
    $code = $LASTEXITCODE
    Log "Flavor $($f.name) finished (exit code $code)."
    if ($code -eq 130) {
        Log "Interrupted (Ctrl+C). Stopping campaign; remaining flavors not started."
        break
    }
    if ($code -ne 0) {
        Log "Non-zero exit for $($f.name); stopping campaign to avoid cascading failures."
        break
    }
}

Log "PMOS Vg-sweep per-flavor campaign done."
