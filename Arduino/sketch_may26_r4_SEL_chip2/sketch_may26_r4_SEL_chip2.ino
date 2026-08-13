// ===========================================================================
// sketch_may26_r4_SEL_chip2 -- COPY of sketch_may26_r4_SEL_align with ONE
// added behavior: a second phase of 344 clocks to propagate the bitstream into
// the daisy-chained CHIP 2.
//
// Inherited from sketch_may26_r4_SEL_align (all UNCHANGED):
//   - Pins, timing, clock waveform, TOTAL_BITS, flavor_base, bounds.
//   - setup() prints READY; loop() parses "SEL <flavor> <row> <col>" -> the
//     original configureDevice(); "PING" -> "PONG".
//   - ALIGN PATCH: setScanAddress() adds +1 to every bit index (chip 1's chain
//     seats one cell short of the 344-bit map, bench-confirmed 2026-08-11).
//   - The built-in Sout verification and its "Test Passed/Failed" / Mismatches
//     report are byte-identical (Q1/Q2: 2 mismatches is a healthy chain).
//
// CHIP2 PATCH (the ONLY functional change vs _align):
//   shiftScanChain() now clocks TWICE 344 = 688 times total. Phase 1 (first 344
//   clocks) is the ORIGINAL align shift, byte-identical: it feeds scan_data on
//   SIN, reads Sout, logs, and counts mismatches -- this is exactly the chip-1
//   load. Phase 2 (next 344 clocks) is NEW: it repeats the IDENTICAL two-phase
//   clock waveform with SIN held LOW, which shifts the pattern OUT of chip 1's
//   chain (Sout1 -> Sin2) and INTO chip 2's chain. No Sout read in phase 2
//   (chip 2's Sout is not wired back), so it does not affect the mismatch count.
//   SENABLE stays LOW across all 688 clocks (as in the original shift) and
//   returns HIGH only after phase 2 completes.
//
//   *** UNVERIFIED FOR CHIP 2 (do not assume) ***: the +1 ALIGN offset was
//   confirmed on CHIP 1's physical seating. Chip 2 is the same silicon
//   downstream, so the same per-chip offset is EXPECTED to apply -- but this is
//   NOT bench-confirmed. Verify on a LIVE chip-2 transistor that commanded
//   (flavor,0,0) is real and (flavor,5,24) is reachable before trusting a run.
//
// Driven by run_device_loop.py. The Python side accepts <=2 mismatches; use it
// as-is (phase-1 verification still prints exactly as in _align).
// ===========================================================================

#include <Arduino.h>

// --- Struct must be at top to avoid Arduino IDE auto-prototype bug ---
struct ShiftResult {
  unsigned long elapsed_us;
  int mismatches;
  bool passed;
};

// --- Pins OLD---
//#define PIN_SIN     2
//#define PIN_SCLKP   3
//#define PIN_SCLKN   4
//#define PIN_SENABLE 5
//#define PIN_SUPDATE 6
//#define PIN_SRST    7
//#define PIN_SOUT    8
//#define PIN_SOUT_ANALOG A0

// --- Pins NEW---
#define PIN_SUPDATE     2
#define PIN_SRST        3
#define PIN_SCLKP       4
#define PIN_SCLKN       5
#define PIN_SENABLE     6
#define PIN_SIN         7
#define PIN_SOUT        8
#define PIN_SOUT_CHIP2  9
#define PIN_SOUT_ANALOG A1

const int threshold = 100;

// --- Chain geometry ---
const int TOTAL_BITS = 344;
uint8_t   scan_data[43];   // 344 / 8 = 43 bytes

// 11 flavors total: 1..11
const int FLAVOR_COUNT = 11;
const int flavor_base[FLAVOR_COUNT + 1] = {
  0,    // index 0: unused
  0,    // 1: nmos_lvt
  32,   // 2: nmos_hvt
  64,   // 3: nmos_mid
  96,   // 4: nmos_na
  120,  // 5: nmos_ulvt
  152,  // 6: nmos_dnw
  184,  // 7: pmos_ulvt
  216,  // 8: pmos_lvt
  248,  // 9: pmos_mid
  280,  // 10: pmos_hvt
  312   // 11: pmos_lvt
};

int flavor_cols(int flavor) {
  if (flavor == 4) return 14;   // nmos_na special case
  return 25;
}

// --- ADC speedup: prescaler 128 -> 16, ~17 us per analogRead ---
// void fastADC() {
//   ADCSRA = (ADCSRA & 0xF8) | 0x04;
// }

bool readSOUT_analog() {
  return (analogRead(PIN_SOUT_ANALOG) > threshold);
}

// --- Reset scan chain ---
void resetScanChain() {
  digitalWrite(PIN_SRST, HIGH);
  delayMicroseconds(5);
  digitalWrite(PIN_SRST, LOW);
  delayMicroseconds(5);
}

// --- Build scan vector ---
void setScanAddress(int flavor, int row, int col) {
  memset(scan_data, 0, sizeof(scan_data));

  int max_cols = flavor_cols(flavor);
  if (flavor < 1 || flavor > FLAVOR_COUNT ||
      row < 0 || row >= 6 ||
      col < 0 || col >= max_cols) {
    Serial.println(F("Invalid flavor/row/col"));
    return;
  }

  int base = flavor_base[flavor];

  // ALIGN PATCH (2026-08-11): +1 on every bit index. The physical chain seats
  // one cell short of the 344-bit map, so bit index B lands on physical cell
  // B-1 (bench-confirmed). Adding 1 makes bit 1 = physical row 0, bit 7 = col 0,
  // etc. Original lines kept below, commented, so the change is auditable.
  // int row_bit = base + row;          // ORIGINAL (unaligned)
  // int col_bit = base + 6 + col;      // ORIGINAL (unaligned)
  int row_bit = base + 1 + row;
  scan_data[row_bit / 8] |= (1 << (row_bit % 8));

  int col_bit = base + 7 + col;
  scan_data[col_bit / 8] |= (1 << (col_bit % 8));
}

// --- Shift scan chain (pass result by reference to avoid IDE prototype bug) ---
//   Phase 1 (344 clocks): ORIGINAL align shift -- feeds scan_data, reads Sout,
//   verifies. Loads chip 1. Phase 2 (344 clocks): CHIP2 PATCH -- same waveform,
//   SIN held LOW, no Sout read; shifts the pattern through chip 1 into chip 2.
void shiftScanChain(ShiftResult &r) {
  r.elapsed_us = 0;
  r.mismatches = 0;
  r.passed = true;

  static uint8_t sin_log[TOTAL_BITS];
  static uint8_t sout_log[TOTAL_BITS];

  digitalWrite(PIN_SENABLE, LOW);   // active low enable

  unsigned long t0 = micros();

  // --- Phase 1: 344 clocks, load chip 1 (byte-identical to _align) ---
  int idx = 0;
  for (int i = TOTAL_BITS - 1; i >= 0; i--) {
    int byteIndex = i / 8;
    int bitIndex  = i % 8;
    int expectedBit = (scan_data[byteIndex] >> bitIndex) & 1;

    digitalWrite(PIN_SIN, expectedBit);

    // two-phase, non-overlapping clocks
    digitalWrite(PIN_SCLKP, HIGH);
    delayMicroseconds(10);
    digitalWrite(PIN_SCLKP, LOW);
    digitalWrite(PIN_SCLKN, LOW);
    delayMicroseconds(10);
    digitalWrite(PIN_SCLKN, HIGH);
    delayMicroseconds(10);
    digitalWrite(PIN_SCLKP, LOW);
    digitalWrite(PIN_SCLKN, LOW);
    delayMicroseconds(10);

    bool soutBit = readSOUT_analog();
    // bool soutBit = digitalRead(PIN_SOUT);

    sin_log[idx]  = expectedBit;
    sout_log[idx] = soutBit ? 1 : 0;
    idx++;

    if (soutBit != expectedBit) {
      r.mismatches++;
      r.passed = false;
    }
  }

  // --- Phase 2: CHIP2 PATCH -- 344 more clocks, SIN LOW, propagate to chip 2 ---
  // Identical waveform to phase 1, but SIN is held LOW (feeding zeros) so the
  // pattern already in chip 1 shifts out (Sout1 -> Sin2) into chip 2's chain.
  // No Sout read here: chip 2's Sout is not wired back, so there is nothing to
  // verify and nothing added to the mismatch count. SENABLE stays LOW.
  for (int i = TOTAL_BITS - 1; i >= 0; i--) {
    digitalWrite(PIN_SIN, LOW);

    // two-phase, non-overlapping clocks (identical to phase 1)
    digitalWrite(PIN_SCLKP, HIGH);
    delayMicroseconds(10);
    digitalWrite(PIN_SCLKP, LOW);
    digitalWrite(PIN_SCLKN, LOW);
    delayMicroseconds(10);
    digitalWrite(PIN_SCLKN, HIGH);
    delayMicroseconds(10);
    digitalWrite(PIN_SCLKP, LOW);
    digitalWrite(PIN_SCLKN, LOW);
    delayMicroseconds(10);
  }

  unsigned long t1 = micros();
  r.elapsed_us = t1 - t0;

  digitalWrite(PIN_SENABLE, HIGH);

  // Print log after timing is done (phase-1 verification only; 344 rows)
  Serial.println(F("Bit#\tSIN\tA0"));
  for (int i = 0; i < TOTAL_BITS; i++) {
    Serial.print(i);
    Serial.print(F("\t"));
    Serial.print(sin_log[i]);
    Serial.print(F("\t"));
    Serial.print(sout_log[i]);
    if (sin_log[i] != sout_log[i]) Serial.print(F("  <-- MISMATCH"));
    Serial.println();
  }
}

// --- Latch ---
void latchScanConfig() {
  digitalWrite(PIN_SUPDATE, HIGH);
  delayMicroseconds(5);
  digitalWrite(PIN_SUPDATE, LOW);
}

// --- Sub-operation timing benchmark ---
void timingTest(int numBits) {
  Serial.println(F("=== Sub-operation timing ==="));
  volatile int dummy = 0;
  unsigned long t0, t1;

  t0 = micros();
  for (int i = 0; i < numBits; i++) digitalWrite(PIN_SIN, i & 1);
  t1 = micros();
  Serial.print(F("digitalWrite: "));
  Serial.print((float)(t1 - t0) / numBits); Serial.println(F(" us/op"));

  t0 = micros();
  for (int i = 0; i < numBits; i++) dummy += digitalRead(PIN_SOUT);
  t1 = micros();
  Serial.print(F("digitalRead:  "));
  Serial.print((float)(t1 - t0) / numBits); Serial.println(F(" us/op"));

  t0 = micros();
  for (int i = 0; i < numBits; i++) dummy += analogRead(PIN_SOUT_ANALOG);
  t1 = micros();
  Serial.print(F("analogRead:   "));
  Serial.print((float)(t1 - t0) / numBits); Serial.println(F(" us/op"));

  // SIN -> A0 loopback round-trip
  int mism = 0;
  t0 = micros();
  for (int i = 0; i < numBits; i++) {
    int exp = i & 1;
    digitalWrite(PIN_SIN, exp);
    delayMicroseconds(5);
    if (readSOUT_analog() != exp) mism++;
  }
  t1 = micros();
  Serial.print(F("SIN->A0 loop: "));
  Serial.print((float)(t1 - t0) / numBits);
  Serial.print(F(" us/op, mismatches="));
  Serial.print(mism); Serial.print(F("/")); Serial.println(numBits);
  Serial.println();
}



// --- Top-level configure ---
void configureDevice(int flavor, int row, int col) {
  resetScanChain();
  setScanAddress(flavor, row, col);

  ShiftResult r;
  shiftScanChain(r);

  latchScanConfig();

  Serial.println(F("=== Scan shift results ==="));
  Serial.print(F("Total bits:     ")); Serial.println(TOTAL_BITS);
  Serial.print(F("Total clocks:   ")); Serial.println(TOTAL_BITS * 2);  // CHIP2: 688
  Serial.print(F("Elapsed:        ")); Serial.print(r.elapsed_us);
  Serial.println(F(" us"));
  Serial.print(F("Per bit:        "));
  Serial.print((float)r.elapsed_us / TOTAL_BITS);
  Serial.println(F(" us"));
  Serial.print(F("Effective rate: "));
  Serial.print(1e6f * TOTAL_BITS / r.elapsed_us);
  Serial.println(F(" bits/s"));
  Serial.print(F("Mismatches:     ")); Serial.println(r.mismatches);
  Serial.println(r.passed ? F("Test Passed") : F("Test Failed"));
}

// --- Debug: print scan vector MSB..LSB ---
void printScanChain() {
  Serial.println(F("Scan vector (MSB..LSB):"));
  for (int i = TOTAL_BITS - 1; i >= 0; i--) {
    int b = (scan_data[i / 8] >> (i % 8)) & 1;
    Serial.print(b);
  }
  Serial.println();
}

void setup() {

  bool is_not_R4 = false;

  pinMode(PIN_SIN, OUTPUT);
  pinMode(PIN_SCLKP, OUTPUT);
  pinMode(PIN_SCLKN, OUTPUT);
  pinMode(PIN_SENABLE, OUTPUT);
  pinMode(PIN_SUPDATE, OUTPUT);
  pinMode(PIN_SRST, OUTPUT);
  pinMode(PIN_SOUT, INPUT);

  // Idle states
  digitalWrite(PIN_SENABLE, HIGH);  // active low -> disabled
  digitalWrite(PIN_SUPDATE, LOW);
  digitalWrite(PIN_SRST, LOW);
  digitalWrite(PIN_SCLKP, LOW);
  digitalWrite(PIN_SCLKN, LOW);
  digitalWrite(PIN_SIN, LOW);

  Serial.begin(115200);
  delay(200);
  Serial.println(F("start"));


  // fastADC();



  // Quick benchmark of basic ops
  timingTest(200);

  // PATCH: hardcoded device selection removed; Python now commands
  // selections over Serial. READY tells the host the boot is complete.
  Serial.println(F("READY"));
}

// PATCH: serial command handler. "SEL <flavor> <row> <col>" runs the
// original configureDevice() unchanged; "PING" answers "PONG".
void loop() {
  static char buf[32];
  static uint8_t pos = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c != '\n') { if (pos < sizeof(buf) - 1) buf[pos++] = c; continue; }
    buf[pos] = 0; pos = 0;

    int flavor, row, col;
    if (sscanf(buf, "SEL %d %d %d", &flavor, &row, &col) == 3) {
      configureDevice(flavor, row, col);   // original function, untouched
      Serial.println(F("SEL_DONE"));
    } else if (strcmp(buf, "PING") == 0) {
      Serial.println(F("PONG"));
    } else if (buf[0] != 0) {
      Serial.print(F("ERR unknown cmd: "));
      Serial.println(buf);
    }
  }
}
