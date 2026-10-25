// ===========================================================================
// sketch_may26_r4_SEL_PUSH -- COPY of sketch_may26_r4_SEL with "push cycles"
// so the SECOND daisy-chained chip can be configured.
//
// WHY: Arduino SIn -> Chip1 chain (344 bits) -> R1 -> Chip2 chain -> Sout.
// A 344-cycle shift only fills CHIP 1; chip 2 gets nothing. To load chip 2 you
// shift its 344-bit pattern first, then keep clocking ZEROS to PUSH that
// pattern through chip 1's chain into chip 2, then latch once (shared SUpdate
// latches both chips).
//
// CHANGES vs sketch_may26_r4_SEL (each marked "// PUSH"):
//   1. shiftScanChain(): takes push_cycles; log arrays sized [1100]; the loop
//      runs TOTAL_BITS+push_cycles cycles, driving the pattern bit while it
//      lasts then 0. The 4-phase clock and the Bit#/SIN/A0 table are UNCHANGED.
//   2. configureDevice(): takes push_cycles and passes it through. resetScanChain
//      still runs once at the start; latchScanConfig still pulses once AFTER all
//      shifting (push included).
//   3. loop(): "SEL <flavor> <row> <col> [push]" -- optional 4th int, default 0.
//      3 matched fields => push=0 == byte-identical to the old SEL behavior, so
//      run_device_loop.py works unchanged.
// Everything else (pins, threshold=100, timing, scan encoding, reset, latch,
// PING/PONG, READY, the same-cycle Mismatches quirk of Q1/Q2) is byte-identical.
// (New sketch folder; originals never edited.)
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

// PUSH: max cycles we log (pattern + push). 1100 covers 344 + a ~700 push,
// or a full 688-bit combined chain plus margin. sin_log 1100B + sout_log 1100B
// = 2.2 KB static -- trivial on the UNO R4 Minima's 32 KB SRAM.
const int MAX_CYCLES = 1100;

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

  int row_bit = base + row;
  scan_data[row_bit / 8] |= (1 << (row_bit % 8));

  int col_bit = base + 6 + col;
  scan_data[col_bit / 8] |= (1 << (col_bit % 8));
}

// --- Shift scan chain (pass result by reference to avoid IDE prototype bug) ---
void shiftScanChain(ShiftResult &r, int push_cycles) {   // PUSH: + push_cycles
  r.elapsed_us = 0;
  r.mismatches = 0;
  r.passed = true;

  static uint8_t sin_log[MAX_CYCLES];    // PUSH: was [TOTAL_BITS]
  static uint8_t sout_log[MAX_CYCLES];   // PUSH: was [TOTAL_BITS]

  int total = TOTAL_BITS + push_cycles;  // PUSH: pattern + push
  if (total > MAX_CYCLES) total = MAX_CYCLES;  // PUSH: clamp to log size

  digitalWrite(PIN_SENABLE, LOW);   // active low enable

  unsigned long t0 = micros();

  for (int c = 0; c < total; c++) {                  // PUSH: cycle-indexed loop
    int i = TOTAL_BITS - 1 - c;                      // PUSH: pattern index (highest first)
    int expectedBit = 0;                             // PUSH: drive 0 once pattern exhausted
    if (i >= 0) expectedBit = (scan_data[i / 8] >> (i % 8)) & 1;

    digitalWrite(PIN_SIN, expectedBit);

    // two-phase, non-overlapping clocks  (UNCHANGED)
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

    sin_log[c]  = expectedBit;
    sout_log[c] = soutBit ? 1 : 0;

    // PUSH: same-cycle mismatch counted ONLY over the first TOTAL_BITS cycles
    // (Q1/Q2 quirk; diagnostic-only). Identical to the old count when push=0.
    if (c < TOTAL_BITS && soutBit != expectedBit) {
      r.mismatches++;
      r.passed = false;
    }
  }

  unsigned long t1 = micros();
  r.elapsed_us = t1 - t0;

  digitalWrite(PIN_SENABLE, HIGH);

  // Print log after timing is done. Header/columns UNCHANGED (Bit#/SIN/A0) so
  // scan_bits.py still parses it; now covers all `total` cycles.
  Serial.println(F("Bit#\tSIN\tA0"));
  for (int c = 0; c < total; c++) {
    Serial.print(c);
    Serial.print(F("\t"));
    Serial.print(sin_log[c]);
    Serial.print(F("\t"));
    Serial.print(sout_log[c]);
    if (sin_log[c] != sout_log[c]) Serial.print(F("  <-- MISMATCH"));
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
void configureDevice(int flavor, int row, int col, int push_cycles) {  // PUSH: + push_cycles
  resetScanChain();                       // once at start (UNCHANGED)
  setScanAddress(flavor, row, col);

  ShiftResult r;
  shiftScanChain(r, push_cycles);         // PUSH: pass push through

  latchScanConfig();                      // once, AFTER all shifting (UNCHANGED)

  Serial.println(F("=== Scan shift results ==="));
  Serial.print(F("Total bits:     ")); Serial.println(TOTAL_BITS);
  Serial.print(F("Push cycles:    ")); Serial.println(push_cycles);  // PUSH: report push
  Serial.print(F("Elapsed:        ")); Serial.print(r.elapsed_us);
  Serial.println(F(" us"));
  Serial.print(F("Per bit:        "));
  Serial.print((float)r.elapsed_us / TOTAL_BITS);
  Serial.println(F(" us"));
  Serial.print(F("Effective rate: "));
  Serial.print(1e6f * TOTAL_BITS / r.elapsed_us);
  Serial.println(F(" bits/s"));
  Serial.print(F("Mismatches:     ")); Serial.println(r.mismatches);  // own line, int only
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

// PATCH: serial command handler. "SEL <flavor> <row> <col> [push]" runs the
// original configureDevice() with an optional 4th push-cycles arg (default 0);
// "PING" answers "PONG".
void loop() {
  static char buf[32];
  static uint8_t pos = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c != '\n') { if (pos < sizeof(buf) - 1) buf[pos++] = c; continue; }
    buf[pos] = 0; pos = 0;

    int flavor, row, col, push = 0;   // PUSH: default 0 if 4th field absent
    int n = sscanf(buf, "SEL %d %d %d %d", &flavor, &row, &col, &push);
    if (n == 3 || n == 4) {           // PUSH: 3 fields => push stays 0 (back-compat)
      configureDevice(flavor, row, col, push);   // original function, + push
      Serial.println(F("SEL_DONE"));
    } else if (strcmp(buf, "PING") == 0) {
      Serial.println(F("PONG"));
    } else if (buf[0] != 0) {
      Serial.print(F("ERR unknown cmd: "));
      Serial.println(buf);
    }
  }
}
