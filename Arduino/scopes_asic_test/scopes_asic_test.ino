// scopes_asic_test.ino
// ASIC scan chain -- daisy-chained chip 1 -> chip 2, with host automation.
//
// SCOPE_MODE selects clock count and whether Sout is sampled/verified:
//   0 = Verification: 1032 clocks (TOTAL_BITS*3), reads/stores SOUT during the
//       final 344 clocks, prints a Mismatches report. Sout readback path only.
//   1 = Full scope:   1032 clocks, no analogRead(), clean timing for the scope.
//   2 = Chip 1:       344 clocks (TOTAL_BITS),   shifts pattern into chip 1.
//   3 = Chip 2:       688 clocks (TOTAL_BITS*2), shifts pattern through chip 1
//       into chip 2 (Sout1 -> Sin2 daisy chain). No analogRead(). <-- default
//       for automation, matches how the two chips are physically connected.
//
// Automation (works in EVERY mode) -- line-based host protocol, 115200 baud:
//   READY                       printed once at boot (liveness handshake)
//   SEL <flavor> <row> <col>    select device, then print SEL_DONE
//   PING                        -> PONG
//   <anything else>             -> ERR unknown cmd: <text>
// In mode 0 a SEL also prints the Mismatches report before SEL_DONE; in modes
// 1/2/3 there is no Sout read, so no Mismatches line -- SEL_DONE alone confirms
// the shift completed (selection is proven by measuring the transistor).
//
// configureDevice() and the scan waveform (pins, timing, shift order) are
// unchanged from the working scope sketch.

#include <Arduino.h>


// ============================================================
// MODE SELECTION
// ============================================================

#define SCOPE_MODE 2   // 0=verify(1032) 1=scope(1032) 2=chip1(344) 3=chip2(688)


struct ShiftResult {
  int mismatches;
  bool passed;
};


// ============================================================
// PINS
// ============================================================

#define PIN_SUPDATE     2
#define PIN_SRST        3
#define PIN_SCLKP       4
#define PIN_SCLKN       5
#define PIN_SENABLE     6
#define PIN_SIN         7
#define PIN_SOUT_ANALOG A1


// ============================================================
// PIN MACROS
// ============================================================

#define SUPDATE_HI()  digitalWrite(PIN_SUPDATE, HIGH)
#define SUPDATE_LO()  digitalWrite(PIN_SUPDATE, LOW)

#define SRST_HI()     digitalWrite(PIN_SRST, HIGH)
#define SRST_LO()     digitalWrite(PIN_SRST, LOW)

#define SCLKP_HI()    digitalWrite(PIN_SCLKP, HIGH)
#define SCLKP_LO()    digitalWrite(PIN_SCLKP, LOW)

#define SCLKN_HI()    digitalWrite(PIN_SCLKN, HIGH)
#define SCLKN_LO()    digitalWrite(PIN_SCLKN, LOW)

#define SENABLE_HI()  digitalWrite(PIN_SENABLE, HIGH)
#define SENABLE_LO()  digitalWrite(PIN_SENABLE, LOW)

#define SIN_HI()      digitalWrite(PIN_SIN, HIGH)
#define SIN_LO()      digitalWrite(PIN_SIN, LOW)

#define SIN_WRITE(b)  ((b) ? SIN_HI() : SIN_LO())


// ============================================================
// TIMING, MICROSECONDS
// ============================================================

#define T_SETUP  3
#define T_PULSE  11
#define T_DEAD   3
#define T_CTRL   10


// ============================================================
// ANALOG SOUT SETTINGS
// ============================================================

const int threshold = 100;


// ============================================================
// SCAN CHAIN GEOMETRY
// ============================================================

const int TOTAL_BITS = 344;

// Clock count depends on the mode (how far the pattern must propagate).
#if SCOPE_MODE == 2
const int TOTAL_CLOCKS = TOTAL_BITS;       // 344 clocks: into chip 1
#elif SCOPE_MODE == 3
const int TOTAL_CLOCKS = TOTAL_BITS * 2;   // 688 clocks: through chip 1 to chip 2
#else
const int TOTAL_CLOCKS = TOTAL_BITS * 3;   // 1032 clocks: verify / full scope
#endif


// ============================================================
// SCAN DATA
// ============================================================

uint8_t scan_data[43];   // 344 bits / 8 = 43 bytes

static uint8_t sin_log[TOTAL_BITS];
static uint8_t sout_log[TOTAL_BITS];


// ============================================================
// DEVICE ADDRESS MAP
// ============================================================

const int FLAVOR_COUNT = 11;

const int flavor_base[FLAVOR_COUNT + 1] = {
  0,    // Index 0 unused
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
  if (flavor == 4) {
    return 14;   // nmos_na native array: 14 cols (CLAUDE.md Q4)
  }

  return 25;
}


// ============================================================
// READ SOUT
// ============================================================

static inline bool readSOUT_analog() {
  return analogRead(PIN_SOUT_ANALOG) > threshold;
}


// ============================================================
// RESET SCAN CHAIN
// ============================================================

void resetScanChain() {
  SRST_HI();
  delayMicroseconds(T_CTRL);

  SRST_LO();
  delayMicroseconds(T_CTRL);
}


// ============================================================
// LATCH SCAN CONFIGURATION
// ============================================================

void latchScanConfig() {
  // Supdate latches on an EDGE, so it must be PULSED every call. Driving it
  // only LOW works once from the HIGH idle (first device) but produces no edge
  // on subsequent calls -> the DUT never changes -> identical curves for every
  // device. Pulse HIGH->LOW, matching the authoritative r4 sketch's
  // latchScanConfig (sketch_may26_r4_copy_20260609150247.ino:162).
  SUPDATE_HI();
  delayMicroseconds(5);
  SUPDATE_LO();
}


// ============================================================
// BUILD SCAN VECTOR
// ============================================================

void setScanAddress(int flavor, int row, int col) {
  memset(scan_data, 0, sizeof(scan_data));

  int max_cols = flavor_cols(flavor);

  if (flavor < 1 ||
      flavor > FLAVOR_COUNT ||
      row < 0 ||
      row >= 6 ||
      col < 0 ||
      col >= max_cols) {

    Serial.println(F("Invalid flavor/row/col"));
    return;
  }

  int base = flavor_base[flavor];

  int row_bit = base + row;

  scan_data[row_bit / 8] |=
      (1 << (row_bit % 8));

  int col_bit = base + 6 + col;

  scan_data[col_bit / 8] |=
      (1 << (col_bit % 8));
}


// ============================================================
// SHIFT SCAN CHAIN
//   Pattern is fed during the first 344 clocks; remaining clocks push it
//   downstream (mode 3: through chip 1 into chip 2). Mode 0 also samples SOUT.
// ============================================================

void shiftScanChain(ShiftResult &r) {
  r.mismatches = 0;
  r.passed = true;

  memset(sin_log, 0, sizeof(sin_log));
  memset(sout_log, 0, sizeof(sout_log));

  SENABLE_LO();

  for (int cycle = 0; cycle < TOTAL_CLOCKS; cycle++) {

    uint8_t sinBit = 0;

    // Send the scan pattern only during the first 344 clocks.
    // After that, SIN remains LOW so zeros trail the pattern.
    if (cycle < TOTAL_BITS) {
      sinBit =
          (scan_data[cycle >> 3] >> (cycle & 7)) & 1;

      sin_log[cycle] = sinBit;
    }

    // SCLKP was left HIGH from the previous cycle.
    // Therefore, this creates the real falling edge.
    SCLKP_LO();

    // Update SIN immediately after the SCLKP falling edge.
    SIN_WRITE(sinBit);

    // Allow SIN to settle before SCLKN rises.
    delayMicroseconds(T_SETUP);

    // Negative clock phase.
    SCLKN_HI();
    delayMicroseconds(T_PULSE);

    SCLKN_LO();
    delayMicroseconds(T_DEAD);

    // Positive clock phase.
    SCLKP_HI();
    delayMicroseconds(T_PULSE);

#if SCOPE_MODE == 0
    // Sample SOUT during the final 344 clocks, while SCLKP is HIGH.
    if (cycle >= TOTAL_BITS - 1 &&
        cycle < (TOTAL_BITS - 1) + TOTAL_BITS) {
      int soutIndex = cycle - (TOTAL_BITS - 1);
      sout_log[soutIndex] = readSOUT_analog();
    }
#endif

    // Match the original timing.
    SIN_LO();
    SCLKP_LO();
    // SIN is updated at the beginning of the next cycle.
  }

  // Return outputs to their idle states after all clocks finish.
  SENABLE_HI();
  SIN_LO();
  SCLKP_HI();
  SCLKN_LO();

#if SCOPE_MODE == 0
  // Compare captured SOUT with transmitted SIN (readback path check only).
  for (int i = 0; i < TOTAL_BITS; i++) {
    if (sin_log[i] != sout_log[i]) {
      r.mismatches++;
      r.passed = false;
    }
  }
#else
  // Scope / propagation modes do not read or verify SOUT.
  r.mismatches = -1;
  r.passed = false;
#endif
}


// ============================================================
// PRINT VERIFICATION RESULTS (mode 0 only)
// ============================================================

void printScanResults() {
  Serial.println(F("Bit#\tSIN\tA1"));

  for (int i = 0; i < TOTAL_BITS; i++) {
    Serial.print(i);
    Serial.print(F("\t"));

    Serial.print(sin_log[i]);
    Serial.print(F("\t"));

    Serial.print(sout_log[i]);

    if (sin_log[i] != sout_log[i]) {
      Serial.print(F("  <-- MISMATCH"));
    }

    Serial.println();
  }
}


// ============================================================
// PRINT CURRENT MODE
// ============================================================

void printModeInformation() {
  Serial.println();

#if SCOPE_MODE == 0
  Serial.println(F("MODE 0: Verification"));
  Serial.println(F("1032 total clocks"));
  Serial.println(F("SOUT sampled during final 344 clocks"));
#elif SCOPE_MODE == 1
  Serial.println(F("MODE 1: Full scope waveform"));
  Serial.println(F("1032 total clocks"));
  Serial.println(F("SOUT not sampled"));
#elif SCOPE_MODE == 2
  Serial.println(F("MODE 2: Chip 1 propagation"));
  Serial.println(F("344 total clocks"));
  Serial.println(F("Pattern shifted into chip 1"));
  Serial.println(F("SOUT not sampled"));
#elif SCOPE_MODE == 3
  Serial.println(F("MODE 3: Chip 2 propagation"));
  Serial.println(F("688 total clocks"));
  Serial.println(F("Pattern shifted through chip 1 into chip 2"));
  Serial.println(F("SOUT not sampled"));
#else
  #error "SCOPE_MODE must be 0, 1, 2, or 3"
#endif

  Serial.print(F("TOTAL_CLOCKS = "));
  Serial.println(TOTAL_CLOCKS);
}


// ============================================================
// TOP-LEVEL CONFIGURATION
// ============================================================

void configureDevice(int flavor, int row, int col) {
  resetScanChain();
  setScanAddress(flavor, row, col);

  ShiftResult r;
  shiftScanChain(r);
  latchScanConfig();

#if SCOPE_MODE == 0
  // Mode 0 prints the full Sout readback report. Q1/Q2: on a healthy chain the
  // same-cycle-style check flags the two one-hot bits (2 ideal, ~3 on this
  // bench); the count tests the readback path only, never selection.
  printScanResults();

  Serial.println(F("=== Scan shift results ==="));

  Serial.print(F("Total bits: "));
  Serial.println(TOTAL_BITS);

  Serial.print(F("Total clocks: "));
  Serial.println(TOTAL_CLOCKS);

  Serial.print(F("Mismatches: "));
  Serial.println(r.mismatches);

  Serial.println(
      r.passed ? F("Test Passed") : F("Test Failed"));
#endif
}


// ============================================================
// COMMAND HANDLER (active in every mode)
// ============================================================

void handleCommand(char *cmd) {
  if (strncmp(cmd, "SEL ", 4) == 0) {
    int flavor, row, col;
    if (sscanf(cmd + 4, "%d %d %d", &flavor, &row, &col) == 3) {
      configureDevice(flavor, row, col);   // original function, unchanged
      Serial.println(F("SEL_DONE"));        // sentinel the host waits on
    } else {
      Serial.print(F("ERR bad SEL args: "));
      Serial.println(cmd);
    }
  } else if (strcmp(cmd, "PING") == 0) {
    Serial.println(F("PONG"));
  } else {
    Serial.print(F("ERR unknown cmd: "));
    Serial.println(cmd);
  }
}


// ============================================================
// SETUP
// ============================================================

void setup() {
  pinMode(PIN_SENABLE, OUTPUT);
  pinMode(PIN_SIN, OUTPUT);
  pinMode(PIN_SCLKP, OUTPUT);
  pinMode(PIN_SCLKN, OUTPUT);
  pinMode(PIN_SUPDATE, OUTPUT);
  pinMode(PIN_SRST, OUTPUT);
  pinMode(PIN_SOUT_ANALOG, INPUT);

  // Idle states
  SENABLE_HI();
  SIN_LO();
  SUPDATE_HI();
  SRST_HI();
  SCLKP_HI();
  SCLKN_LO();

  Serial.begin(115200);
  delay(2000);

  Serial.println(F("start"));
  printModeInformation();
  Serial.println(F("READY"));   // handshake for host script (CLAUDE.md Q6)
}


// ============================================================
// LOOP
// ============================================================

void loop() {
  static char buf[32];
  static uint8_t len = 0;

  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (len > 0) {
        buf[len] = '\0';
        handleCommand(buf);
        len = 0;
      }
    } else if (len < sizeof(buf) - 1) {
      buf[len++] = c;
    }
  }
}
