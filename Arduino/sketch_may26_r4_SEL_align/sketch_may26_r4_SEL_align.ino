// ===========================================================================
// sketch_may26_r4_SEL_align -- COPY of sketch_may26_r4_SEL with ONE added fix.
//
// Changes vs the original r4 sketch (all marked "// PATCH" / "// ALIGN PATCH"):
//   1. setup(): the hardcoded configureDevice(1,0,14) + while(true){} trap
//      are replaced by a READY banner. (inherited from _SEL)
//   2. loop(): parses "SEL <flavor> <row> <col>\n" from Serial and calls the
//      EXISTING configureDevice(); "PING" -> "PONG". (inherited from _SEL)
//   3. ALIGN PATCH (2026-08-11 bench finding): setScanAddress() now adds +1 to
//      every bit index. The physical chain seats one cell short of the 344-bit
//      software map -- bench-confirmed that scan_data bit index B lands on
//      physical cell B-1 (so bit 1, not bit 0, enables physical row 0). WITHOUT
//      this patch: commanded row0/col0 = garbage, and physical row5/col24 are
//      unreachable. WITH it: bit1=row0 ... bit6=row5, bit7=col0 ... bit31=col24.
//      Only the two index lines in setScanAddress change; pins, timing, shift,
//      latch, bounds, TOTAL_BITS, and the verification report are byte-identical
//      to the working sketch. Per CLAUDE.md §1 the bench wins over the brief's
//      344-bit map. MUST be confirmed on a LIVE transistor (Sout is the weak
//      analog read, Q2) -- verify commanded (0,0) is a real device and (5,24)
//      is reachable, and spot-check a block boundary in case the true cause is
//      a single global 345-cell shift rather than a per-block LSB spare.
//
// Driven by run_device_loop.py. Note: the built-in verification prints
// "Test Failed" with Mismatches: 2 on a HEALTHY chain (same-cycle check
// quirk); the Python side accepts <=2 and aborts only above that.
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
void shiftScanChain(ShiftResult &r) {
  r.elapsed_us = 0;
  r.mismatches = 0;
  r.passed = true;

  static uint8_t sin_log[TOTAL_BITS];
  static uint8_t sout_log[TOTAL_BITS];

  digitalWrite(PIN_SENABLE, LOW);   // active low enable

  unsigned long t0 = micros();

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

  unsigned long t1 = micros();
  r.elapsed_us = t1 - t0;

  digitalWrite(PIN_SENABLE, HIGH);

  // Print log after timing is done
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