# NMOS Vg characterization at 80 K: the fast Vds=+0.05 Vg sweep and the full Vg
# sweep, for every NMOS flavor. The Vd sweep (Output WO Bulk) is intentionally
# OMITTED (2026-11-11) due to a limited coolant window; it will be run later when
# more LN2 is available.
#
# Phase 1 = "Vg Sweep Vds p0p05"        Vg @ Vds=+0.05  (routine index 3, 0.1 s settle,   30 rows/dev).
# Phase 2 = "Accumulation to Inversion" Vg sweep        (routine index 1, 0.1 s settle,  300 rows/dev).
# One output CSV per flavor per routine so completion status is obvious from the
# data directory. All data taken at 80 K (encoded in the filename).
#
# NMOS NOTE: normal wiring (Keithley LO at ground) -> raw vg/vd ARE true Vgs/Vds,
# Id positive. NMOS_NA uses only 14 columns (0-13 -> 84 devices); all other
# flavors use the standard 6 rows x 25 cols = 150 devices. Per-flavor runs are
# required (cannot combine NA with the others in one invocation).
#
# Manual rails (0.9 V / 1.8 V on COM6, vgxp/vgxn on BK COM10) must stay ON for
# the whole run; software never touches them.

$ErrorActionPreference = "Stop"
$log = "data/nmos_full_scan_80K.log"
function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    $line | Tee-Object -FilePath $log -Append
}

# cliIndex is 1-based (as the scan script expects): NMOS flavors are 1-6.
$flavors = @(
    @{ cli = 1; name = "NMOS_LVT";  cols = "0-24"; expectedDevices = 150 },
    @{ cli = 2; name = "NMOS_HVT";  cols = "0-24"; expectedDevices = 150 },
    @{ cli = 3; name = "NMOS_MID";  cols = "0-24"; expectedDevices = 150 },
    @{ cli = 4; name = "NMOS_NA";   cols = "0-13"; expectedDevices = 84  },
    @{ cli = 5; name = "NMOS_ULVT"; cols = "0-24"; expectedDevices = 150 },
    @{ cli = 6; name = "NMOS_DNW";  cols = "0-24"; expectedDevices = 150 }
)

# Each phase: routine index, settle time (s), filename tag, rows-per-device
# (used for resume accounting), and flavorClis = the 1-based flavor CLI indices
# this phase runs.
# PHASE ORDER (2026-11-11, limited cold window): run the fast Vds=+0.05 Vg sweep
# FIRST across ALL 6 flavors so a complete 80 K threshold/transfer map for all
# 834 devices is captured cold, then the full Vg sweep. The Vd sweep is OMITTED
# (deferred to a later run with more coolant).
# STOP-AFTER-MID (2026-11-11): the Vg sweep phase runs only LVT, HVT, MID (cli
# 1,2,3) and then the campaign ends -- coolant on this fill is only enough to
# cover the all-flavor Vds+0.05 map plus a few Vg flavors, so NA/ULVT/DNW Vg are
# intentionally not attempted (would run warm). They resume on the next fill.
$phases = @(
    @{ routine = 3; settle = 0.1;  tag = "vgsweep_vdsp0p05"; rowsPerDevice = 30;  label = "Vg sweep @ Vds=+0.05"; flavorClis = @(1,2,3,4,5,6) },
    @{ routine = 1; settle = 0.1;  tag = "vgsweep";          rowsPerDevice = 300; label = "Vg sweep (Accumulation to Inversion)"; flavorClis = @(1,2,3) }
)

Log "NMOS Vg characterization campaign (80 K, Vd sweep omitted, Vg stops after MID) started."

foreach ($p in $phases) {
    Log "########## PHASE: $($p.label) [routine $($p.routine), settle $($p.settle)s] ##########"
    foreach ($f in $flavors) {
        if ($p.flavorClis -notcontains $f.cli) { continue }
        $out = "data/array_scan_board1_chip2_$($f.name)_$($p.tag)_80K.csv"

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
            Log "NMOS full-characterization campaign (80 K) halted."
            exit 130
        }
        if ($code -ne 0) {
            Log "Non-zero exit for $($f.name) $($p.tag); stopping campaign to avoid cascading failures."
            Log "NMOS full-characterization campaign (80 K) halted."
            exit $code
        }
    }
}

Log "NMOS Vg characterization campaign (80 K, Vd sweep omitted, Vg stops after MID) done."
