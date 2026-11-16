# Overnight auto-chain watcher.
# Waits for the final Vd-sweep run (the NA flavor scan) to start and then
# finish, then launches the Vg sweep automatically. Keys off the python
# process command line so it only fires after the NA scan's process has both
# appeared and exited (which frees the instrument COM ports).

$ErrorActionPreference = "Stop"
Set-Location "C:\Users\blenardo\Desktop\28nm PDK"

$logPath = "data/overnight_autochain.log"
function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $logPath -Value $line
    Write-Output $line
}

# Marker uniquely identifying the LAST Vd-sweep run (NA flavor).
$naMarker = "nmos_na_vdsweep"

function Get-ScanProc($marker) {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*$marker*" }
}

Log "Watcher started. Waiting for the NA Vd-sweep run to begin..."

# Phase 1: wait until the NA scan process appears (standard scan still running).
while (-not (Get-ScanProc $naMarker)) {
    Start-Sleep -Seconds 30
}
Log "NA Vd-sweep run detected. Waiting for it to complete..."

# Phase 2: wait until the NA scan process exits (ports released).
while (Get-ScanProc $naMarker) {
    Start-Sleep -Seconds 30
}
Log "NA Vd-sweep run finished. Grace period before starting the Vg sweep."
Start-Sleep -Seconds 10

# Launch the Vg sweep (routine 1, 0.1 s settle), same device set as before.
$vgOut = "data/array_scan_board1_chip2_vg_sweep_settle0p1_full_run2.csv"
Log "Starting Vg sweep -> $vgOut"
& python run_routine_automated_scan.py `
    --device-flavors 1 `
    --device-rows 0-2 `
    --device-cols 0-10 `
    --device-chip 2 `
    --board 1 `
    --routine-indices 1 `
    --ids-settle-s 0.1 `
    --output-csv $vgOut 2>&1 | Add-Content -Path $logPath

Log "Vg sweep command returned (exit code $LASTEXITCODE)."
Log "Watcher done."
