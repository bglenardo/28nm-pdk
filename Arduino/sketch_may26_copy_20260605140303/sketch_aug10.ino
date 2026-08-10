#include <Arduino.h>

// --- Struct must be at top to avoid Arduino IDE auto-prototype bug ---
struct ShiftResult {
  unsigned long elapsed_us;
  int mismatches;
  int mismatches_chip2;
  bool passed;
};

// --- Pins ---
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
  0, 0, 32, 64, 96, 120, 152, 184, 216, 248, 280, 312
};

int flavor_cols(int flavor) {
  if (flavor == 4) return 14;   // nmos_na special case
  return 25;
}

void fastADC() {
  ADCSRA = (ADCSRA & 0xF8) | 0x04;
}

bool readSOUT_analog() {
  return (analogRead(PIN_SOUT_ANALOG) > threshold);
}

bool readSOUT2_analog() {
  return (analogRead(PIN_SOUT_CHIP2) > threshold);
}

void resetScanChain() {
  digitalWrite(PIN_SRST, HIGH);
  delayMicroseconds(5);
  digitalWrite(PIN_SRST, LOW);
  delayMicroseconds(5);
}

void setScanAddress(int flavor, int row, int col) {
  memset(scan_data, 0, sizeof(scan_data));

  int max_cols = flavor_cols(flavor);
  if (flavor < 1 || flavor > FLAVOR_COUNT ||
      row < 0 || row >= 6 ||
      col < 0 || col >= max_cols) {
    Serial.println(F("ERR invalid flavor/row/col"));
    return;
  }

  int base = flavor_base[flavor];
  int row_bit = base + row;
  scan_data[row_bit / 8] |= (1 << (row_bit % 8));

  int col_bit = base + 6 + col;
  scan_data[col_bit / 8] |= (1 << (col_bit % 8));
}

// Added `verbose` flag so the sweep script can skip the full bit-by-bit
// log for every single device — printing 344 lines per device across a
// sweep of ~1000+ devices would dominate runtime.
void shiftScanChain(ShiftResult &r, bool verbose) {
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

  if (verbose) {
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
}

void latchScanConfig() {
  digitalWrite(PIN_SUPDATE, HIGH);
  delayMicroseconds(5);
  digitalWrite(PIN_SUPDATE, LOW);
}

// Now reports its result over Serial instead of printing a big summary
// block, since the Python side needs a machine-parsable line to know
// when the device is configured and whether the readback passed.
void configureDevice(int flavor, int row, int col, bool verbose) {
  resetScanChain();
  setScanAddress(flavor, row, col);

  ShiftResult r;
  shiftScanChain(r, verbose);

  latchScanConfig();

  Serial.print(F("RESULT flavor="));
  Serial.print(flavor);
  Serial.print(F(" row="));
  Serial.print(row);
  Serial.print(F(" col="));
  Serial.print(col);
  Serial.print(F(" mismatches="));
  Serial.print(r.mismatches);
  Serial.print(F(" mismatches2="));
  Serial.print(r.mismatches_chip2);
  Serial.print(F(" passed="));
  Serial.println(r.passed ? F("1") : F("0"));

  // Explicit sentinel line the Python side waits on before it knows the
  // device is ready to measure.
  Serial.println(F("DONE"));
}

// Command format, one line terminated by '\n':
//   C,<flavor>,<row>,<col>[,<verbose 0|1>]
// Example: "C,1,1,14,0\n"
void handleSerialCommand(const String &line) {
  if (line.length() == 0) return;

  if (line[0] != 'C') {
    Serial.println(F("ERR unknown command"));
    return;
  }

  int flavor = -1, row = -1, col = -1, verboseFlag = 0;
  // the %d matches the format of the values (digits) and then &flavor, &row, &col are assigned to pointres
  int parsed = sscanf(line.c_str(), "C,%d,%d,%d,%d", &flavor, &row, &col, &verboseFlag);

  if (parsed < 3) {
    Serial.println(F("ERR malformed command, expected C,<flavor>,<row>,<col>[,<verbose>]"));
    return;
  }

  configureDevice(flavor, row, col, verboseFlag != 0);
}

void setup() {
  pinMode(PIN_SIN, OUTPUT);
  pinMode(PIN_SCLKP, OUTPUT);
  pinMode(PIN_SCLKN, OUTPUT);
  pinMode(PIN_SENABLE, OUTPUT);
  pinMode(PIN_SUPDATE, OUTPUT);
  pinMode(PIN_SRST, OUTPUT);
  pinMode(PIN_SOUT, INPUT);

  digitalWrite(PIN_SENABLE, HIGH);  // active low -> disabled
  digitalWrite(PIN_SUPDATE, LOW);
  digitalWrite(PIN_SRST, LOW);
  digitalWrite(PIN_SCLKP, LOW);
  digitalWrite(PIN_SCLKN, LOW);
  digitalWrite(PIN_SIN, LOW);

  Serial.begin(115200);
  delay(200);

  fastADC();

  // Signals to the Python side that the board has finished booting and
  // is ready to accept "C,..." commands.
  Serial.println(F("READY"));
}

void loop() {
  static String lineBuf;

  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n') {
      lineBuf.trim();
      handleSerialCommand(lineBuf);
      lineBuf = "";
    } else if (c != '\r') {
      lineBuf += c;
    }
  }
}
