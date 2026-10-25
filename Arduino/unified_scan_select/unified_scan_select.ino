// unified_scan_select.ino
// Unified, runtime-controlled scan-chain driver for the two-chip (series /
// daisy-chained) ASIC board:  SIN -> chip 1 (344 bits) -> chip 2 (344 bits) -> SOUT.
//
// Unlike the earlier sketches (where chip 1 vs chip 2 was a COMPILE-TIME
// SCOPE_MODE), this sketch selects the target chip at RUNTIME from the host
// command, clocking 344 bits for chip 1 or 688 bits for chip 2 so the pattern
// propagates through chip 1 into chip 2.
//
// It also provides a VERIFY command that clocks the full chain and reads SOUT,
// then self-diagnoses WHERE SOUT is tapped by testing the readback against both
// a midpoint (chip-1 output, 344-stage) and an end-of-chain (chip-2 output,
// 688-stage) alignment. This resolves the long-standing "where is SOUT tapped?"
// question empirically, without needing the schematic.
//
// ----------------------------------------------------------------------------
// Serial protocol  (115200 baud, newline-terminated; commas OR spaces accepted)
// ----------------------------------------------------------------------------
//   On boot:            prints "start", board info, then "READY".
//   SEL <f> <r> <c> <chip>
//                       Select a device. chip=1 -> 344 clocks, chip=2 -> 688
//                       clocks. Latches, then prints "SEL_DONE".
//                       (chip defaults to 1 if omitted.)
//   VERIFY <f> <r> <c>  Clock the full 1032-bit chain, sample SOUT, print an
//                       alignment report, then "VERIFY_DONE".
//   PING                -> "PONG"
//   <anything else>     -> "ERR unknown cmd: <text>"
//
// Accepts either "SEL,1,2,3,2" or "SEL 1 2 3 2" so it works with both the
// space-delimited authoritative sketches and the comma-delimited Python host.
// ----------------------------------------------------------------------------

#include <Arduino.h>


// ============================================================
// PINS  (match the authoritative scopes_asic_test.ino)
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
// TIMING (microseconds) -- identical to the authoritative sketch
// ============================================================

#define T_SETUP  3
#define T_PULSE  11
#define T_DEAD   3
#define T_CTRL   10


// ============================================================
// SOUT analog settings
// ============================================================

const int SOUT_THRESHOLD = 100;


// ============================================================
// SCAN CHAIN GEOMETRY
// ============================================================

const int TOTAL_BITS    = 344;             // bits per chip
const int CLOCKS_CHIP1  = TOTAL_BITS;      // 344: into chip 1
const int CLOCKS_CHIP2  = TOTAL_BITS * 2;  // 688: through chip 1 into chip 2
const int CLOCKS_VERIFY = TOTAL_BITS * 3;  // 1032: full-chain readback

uint8_t scan_data[43];                     // 344 bits / 8 = 43 bytes

// Logs. sin_log holds the 344-bit pattern we drove; sout_log holds the SOUT
// sample for every one of the 1032 verification clocks.
static uint8_t sin_log[TOTAL_BITS];
static uint8_t sout_log[CLOCKS_VERIFY];

// Raw-ADC statistics for the most recent captured shift. These let us tell a
// truly dead SOUT line (raw_max ~0) from one that swings but never crosses the
// digital threshold (0 < raw_max < SOUT_THRESHOLD).
static int  raw_min = 1023;
static int  raw_max = 0;
static long raw_sum = 0;
static int  raw_count = 0;
static int  raw_over = 0;


// ============================================================
// DEVICE ADDRESS MAP  (authoritative offsets: base+row, base+6+col)
// ============================================================

const int FLAVOR_COUNT = 11;

const int flavor_base[FLAVOR_COUNT + 1] = {
  0,    // 0: unused
  0,    // 1:  nmos_lvt
  32,   // 2:  nmos_hvt
  64,   // 3:  nmos_mid
  96,   // 4:  nmos_na  (native array -- only 14 columns)
  120,  // 5:  nmos_ulvt
  152,  // 6:  nmos_dnw
  184,  // 7:  pmos_ulvt
  216,  // 8:  pmos_lvt
  248,  // 9:  pmos_mid
  280,  // 10: pmos_hvt
  312   // 11: pmos_lvt
};

int flavor_cols(int flavor) {
  if (flavor == 4) {
    return 14;   // nmos_na native array
  }
  return 25;
}


// ============================================================
// LOW-LEVEL HELPERS
// ============================================================

static inline bool readSOUT_analog() {
  return analogRead(PIN_SOUT_ANALOG) > SOUT_THRESHOLD;
}

void resetScanChain() {
  SRST_HI();
  delayMicroseconds(T_CTRL);
  SRST_LO();
  delayMicroseconds(T_CTRL);
}

// SUPDATE latches on an EDGE, so it MUST be pulsed HIGH->LOW every call.
// Driving it only LOW works once from the idle-HIGH state but produces no edge
// on later calls -> the DUT never changes -> identical curves for every device.
void latchScanConfig() {
  SUPDATE_HI();
  delayMicroseconds(5);
  SUPDATE_LO();
}

// Returns false (and prints an error) if flavor/row/col is out of range.
bool setScanAddress(int flavor, int row, int col) {
  memset(scan_data, 0, sizeof(scan_data));

  int max_cols = flavor_cols(flavor);
  if (flavor < 1 || flavor > FLAVOR_COUNT ||
      row < 0 || row >= 6 ||
      col < 0 || col >= max_cols) {
    Serial.print(F("ERR invalid flavor/row/col: "));
    Serial.print(flavor); Serial.print(' ');
    Serial.print(row);    Serial.print(' ');
    Serial.println(col);
    return false;
  }

  int base = flavor_base[flavor];

  int row_bit = base + row;
  scan_data[row_bit / 8] |= (1 << (row_bit % 8));

  int col_bit = base + 6 + col;
  scan_data[col_bit / 8] |= (1 << (col_bit % 8));
  return true;
}


// ============================================================
// SHIFT ENGINE
//   Clocks `total_clocks` cycles. The scan pattern is driven on SIN only for
//   the first TOTAL_BITS clocks; afterwards SIN is held LOW so zeros trail the
//   pattern and push it downstream. When `capture_sout` is true, SOUT is
//   sampled (while SCLKP is HIGH) on every clock into sout_log[].
// ============================================================

void shiftChain(int total_clocks, bool capture_sout) {
  memset(sin_log, 0, sizeof(sin_log));
  if (capture_sout) {
    memset(sout_log, 0, sizeof(sout_log));
    raw_min = 1023;
    raw_max = 0;
    raw_sum = 0;
    raw_count = 0;
    raw_over = 0;
  }

  SENABLE_LO();  // active-low enable

  for (int cycle = 0; cycle < total_clocks; cycle++) {
    uint8_t sinBit = 0;
    if (cycle < TOTAL_BITS) {
      sinBit = (scan_data[cycle >> 3] >> (cycle & 7)) & 1;
      sin_log[cycle] = sinBit;
    }

    // SCLKP was left HIGH from the previous cycle -> real falling edge here.
    SCLKP_LO();
    SIN_WRITE(sinBit);          // update SIN right after the SCLKP falling edge
    delayMicroseconds(T_SETUP); // let SIN settle before SCLKN rises

    SCLKN_HI();
    delayMicroseconds(T_PULSE);
    SCLKN_LO();
    delayMicroseconds(T_DEAD);

    SCLKP_HI();
    delayMicroseconds(T_PULSE);

    if (capture_sout && cycle < CLOCKS_VERIFY) {
      int raw = analogRead(PIN_SOUT_ANALOG);
      sout_log[cycle] = (raw > SOUT_THRESHOLD) ? 1 : 0;
      if (raw < raw_min) raw_min = raw;
      if (raw > raw_max) raw_max = raw;
      raw_sum += raw;
      raw_count++;
      if (raw > SOUT_THRESHOLD) raw_over++;
    }

    SIN_LO();
    SCLKP_LO();
  }

  // Idle states after all clocks finish.
  SENABLE_HI();
  SIN_LO();
  SCLKP_HI();
  SCLKN_LO();
}


// ============================================================
// SELECT (runtime chip choice)
// ============================================================

bool selectDevice(int flavor, int row, int col, int chip) {
  resetScanChain();
  if (!setScanAddress(flavor, row, col)) {
    return false;
  }

  int clocks = (chip == 2) ? CLOCKS_CHIP2 : CLOCKS_CHIP1;
  shiftChain(clocks, /*capture_sout=*/false);
  latchScanConfig();
  return true;
}


// ============================================================
// VERIFY (full-chain readback + SOUT tap-point self-diagnosis)
//   Counts mismatches assuming SOUT is tapped after `stages` shift elements:
//   a bit driven at clock k appears at SOUT at clock k+stages.
// ============================================================

int countMismatches(int stages) {
  int mism = 0;
  for (int k = 0; k < TOTAL_BITS; k++) {
    int c = k + stages;
    if (c >= CLOCKS_VERIFY) {
      break;
    }
    if (sout_log[c] != sin_log[k]) {
      mism++;
    }
  }
  return mism;
}

void verifyDevice(int flavor, int row, int col) {
  resetScanChain();
  if (!setScanAddress(flavor, row, col)) {
    return;
  }

  shiftChain(CLOCKS_VERIFY, /*capture_sout=*/true);
  latchScanConfig();

  // --- Flat-line / stuck-SOUT detection -------------------------------------
  // Count how many SOUT samples were HIGH across the whole capture. If this is
  // 0 the SOUT line is reading flat LOW (not connected, wrong threshold, or the
  // DUT is unpowered) and ANY mismatch count below is meaningless.
  int n_high = 0;
  int n_set = 0;
  for (int c = 0; c < CLOCKS_VERIFY; c++) {
    n_high += sout_log[c];
  }
  for (int k = 0; k < TOTAL_BITS; k++) {
    n_set += sin_log[k];
  }

  // --- Auto-find the real tap point -----------------------------------------
  // The proven reference samples SOUT at cycle (TOTAL_BITS-1)+i, i.e. an offset
  // of 343 for the chip-1 tap. Rather than guess one or two exact offsets, scan
  // a window around both plausible taps (chip-1 ~343, chip-2 ~687) and report
  // the offset that minimises mismatches. A real, correctly-aligned readback
  // drops to ~0; a flat/no-data line stays at n_set everywhere.
  int best_offset = -1;
  int best_mism = TOTAL_BITS + 1;
  for (int d = TOTAL_BITS - 6; d <= TOTAL_BITS * 2 + 6; d++) {
    if (d < 0) {
      continue;
    }
    int m = countMismatches(d);
    if (m < best_mism) {
      best_mism = m;
      best_offset = d;
    }
  }

  // Classify which chip tap the winning offset corresponds to.
  const char *tap;
  if (best_offset <= TOTAL_BITS + (TOTAL_BITS / 2)) {
    tap = "chip1";    // offset near 343
  } else {
    tap = "chip2";    // offset near 687
  }

  // Pass only when SOUT actually carries data AND aligns well somewhere.
  const int PASS_THRESHOLD = 4;
  int passed = (n_high > 0 && best_mism <= PASS_THRESHOLD) ? 1 : 0;

  Serial.print(F("VERIFY flavor=")); Serial.print(flavor);
  Serial.print(F(" row="));          Serial.print(row);
  Serial.print(F(" col="));          Serial.print(col);
  Serial.print(F(" bits_set="));     Serial.print(n_set);
  Serial.print(F(" sout_highs="));   Serial.print(n_high);
  Serial.print(F(" best_offset="));  Serial.print(best_offset);
  Serial.print(F(" best_mismatch=")); Serial.print(best_mism);
  Serial.print(F(" tap="));          Serial.print(tap);
  Serial.print(F(" raw_min="));      Serial.print(raw_min);
  Serial.print(F(" raw_max="));      Serial.print(raw_max);
  Serial.print(F(" raw_mean="));     Serial.print(raw_count ? (int)(raw_sum / raw_count) : 0);
  Serial.print(F(" passed="));       Serial.println(passed);

  if (n_high == 0) {
    Serial.println(F("VERIFY_NOTE SOUT read flat LOW -- check SOUT wiring to A1, "
                     "analog threshold, and that the DUT rails are powered."));
  }
}


// ============================================================
// SOUTRAW (raw-ADC diagnosis of the SOUT line)
//   Drives the full 1032-clock pattern and reports the raw analogRead(A1)
//   envelope so a dead line (max ~0) can be told apart from a swinging-but-
//   under-threshold line. Also samples A1 statically with SIN forced high/low.
// ============================================================

void soutRawDiag(int flavor, int row, int col) {
  // Static probes first: hold SIN low, then high, and read A1 directly. If the
  // line is wired and powered these should differ when the chain passes it.
  SENABLE_LO();
  SIN_LO();
  delayMicroseconds(50);
  int raw_sin_lo = analogRead(PIN_SOUT_ANALOG);
  SIN_HI();
  delayMicroseconds(50);
  int raw_sin_hi = analogRead(PIN_SOUT_ANALOG);
  SIN_LO();
  SENABLE_HI();

  resetScanChain();
  if (!setScanAddress(flavor, row, col)) {
    return;
  }
  shiftChain(CLOCKS_VERIFY, /*capture_sout=*/true);
  latchScanConfig();

  Serial.print(F("SOUTRAW threshold=")); Serial.print(SOUT_THRESHOLD);
  Serial.print(F(" static_sinlo="));     Serial.print(raw_sin_lo);
  Serial.print(F(" static_sinhi="));     Serial.print(raw_sin_hi);
  Serial.print(F(" shift_min="));        Serial.print(raw_min);
  Serial.print(F(" shift_max="));        Serial.print(raw_max);
  Serial.print(F(" shift_mean="));       Serial.print(raw_count ? (int)(raw_sum / raw_count) : 0);
  Serial.print(F(" shift_over_thresh=")); Serial.println(raw_over);
}


// ============================================================
// COMMAND PARSING
//   Accepts commas or spaces as field separators.
// ============================================================

void normalizeSeparators(char *s) {
  for (char *p = s; *p; ++p) {
    if (*p == ',') {
      *p = ' ';
    }
  }
}

void handleCommand(char *cmd) {
  normalizeSeparators(cmd);

  if (strncmp(cmd, "SEL", 3) == 0 && (cmd[3] == ' ' || cmd[3] == '\0')) {
    int f = -1, r = -1, c = -1, chip = 1;
    int n = sscanf(cmd + 3, "%d %d %d %d", &f, &r, &c, &chip);
    if (n >= 3) {
      if (selectDevice(f, r, c, chip)) {
        Serial.println(F("SEL_DONE"));
      } else {
        Serial.println(F("SEL_FAIL"));
      }
    } else {
      Serial.print(F("ERR bad SEL args: "));
      Serial.println(cmd);
    }
  } else if (strncmp(cmd, "VERIFY", 6) == 0 && (cmd[6] == ' ' || cmd[6] == '\0')) {
    int f = -1, r = -1, c = -1;
    int n = sscanf(cmd + 6, "%d %d %d", &f, &r, &c);
    if (n == 3) {
      verifyDevice(f, r, c);
      Serial.println(F("VERIFY_DONE"));
    } else {
      Serial.print(F("ERR bad VERIFY args: "));
      Serial.println(cmd);
    }
  } else if (strncmp(cmd, "SOUTRAW", 7) == 0 && (cmd[7] == ' ' || cmd[7] == '\0')) {
    int f = 1, r = 1, c = 6;
    sscanf(cmd + 7, "%d %d %d", &f, &r, &c);
    soutRawDiag(f, r, c);
    Serial.println(F("SOUTRAW_DONE"));
  } else if (strcmp(cmd, "PING") == 0) {
    Serial.println(F("PONG"));
  } else {
    Serial.print(F("ERR unknown cmd: "));
    Serial.println(cmd);
  }
}


// ============================================================
// SETUP / LOOP
// ============================================================

void setup() {
  pinMode(PIN_SENABLE, OUTPUT);
  pinMode(PIN_SIN, OUTPUT);
  pinMode(PIN_SCLKP, OUTPUT);
  pinMode(PIN_SCLKN, OUTPUT);
  pinMode(PIN_SUPDATE, OUTPUT);
  pinMode(PIN_SRST, OUTPUT);
  pinMode(PIN_SOUT_ANALOG, INPUT);

  // Idle states.
  SENABLE_HI();
  SIN_LO();
  SUPDATE_HI();
  SRST_HI();
  SCLKP_HI();
  SCLKN_LO();

  Serial.begin(115200);
  delay(2000);

  Serial.println(F("start"));
  Serial.println(F("unified_scan_select: 2-chip series, runtime chip select"));
  Serial.println(F("cmds: SEL f r c chip | VERIFY f r c | PING"));
  Serial.println(F("READY"));
}

void loop() {
  static char buf[48];
  static uint8_t len = 0;

  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (len > 0) {
        buf[len] = '\0';
        handleCommand(buf);
        len = 0;
      }
    } else if (len < sizeof(buf) - 1) {
      buf[len++] = ch;
    }
  }
}
