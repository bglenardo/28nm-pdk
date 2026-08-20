#include <Arduino.h>

// --- Pins ---
#define PIN_SUPDATE     2
#define PIN_SRST        3
#define PIN_SCLKP       4
#define PIN_SCLKN       5
#define PIN_SENABLE     6
#define PIN_SIN         7
#define PIN_SOUT        8
#define PIN_SOUT_ANALOG A0

const int threshold = 150;

// --- Chain geometry ---
const int TOTAL_BITS = 344;
static uint8_t sinLog[TOTAL_BITS];
static uint8_t soutLog[TOTAL_BITS];
uint8_t   scan_data[43];   // 344 / 8 = 43 bytes


const int FLAVOR_COUNT = 11;
const int flavor_base[FLAVOR_COUNT + 1] = {
  0, 0, 32, 64, 96, 120, 152, 184, 216, 248, 280, 312
};

int flavor_cols(int flavor) {
  if (flavor == 4) return 14;  // nmos_na special case
  return 25;
}

bool readSOUT_analog() {
  return (analogRead(PIN_SOUT_ANALOG) > threshold);
}

void resetScanChain() {
  digitalWrite(PIN_SRST, HIGH);
  delayMicroseconds(5);
  digitalWrite(PIN_SRST, LOW);
  delayMicroseconds(5);
}

// Returns false if flavor/row/col is out of range.
bool setScanAddress(int flavor, int row, int col) {
  memset(scan_data, 0, sizeof(scan_data));

  int max_cols = flavor_cols(flavor);
  if (flavor < 1 || flavor > FLAVOR_COUNT ||
      row < 0 || row >= 6 ||
      col < 0 || col >= max_cols) {
    return false;
  }

  int base = flavor_base[flavor];
  int SPACER_BIT = 1
  int row_bit = base + SPACER_BIT + row;
  scan_data[row_bit / 8] |= (1 << (row_bit % 8));

  int col_bit = base + 6 + SPACER_BIT + col;
  scan_data[col_bit / 8] |= (1 << (col_bit % 8));
  return true;
}

void shiftScanChain() {
  digitalWrite(PIN_SENABLE, LOW);  // active low enable

  for (int i = TOTAL_BITS - 1; i >= 0; i--) {
    int byteIndex = i / 8;
    int bitIndex  = i % 8;
    int bit = (scan_data[byteIndex] >> bitIndex) & 1;
    if (bit) {
      sinLog[i] = bit;
    }
    digitalWrite(PIN_SIN, bit);
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
  latchScanConfig();
  for (int i = TOTAL_BITS - 1; i >= 0; i--) {
    int byteIndex = i / 8;
    int bitIndex  = i % 8;
    int bit = (scan_data[byteIndex] >> bitIndex) & 0;
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
    if (readSOUT_analog()) {
      soutLog[i] = readSOUT_analog();
    }
    
  }
  digitalWrite(PIN_SENABLE, HIGH);
}

void latchScanConfig() {
  digitalWrite(PIN_SUPDATE, HIGH);
  delayMicroseconds(5);
  digitalWrite(PIN_SUPDATE, LOW);
}

// Parses "SEL,<flavor>,<row>,<col>" using simple String methods (no sscanf).
// Returns false if the line doesn't start with "SEL," or is missing a field.
// Inputting these pointers to flavor, row, and col
bool parseCommand(const String &line, int &flavor, int &row, int &col) {
  if (!line.startsWith("SEL,")) {
    return false;
  }

  // Strip the "SEL," prefix before splitting the remaining comma-separated fields.
  String rest = line.substring(4);

  int firstComma = rest.indexOf(',');
  int secondComma = rest.indexOf(',', firstComma + 1);
  if (firstComma == -1 || secondComma == -1) {
    return false;
  }

  flavor = rest.substring(0, firstComma).toInt();
  row = rest.substring(firstComma + 1, secondComma).toInt();
  col = rest.substring(secondComma + 1).toInt();
  return true;
}

bool compareLogs(uint8_t *sinLog, uint8_t *soutLog, int length) {
  bool allMatch = true;

  for (int i = 343; i >= 0; i--) {
    if (sinLog[i] != soutLog[i]){
      Serial.print(i);
      Serial.print(F(": SIN="));
      Serial.print(sinLog[i]);
      Serial.print(F(" SOUT="));
      Serial.println(soutLog[i]);
      allMatch = false;
  }
  }
}

void handleLine(const String &line) {
  int flavor, row, col;
  if (!parseCommand(line, flavor, row, col)) {
    Serial.println("ERR");
    return;
  }

  resetScanChain();
  if (!setScanAddress(flavor, row, col)) {
    Serial.println("ERR");
    return;
  }

  shiftScanChain();
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

  Serial.begin(9600);   // matches ARDUINO_BAUD = 9600 in the Python sweep script
  delay(200);
  Serial.println("READY");
}

void loop() {
  static String lineBuf;
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n') {
      lineBuf.trim();
      if (lineBuf.length() > 0) {
        handleLine(lineBuf);
        compareLogs(sinLog, soutLog, 344);
      }
      lineBuf = "";
    } else if (c != '\r') {
      lineBuf += c;
    }
    Serial.print("Completed");
  }
}