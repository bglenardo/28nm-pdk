#include <Arduino.h>

// THESE PINS ARE ALL WRONG! - BL 2.10.2026

// --- Pins (same) ---
#define PIN_SIN     7
#define PIN_SENABLE 6
#define PIN_SUPDATE 2
#define PIN_SRST    3
#define PIN_SCLKN   5
#define PIN_SCLKP   4
#define PIN_SOUT    8   // Optional for scan-out

// --- Chain geometry (UPDATED) ---
const int TOTAL_BITS = 3;       // 1..344 per bit-map
uint8_t   scan_data[43];  //44        // 344 / 8 = 43 bytes

// 11 flavors total: 1..11 (keep 0 as NA placeholder)
const int FLAVOR_COUNT = 11;

// Start bit (0-based) of each flavor block, from the map:
// nmos_lvt (1-31), nmos_hvt (33-63), nmos_mid (65-95),
// nmos_na (97-116), nmos_ulvt (121-151), nmos_dnw (153-183),
// pmos_ulvt (185-215), pmos_lvt (217-247), pmos_mid (249-279),
// pmos_hvt (281-311), pmos_lvt (313-343)
const int flavor_base[FLAVOR_COUNT + 1] = {
  0,    // flavor 0: NA (unused)
  0,    // 1: nmos_lvt   (starts at bit #1 -> index 0)
  32,   // 2: nmos_hvt   (starts at #33 -> index 32)
  64,   // 3: nmos_mid   (starts at #65 -> index 64)
  96,   // 4: nmos_na    (starts at #97 -> index 96)
  120,  // 5: nmos_ulvt  (starts at #121 -> index 120)
  152,  // 6: nmos_dnw   (starts at #153 -> index 152)
  184,  // 7: pmos_ulvt  (starts at #185 -> index 184)
  216,  // 8: pmos_lvt   (starts at #217 -> index 216)
  248,  // 9: pmos_mid   (starts at #249 -> index 248)
  280,  // 10: pmos_hvt  (starts at #281 -> index 280)
  312   // 11: pmos_lvt  (starts at #313 -> index 312)
};

// Per-flavor column count: most flavors have 25 columns (C0..C24).
// The bit-map shows flavor "nmos_na" (flavor 4) only has C0..C13 (14 columns).
int flavor_cols(int flavor) {
  if (flavor == 4) return 14;   // nmos_na special case
  return 25;                    // default C0..C24
}

#define PIN_SOUT_ANALOG A0
const int threshold = 300; 

bool readSOUT_analog() {
  int val = analogRead(PIN_SOUT_ANALOG);
  //Serial.print(val);
  return (val > threshold);
}

// Reset scan chain 
void resetScanChain() {
  digitalWrite(PIN_SRST, HIGH);
  logControlSignals();
  delayMicroseconds(5);
  digitalWrite(PIN_SRST, LOW);
  logControlSignals();
  delayMicroseconds(5);
}

// Set scan data bits for row/col selection (one-hot)
// Uses per-flavor base and per-flavor column limit
void setScanAddress(int flavor, int row, int col) {
  memset(scan_data, 0, sizeof(scan_data));

  int max_cols = flavor_cols(flavor);
  if (flavor < 1 || flavor > FLAVOR_COUNT || row < 0 || row >= 6 || col < 0 || col >= max_cols) {
    Serial.println("Invalid row/col/flavor index");
    return;
  }

  int base = flavor_base[flavor];

  // Row bits: R0..R5 occupy the first 6 bits of each flavor block
  int row_bit = base + row;
  scan_data[row_bit / 8] |= (1 << (row_bit % 8));

  // Column bits: immediately after 6 rows
  int col_bit = base + 6 + col;
  scan_data[col_bit / 8] |= (1 << (col_bit % 8));
  Serial.println("Scan data value:");
  for(int i=0; i<43; i++){
    Serial.print(scan_data[i]);
  }
  Serial.println("");
}

// Shift scan data into chain 
void shiftScanChain() {
  digitalWrite(PIN_SENABLE, LOW);  
  logControlSignals();

  int expectedBit = 0;
  int soutBit = 0;
  bool match = true;

  for (int i = TOTAL_BITS - 1; i >= 0; i--) {
    int byteIndex = i / 8;
    int bitIndex  = i % 8;
    expectedBit = (scan_data[byteIndex] >> bitIndex) & 1;
    //Serial.print(i);
    digitalWrite(PIN_SIN, expectedBit); 

    // two-phase, non-overlapping clocks 
    digitalWrite(PIN_SCLKP, HIGH);
    logControlSignals();
    delayMicroseconds(10);
    digitalWrite(PIN_SCLKP, LOW);
    digitalWrite(PIN_SCLKN, LOW);
    logControlSignals();
    delayMicroseconds(10);
    digitalWrite(PIN_SCLKN, HIGH);
    logControlSignals();
    delayMicroseconds(10);
    digitalWrite(PIN_SCLKP, LOW);
    digitalWrite(PIN_SCLKN, LOW);
    logControlSignals();
    delayMicroseconds(10);

    // read SOUT
    //soutBit = digitalRead(PIN_SOUT);
    soutBit = readSOUT_analog();

    if (soutBit != expectedBit) match = false;
  }

  digitalWrite(PIN_SENABLE, HIGH); //active low
  logControlSignals();

  Serial.println(match ? "Test Passed" : "Test Failed");
}

// Latch config 
void latchScanConfig() {
  digitalWrite(PIN_SUPDATE, HIGH);
  logControlSignals();
  delayMicroseconds(5);
  digitalWrite(PIN_SUPDATE, LOW);
  logControlSignals();
}

// Top-level configure 
void configureDevice(int flavor, int row, int col) {
  resetScanChain();
  setScanAddress(flavor, row, col);
  shiftScanChain();
  latchScanConfig();
}


void logControlSignals() {
  static bool printed_header = false;
  if (!printed_header) {
    printed_header = true;
  }
}

// Optional: print scan buffer MSB..LSB for debugging
void printScanChain() {
  Serial.println("Full Scan Chain:");
  for (int i = TOTAL_BITS - 1; i >= 0; i--) {
    int byteIndex = i / 8;
    int bitIndex  = i % 8;
    int bitVal = (scan_data[byteIndex] >> bitIndex) & 1;
    Serial.print(bitVal);
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
  pinMode(LED_BUILTIN, OUTPUT);

  Serial.begin(9600);
  delay(100);

  Serial.println("start");

  //digitalWrite(PIN_SUPDATE, HIGH);
  //digitalWrite(LED_BUILTIN, HIGH);

  // Example: flavor 1 (nmos_lvt), row 5, col 13 — adjust as needed
  configureDevice(1, 5, 7);
  printScanChain();

  while (true) { /* hold */ }
}

void loop() {}


