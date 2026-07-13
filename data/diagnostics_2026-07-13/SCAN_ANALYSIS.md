# Scan-chain diagnostic — 2026-07-13 (chip 2, COM11)

## Raw capture
`scan_dump_sel300.txt` = full 344-bit `SEL 3 0 0` dump (Bit# / SIN / A0-readback).

## Finding: Sout readback is STUCK HIGH
- For SEL 3 0 0, the sketch sends a one-hot pattern: SIN=1 at printed Bit# 273
  and 279 (= logical bits 70 and 64 after the sketch's reverse print order),
  which ARE the correct row0/col0 bits for flavor 3 (base 64): row bit 64,
  col bit 70. So what we SEND is correct.
- The READBACK column (A0 = analogRead(A1) > threshold 100) is **1 for ALL 344
  bits**. Sout never goes low, never toggles with the shifted data.
- The two "matches" at bits 273/279 are coincidental (SIN was 1 there too);
  they are NOT the chain echoing data back.
- => Sout line is stuck high (floating/disconnected, pulled to a rail, or the
  ADC threshold is wrong). Mismatches = 342 = "all bits but the 2 sent-high".

## What this does and does NOT prove (CLAUDE.md Q1/Q2)
- The readback path (chip Sout pin 15 -> Arduino A1) is BROKEN.
- It does NOT by itself prove selection fails: per Q1/Q2 the readback only
  tests the Sout path. Selection worked in a prior good run (see the fanned
  Id-Vd screenshot with vgxn=-0.2V).

## Corroborating bench facts (2026-07-13)
- Rails 0.9/1.8 confirmed on; Vg (pin 13) confirmed reaching chip.
- E3631A Vg output verified: set 0.8 -> measured 0.803 V (needs SYST:REM +
  \r\n termination to talk).
- Keithley source/measure verified via raw serial.
- Gentle low-V trace: current starts at 0, rises smoothly (~6 kOhm) -> real
  semiconductor conduction, NOT a dead short and NOT damaged silicon.
- With a device selected + Vg swept 0..0.8, Id does NOT respond to Vg and pins
  at compliance -> gate not controlling the channel.

## Next decisive check (hardware)
Meter chip Sout (connector pin 15, CHIP2_SOut) to GND during a SEL:
- Fixed high, no wiggle while bits shift -> Sout stuck/disconnected at the chip.
- Toggles at pin 15 but A1 reads flat -> break is pin15 -> Arduino A1 (wire or
  threshold).
