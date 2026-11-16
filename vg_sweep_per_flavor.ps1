# Vg-sweep campaign, one output CSV per flavor.
#
# Runs the full "Accumulation to Inversion" Vg sweep (routine index 1, 0.1 s
# settle) on every NMOS flavor, writing a separate file per flavor so that
# completion status is obvious from the data directory. Each flavor file is
# self-contained (all rows/cols for that flavor). The underlying scan script
# checkpoints after every device, so an interruption still leaves a valid,
# up-to-date CSV for the flavor in progress.
#
# Manual rails (0.9 V / 1.8 V on COM6, vgxp/vgxn on BK COM10) must stay ON for
# the whole run; software never touches them.

$ErrorActionPreference = "Stop"
$log = "data/vg_sweep_per_flavor.log"
function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    $line | Tee-Object -FilePath $log -Append
}

# cliIndex is 1-based (as the scan script expects). cols is the column range
# for that flavor: NA has only 14 columns (0-13), the rest have 25 (0-24).
# expectedDevices lets the script skip a flavor whose output CSV is already
# complete, so the campaign can be safely re-run to resume after an interruption
# (e.g. a reboot) without redoing finished flavors. 6 rows x 25 cols = 150 for
# the standard flavors; 6 rows x 14 cols = 84 for NA.
$flavors = @(
    @{ cli = 1; name = "NMOS_LVT";  cols = "0-24"; expectedDevices = 150 },
    @{ cli = 2; name = "NMOS_HVT";  cols = "0-24"; expectedDevices = 150 },
    @{ cli = 3; name = "NMOS_MID";  cols = "0-24"; expectedDevices = 150 },
    @{ cli = 4; name = "NMOS_NA";   cols = "0-13"; expectedDevices = 84 },
    @{ cli = 5; name = "NMOS_ULVT"; cols = "0-24"; expectedDevices = 150 },
    @{ cli = 6; name = "NMOS_DNW";  cols = "0-24"; expectedDevices = 150 }
)

Log "Vg-sweep per-flavor campaign started."

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

Log "Vg-sweep per-flavor campaign done."
