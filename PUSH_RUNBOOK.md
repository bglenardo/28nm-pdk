# PUSH_RUNBOOK.md -- configuring the SECOND daisy-chained chip

The two chips share one scan chain: Arduino SIn -> Chip1 (344 bits) -> R1 ->
Chip2 -> Sout. A plain 344-cycle shift fills chip 1 only. This runbook flashes
the "push" sketch, measures the real chain length, and configures chip 2.

Files used (all new; no original edited):
`Arduino/sketch_may26_r4_SEL_PUSH/`, `flush_analyze.py`.

`<PORT>` = the Arduino serial port (e.g. COM11). Only ONE program may hold it
at a time (CLAUDE.md Q5): close the Arduino Serial Monitor before running any
Python, and vice-versa.

---

## Step 1 -- Flash the push sketch
```
arduino-cli compile --fqbn arduino:renesas_uno:minima Arduino/sketch_may26_r4_SEL_PUSH
arduino-cli upload  --fqbn arduino:renesas_uno:minima -p <PORT> Arduino/sketch_may26_r4_SEL_PUSH
```
Expect: `Compilation ... done`, then upload success. If compile fails, fix
before continuing. -> Step 2.

## Step 2 -- Smoke test (backward compatibility)
Close the Serial Monitor. Then:
```
python scan_bits.py --scan-port <PORT> --flavor 3 --row 0 --col 0
```
This sends `SEL 3 0 0` (no push). The lines `run_device_loop.py` actually
parses must all appear:
- `READY` (or answers `PING` with `PONG`)   -- port-open handshake (Q6)
- `Mismatches: N`                            -- N on its own line, integer only
- `SEL_DONE`                                 -- end of the SEL

If those appear, the push sketch is byte-compatible with the existing
automation. `Mismatches` ~2-3 is healthy (Q1/Q2 same-cycle quirk); the number
is diagnostic-only. -> Step 3.

If nothing prints: press RESET on the board with the port open; if still
nothing, wrong port or sketch not flashed -> back to Step 1.

## Step 3 -- Discovery run (measure the chain length)
```
python flush_analyze.py --scan-port <PORT> --flavor 3 --row 0 --col 0 --push 700 --save
```
Read the VERDICT line and WRITE DOWN the result:

- **"dominant delay ~344: A1 taps CHIP1_SOut ... length confirmed 344."**
  A1 monitors chip 1's Sout. Chip-1 chain is verified at 344. Record:
  `A1 = CHIP1_SOut`, `chip1 length = 344`. To configure chip 2 you must push by
  chip 1's length -> use `push = 344` in Step 6.

- **"dominant delay ~688 (or other): A1 taps CHIP2_SOut; combined = <X>;
  per-chip inferred = <X-344>."**
  A1 monitors chip 2's Sout. Record: `A1 = CHIP2_SOut`, `combined = X`,
  `per-chip = X-344`. Use `push = X-344` (bits needed to move chip 2's pattern
  from SIn into chip 2's segment) in Step 6.

- **"no 1s on Sout in any cycle: readback path dead OR chain not propagating."**
  Stop. Remove R1 (the 0-ohm link) and retest chip 1 alone via its Sout test
  point; if it works isolated, the fault is downstream of R1. Do not proceed.

Also note the recommended threshold context: this sketch uses `threshold=100`,
already proven healthy. Only revisit it (Step 5) if Step 3 finds 1s but the
delay analysis looks noisy. -> Step 4.

## Step 4 -- Reset-efficacy check
Run Step 3's command TWICE back-to-back. On the 2nd run, watch for:
```
NOTE: <k> SOUT=1 in the first 344 cycles (drain-out) ...
```
Meaning: the first 344 readback cycles show what the chain held BEFORE this
load. If they are nonzero after a prior SEL, the chain is draining out the
PREVIOUS selection -- i.e. `resetScanChain()` (SRST) did not clear it. This
means chip 2 may have been holding a stale selection in past runs. If you see
this consistently, SRST polarity/pulse needs fixing before trusting any
campaign data. If the first 344 cycles are all 0, reset is effective. -> Step 5.

## Step 5 -- Threshold update (only if needed)
If Step 3/4 showed 1s hovering ambiguously, change the single constant
`const int threshold = 100;` near the top of
`Arduino/sketch_may26_r4_SEL_PUSH/sketch_may26_r4_SEL_PUSH.ino` to the value
Step 3 suggested, then re-flash (Step 1). Otherwise skip. -> Step 6.

## Step 6 -- Configure a chip-2 device
Using the push value from Step 3 (chip 1's length, typically 344):
```
python -c "import serial,time; s=serial.Serial('<PORT>',115200,timeout=2); time.sleep(2); s.write(b'SEL <f> <r> <c> <push>\n'); time.sleep(3); print(s.read(4000).decode(errors='ignore')); s.close()"
```
Expect `SEL_DONE`. The shared SUpdate latches BOTH chips once, after all
shifting -- so chip 2 now holds (f,r,c) and chip 1 holds whatever its segment
ended up with (zeros if you pushed the pattern fully through).

Then the 5-minute electrical sanity check on chip 2's terminals: set Vg=0.1 V,
Vd=0.8 V (E3631A output ON; confirm vgxn=-0.2 V, vgxp=+0.95 V at the chip pins
with a DMM).
- nA-uA drain current -> device is off/subthreshold as expected -> proceed.
- mA -> STOP. Check the vgx rails at the chip pins with a DMM and confirm the
  E3631A output is actually ON. Do not run a campaign on a mA short.
-> Step 7.

## Step 7 -- One full routine on a chip-2 device
```
python run_routine.py --routines-csv "Routines/Cryo PDK DC measurement routines - nMOS 28nm.csv" --routine-index 0
```
(run_routine.py measures whatever is currently latched -- so it uses the chip-2
device you configured in Step 6.)

Healthy vs suspect (validate_iv.py's three failure modes):
- HEALTHY: Id-Vd curves FAN with Vg, rise then saturate, uA-scale.
- SUSPECT if any of: all-flat at nA (leakage floor -> nothing selected);
  pinned at compliance (10 mA rail -> short, not physics); curves overlap
  (no gate modulation -> gate not reaching the channel).

If healthy, chip 2 is characterizable -- point run_device_loop.py at it with
the measured push value baked into your SEL commands.
```
