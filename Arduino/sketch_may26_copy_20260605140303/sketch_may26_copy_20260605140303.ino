#include <Arduino.h>

// --- Struct must be at top to avoid Arduino IDE auto-prototype bug ---
struct ShiftResult {
  unsigned long elapsed_us;
  int mismatches;
  int mismatches_chip2;
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
#define PIN_SOUT_CHIP2  A1
#define PIN_SOUT_ANALOG A0

const int threshold = 150;

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
void fastADC() {
  ADCSRA = (ADCSRA & 0xF8) | 0x04;
}

bool readSOUT_analog() {
  return (analogRead(PIN_SOUT_ANALOG) > threshold);
}

bool readSOUT2_analog() {
  return (analogRead(PIN_SOUT_CHIP2) > threshold);
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
void shiftScanChain(ShiftResult &r) {
  r.elapsed_us = 0;
  r.mismatches = 0;
  r.mismatches_chip2 = 0;
  r.passed = true;

  static uint8_t sin_log[TOTAL_BITS];
  static uint8_t sout_log[TOTAL_BITS];
  static uint8_t sout2_log[TOTAL_BITS];

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
    bool sout2Bit = readSOUT2_analog();
    // bool soutBit = digitalRead(PIN_SOUT);

    sin_log[idx]  = expectedBit;
    sout_log[idx] = soutBit ? 1 : 0;
    sout2_log[idx] = sout2Bit ? 1 : 0;
    idx++;

    if (soutBit != expectedBit) {
      r.mismatches++;
      r.passed = false;
    }
    if (sout2Bit != expectedBit) {
      r.mismatches_chip2++;
      r.passed = false;
    }
  }

  unsigned long t1 = micros();
  r.elapsed_us = t1 - t0;

  digitalWrite(PIN_SENABLE, HIGH);

  // Print log after timing is done
  Serial.println(F("Bit#\tSIN\tA0\tA1"));
  for (int i = 0; i < TOTAL_BITS; i++) {
    Serial.print(i);
    Serial.print(F("\t"));
    Serial.print(sin_log[i]);
    Serial.print(F("\t"));
    Serial.print(sout_log[i]);
    Serial.print(F("\t"));
    Serial.print(sout2_log[i]);
    if (sin_log[i] != sout_log[i]) Serial.print(F("  <-- MISMATCH"));
    if (sin_log[i] != sout2_log[i]) Serial.print(F("  <-- MISMATCH"));
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

  fastADC();

  // Quick benchmark of basic ops
  timingTest(200);

  // Real configuration + full chain shift with logging
  configureDevice(1, 1, 14); // (flavor, row, col)

  while (true) {}
}

void loop() {}