// =========================================================
//  Perfusion Control sketch for the miniBCS with Teensy 3.5
//   REV G Board
//
//
//  2019 HHMI Janelia Steve Sawtelle
//
// ===============================================
// NON STANDARD LIBRARIES REQUIRED:
//     miniBCS
//     ILI9341_t3
//     Cmd

//#define DEBUG // print filtered ADC counts

#define VERSION "20261009"
// 20261009 JL
// - fix: ON_TYPE in runInterrupt() didn't stop a still-running pulse train
//   before setting the pin continuously HIGH, so a PULSE step immediately
//   followed by an "always on" (0Hz) step could get turned back off later
//   by the old pulse's own timers. Needed now that protocols are STIMULUS-only
//   and duration-based (see the Python side's ProtocolCodec.encode_protocol_download()),
//   which can place a PULSE step right before a continuous-ON step. The
//   device-side command format (CLEAR/PULSE/ON/OFF/RUN/STOP/MANUAL) itself is
//   unchanged; VALVE commands just aren't sent by the GUI anymore.
//
// 20261007 JL
// - add a per-sample timestamp: each analog sample now goes over serial as
//   "<current>,<vinMillivolts>,<elapsedMicros>", where elapsedMicros counts
//   up from 0 at the moment RUN starts (runCmd() latches protocolStartMicros
//   via micros(); 0 whenever no protocol has run yet). Lets the CSV log carry
//   a real time column instead of one row per poll with no time reference.
// - generalize that timestamp to MANUAL STIMULUS sessions too (not just
//   protocol RUN): renamed to timestampSessionActive/timestampSessionStartMicros
//   and latched in MANUAL STIMULUS ON/OFF-Hz/OFF as well as runCmd()/
//   stopProtocol(), so the Python side can log manual-mode data the same way.
//
// 20260916 JL
// - add A15 as a second analog input, reading a 0-3.3V signal ("VIN"). Each
//   analog sample now goes over serial as "<current>,<vinMillivolts>" instead
//   of a lone integer - see analogInterrupt()/loop() and the Python side's
//   ProtocolCodec.parse_stream_text() for the matching change.
// - fix: "MANUAL STIMULUS 0" (0Hz, sent whenever the GUI's Stimulus checkbox
//   is toggled on while the frequency spinbox reads 0) silently did nothing
//   because of the divide-by-zero guard added on 20260908 - the pin never
//   went high. 0Hz is now treated as the limit of a pulse train (period ->
//   infinity), i.e. equivalent to MANUAL STIMULUS ON.
//
// 20260908 JL
// - fix: protocol-mode STIMULUS pulses sounded continuous instead of clicking at
//   the configured frequency, even with the same width/frequency as MANUAL mode.
//   Root cause: runInterrupt() (a 1 kHz ISR) was calling pulseTimer.begin()/
//   frequencyTimer.begin() (hardware timer allocation) directly from inside itself,
//   while analogInterrupt() (a 4 kHz ISR) was doing blocking Serial I/O. Nesting
//   timer allocation and USB-serial writes inside interrupts is fragile on Teensy 3.x
//   and let the "turn pulse off" interrupt get delayed/dropped once the protocol's
//   runTimer ISR was also active (MANUAL mode never runs runTimer, so it never hit this).
//   Fix: runInterrupt()/analogInterrupt() now only record what needs to happen
//   (pending flags), and loop() does the actual timer arming, protocol-stop, and
//   Serial output in normal (non-ISR) code, matching how MANUAL mode already worked.
// - fix: pulseCmd() wrote into outList[outIndex] *before* validating width/frequency,
//   so a rejected PULSE line (e.g. FREQUENCY 0) could corrupt the downloaded protocol
//   (outIndex not advanced, END marker left stale). Validation now happens first.
// - fix: divide-by-zero guard for FREQUENCY 0 in both PULSE (protocol) and MANUAL
//   commands (the manual frequency spinbox allows 0).
//
// 20260408 JL
// - manual stiumlus frequency can be any integer value between 0 and 500Hz

// 20191205 sws
// - read current via miniBCS A0

// 20191121 sws
// - add 'DONE'reply when run is finished


// 20191015 sws
// - add 1,20, 100 Hz to manual pulse

// 20191007 sws
// - add manual control

// 20191002 sws
// - derived from miniBCS G Example


#include <miniBCSrevG.h>          // miniBSC functions
#include <XPT2046_Touchscreen.h>  // Touchscreen functions
#include <ILI9341_t3.h>           // TFT Display functions
#include <font_Arial.h>           // from ILI9341_t3
#include <SPI.h>                  // SPI needed for TFT display
#include <Cmd.h>                  // Command parsing


#define TS_CS 38    // touchscreen chip select
#define TFT_DC 21   // TFT data/command
#define TFT_CS 15   // TFT chip select
#define TFT_RST 37  // TFT rseest pin
// MOSI=11, MISO=12, SCK=13
#define LED_PIN 13

#define VALVE_PIN SOL1pin
#define STIMULUS_PIN A14
#define VIN_PIN A6  // second analog input: 0-3.3V signal

char instr[32];
char *isp;

#define END_TYPE 0
#define PULSE_TYPE 1
#define ON_TYPE 2
#define OFF_TYPE 3


struct output {
  int type;
  int pin;
  uint32_t start;
  uint32_t width;
  uint16_t frequency;
};

struct output outList[32];
int outIndex = 0;

// --- pin and constant assignments:

// assume Host serial interface is via USB

#define TONE_FREQ 500  // test tone frequency
#define MINDELAY 0     // min/max pulse delay in msec
#define MAXDELAY 5000
#define MINON 100  // min/max pusle time in msec
#define MAXON 5000

#define ZERO_OFFSET 4096  // 1.65V ref on 3.3V ain with 13 bits resolution
#define SAMPLE_TIME 250   // usecs per analog sample

// VIN_PIN reads a plain 0-3.3V signal (no offset), 13-bit resolution (0..8191
// counts). Scale converts a raw ADC count directly to millivolts:
// 3300mV / 8192 counts = 0.402832 mV/count
#define VIN_MV_PER_COUNT 0.402832

//volatile int8_t  pulsePin = LED_PIN;   // Teensy pin for pulse out
volatile int32_t pulseDelay = 0;
volatile int32_t pulseTime = 100000;
volatile boolean runFlag = false;
volatile float freq = 500;
volatile uint8_t level = 255;

// --- instantiate objects
miniBCS bcs;                   // instantiate a miniBCS object
IntervalTimer pulseTimer;      // create a timer for TTLpulse out
IntervalTimer frequencyTimer;  //  and for the pulse frequency
IntervalTimer runTimer;        // runs the protocol
IntervalTimer analogTimer;

ILI9341_t3 tft = ILI9341_t3(TFT_CS, TFT_DC, TFT_RST);  // instantiate TFT display
//XPT2046_Touchscreen ts(TS_CS);        // set chip select for touchscreen
// Touchscreen alternate setups
//#define TIRQ_PIN  32
//XPT2046_Touchscreen ts(CS_PIN);  // Param 2 - NULL - No interrupts
//XPT2046_Touchscreen ts(CS_PIN, 255);  // Param 2 - 255 - No interrupts
//XPT2046_Touchscreen ts(CS_PIN, TIRQ_PIN);  // Param 2 - Touch IRQ Pin - interrupt enabled polling


// need to save pin and time values from the list
volatile int pulsePin;
volatile uint32_t pulseOnUsecs;

// --- work handed off from ISRs to loop() -----------------------------------
// runInterrupt() and analogInterrupt() only set these; loop() does the actual
// hardware-timer allocation / Serial I/O. See VERSION changelog above for why.
volatile boolean pulseStartPending = false;
volatile int pendingPulsePin = 0;
volatile uint32_t pendingPulseOnUsecs = 0;
volatile uint16_t pendingPulseFrequency = 0;

volatile boolean protocolStopPending = false;

volatile boolean ainReady = false;
volatile int16_t current = 0;
volatile int16_t voltage = 0;
volatile float fcurrent = 0;
volatile float fvoltage = 0;
volatile uint32_t ainElapsedUsValue = 0;

// Elapsed-time reference for logged sample timestamps: t=0 the moment any
// timed output session starts - a protocol RUN, or a MANUAL STIMULUS ON/OFF-Hz
// command - and restarts at 0 the next time one starts. Independent of
// runFlag (which is protocol-specific) since MANUAL mode has no protocol.
volatile boolean timestampSessionActive = false;
volatile uint32_t timestampSessionStartMicros = 0;

// ==================================
//  === S T O P   P R O T O C O L ===
//  =================================

void stopProtocol(void) {
  tft.println("Stopped");
  runFlag = false;
  timestampSessionActive = false;
  // end all timers
  pulseTimer.end();
  runTimer.end();
  frequencyTimer.end();
  digitalWriteFast(pulsePin, LOW);  // turn off pulse
  Serial.println("DONE");
}

// =====================================================
//  ===  P U L S E    F R E Q U E N C Y   T I M E R  ===
//  ====================================================

// time to send another pulse

void frequencyInterrupt() {
  digitalWriteFast(pulsePin, HIGH);  // turn on pulse
  pulseTimer.begin(pulseInterrupt, pulseOnUsecs);
}


// ===============================
//  === P U L S E   T I M E R  ===
//  ==============================

void pulseInterrupt() {
  digitalWriteFast(pulsePin, LOW);  // end pulse
  pulseTimer.end();
}

// ============================
//  === R U N    T I M E R  ===
//  ===========================

volatile uint32_t runTime = 0;

// Runs every 1 msec while a protocol is active. Kept deliberately lightweight:
// starting a PULSE step needs to allocate/re-arm hardware timers, and reaching
// the end of the protocol needs to print "DONE" over Serial - neither of those
// is safe to do from inside this ISR (see VERSION changelog), so both are just
// flagged here and actually performed from loop().
void runInterrupt() {
  runTime++;
  if (outList[outIndex].start <= runTime)  // time for this output  to do its thing
  {
    if (outList[outIndex].type == PULSE_TYPE) {
      pendingPulsePin = outList[outIndex].pin;
      pendingPulseOnUsecs = outList[outIndex].width * 1000;
      pendingPulseFrequency = outList[outIndex].frequency;
      pulseStartPending = true;  // loop() will start the pulse train
                                 //         tft.print(".");
    } else if (outList[outIndex].type == ON_TYPE) {
      // stop any pulse train left running from a preceding PULSE step on
      // this pin - otherwise its pulseInterrupt()/frequencyInterrupt()
      // would still fire later and turn the pin back off, even though
      // this step means "stay on continuously". Needed now that a single
      // STIMULUS-only protocol can mix PULSE and continuous-ON steps
      // back to back (previously ON/PULSE were normally different
      // outputs - STIMULUS vs VALVE - so this never came up).
      if (outList[outIndex].pin == pulsePin) {
        frequencyTimer.end();
        pulseTimer.end();
        pulsePin = 0;
      }
      digitalWriteFast(outList[outIndex].pin, HIGH);
      //          tft.print("ON  ");
    } else if (outList[outIndex].type == OFF_TYPE) {
      digitalWriteFast(outList[outIndex].pin, LOW);
      if (outList[outIndex].pin == pulsePin)  // if so, then thisi was a pulse function
      {
        frequencyTimer.end();
        pulseTimer.end();
        pulsePin = 0;
      }
      //          tft.print("off ");
    }
    outIndex++;                                                          // point to the next piece of the protocol
    if (outList[outIndex].type == END_TYPE) protocolStopPending = true;  // loop() will call stopProtocol()
  }
}

// Starts the pulse train requested by runInterrupt(). Runs from loop(), i.e.
// normal foreground code - exactly like MANUAL mode already does - so it is
// safe to allocate/re-arm the pulseTimer and frequencyTimer here.
void startPendingPulse(void) {
  noInterrupts();
  int pin = pendingPulsePin;
  uint32_t onUsecs = pendingPulseOnUsecs;
  uint16_t frequency = pendingPulseFrequency;
  pulseStartPending = false;
  interrupts();

  pulsePin = pin;
  digitalWriteFast(pulsePin, HIGH);
  pulseOnUsecs = onUsecs;
  pulseTimer.begin(pulseInterrupt, pulseOnUsecs);
  if (frequency > 0)  // guard against divide-by-zero; pulseCmd() already rejects this, kept here as a backstop
  {
    frequencyTimer.begin(frequencyInterrupt, 1e6 / frequency);
  }
}


// ==========================
// === R U N   C M D ====
// ==========================


void runCmd(int arg_cnt, char **args) {
  runFlag = true;
  timestampSessionActive = true;
  timestampSessionStartMicros = micros();  // t=0 reference for logged sample timestamps
  tft.println("Started");
  outIndex = 0;
  runTime = 0;
  runTimer.begin(runInterrupt, 1000);
}

// =========================
// === S T O P    C M D ====
// =========================

void stopCmd(int arg_cnt, char **args) {
  stopProtocol();
}

// ==========================
// === C L E A R   C M D ====
// ==========================

void clearCmd(int arg_cnt, char **args) {
  outIndex = 0;
  outList[outIndex].type = END_TYPE;
  tft.fillScreen(ILI9341_BLACK);
  tft.setCursor(0, 0);
}

// ==========================
// === P U L S E   C M D ====
// ==========================

// pulse command is:
//  PULSE OUTPUT START WIDTH FREQUENCY
//      OUTPUT is what is being controlled (valve, stmulus)
//      START is start time in milliseconds
//      WIDTH is pulse width in msecs
//      FREQUENCY is pulse rep rate in Hz


void pulseCmd(int arg_cnt, char **args) {

  if (arg_cnt >= 4)  // arg 0 = cmd,
  {
    int pin;

    if (strcmp(args[1], "STIMULUS") == 0) {
      pin = STIMULUS_PIN;
    } else if (strcmp(args[1], "VALVE") == 0) {
      pin = VALVE_PIN;
    } else
      return;

    uint32_t start = cmdStr2Num(args[2], 10);
    uint32_t width = cmdStr2Num(args[3], 10);
    uint16_t frequency = cmdStr2Num(args[4], 10);

    // validate BEFORE touching outList[outIndex]: previously the type/pin/etc
    // were written first and this check could reject the line afterward,
    // leaving outIndex unmoved and a half-written PULSE_TYPE entry behind.
    if (frequency == 0) return;              // avoid divide-by-zero; a 0 Hz pulse train is meaningless
    if ((1000 / frequency) < width) return;  // can't have width greater than rep rate

    outList[outIndex].type = PULSE_TYPE;
    outList[outIndex].pin = pin;
    outList[outIndex].start = start;
    outList[outIndex].width = width;
    outList[outIndex].frequency = frequency;

    tft.print("PLS ");
    tft.print(outList[outIndex].start);
    tft.print(" ");
    tft.print(outList[outIndex].pin);
    tft.print(" ");
    tft.print(outList[outIndex].width);
    tft.print(" ");
    tft.println(outList[outIndex].frequency);

    outIndex++;  // point to next line in protocol

    outList[outIndex].type = END_TYPE;  // move end out one more line
  }
}

// ==========================
// === O N   C M D ====
// ==========================

// on command is:
//  ON OUTPUT START
//      OUTPUT is what is being controlled (valve, stmulus)
//      START is start time in milliseconds

void onCmd(int arg_cnt, char **args) {

  if (arg_cnt >= 2)  // arg 0 = cmd,
  {
    outList[outIndex].type = ON_TYPE;

    if (strcmp(args[1], "STIMULUS") == 0)
      outList[outIndex].pin = STIMULUS_PIN;
    else if (strcmp(args[1], "VALVE") == 0)
      outList[outIndex].pin = VALVE_PIN;
    else
      return;

    outList[outIndex].start = cmdStr2Num(args[2], 10);

    tft.print("ON  ");
    tft.print(outList[outIndex].start);
    tft.print(" ");
    tft.println(outList[outIndex].pin);

    outIndex++;  // point to next line in protocol

    outList[outIndex].type = END_TYPE;  // move end out one more line
  }
}


// ======================
// === O F F   C M D ====
// ======================

// off command is:
//  OFF OUTPUT START
//      OUTPUT is what is being controlled (valve, stmulus)
//      START is start time in milliseconds

void offCmd(int arg_cnt, char **args) {

  if (arg_cnt >= 2)  // arg 0 = cmd,
  {
    outList[outIndex].type = OFF_TYPE;

    if (strcmp(args[1], "STIMULUS") == 0)
      outList[outIndex].pin = STIMULUS_PIN;
    else if (strcmp(args[1], "VALVE") == 0)
      outList[outIndex].pin = VALVE_PIN;
    else
      return;

    outList[outIndex].start = cmdStr2Num(args[2], 10);

    tft.print("OFF ");
    tft.print(outList[outIndex].start);
    tft.print(" ");
    tft.println(outList[outIndex].pin);

    outIndex++;  // point to next line in protocol

    outList[outIndex].type = END_TYPE;  // move end out one more line
  }
}

// ===========================
// === M A N U A L  C M D ====
// ===========================

// manual command is:
//  MANUAL OUTPUT ON/OFF
//      OUTPUT is what is being controlled (valve, stmulus)
//      ON/OFF is on or off

void manualCmd(int arg_cnt, char **args) {

  if (arg_cnt >= 2)  // arg 0 = cmd, 1 = function, 2 = on/off
  {
    if (strcmp(args[1], "STIMULUS") == 0) {
      if (strcmp(args[2], "ON") == 0) {
        digitalWriteFast(STIMULUS_PIN, HIGH);
        timestampSessionActive = true;
        timestampSessionStartMicros = micros();
        tft.println("Stimulus ON");
      } else if (strcmp(args[2], "OFF") == 0) {
        digitalWriteFast(STIMULUS_PIN, LOW);
        timestampSessionActive = false;
        tft.println("Stimulus OFF");
        pulseTimer.end();
        frequencyTimer.end();
      } else  //args[2] is a value between 0 and 500Hz
      {
        int manualFreq = atoi(args[2]);

        // stop any pulse train from a previous MANUAL command before
        // (re)starting - otherwise a stale frequencyTimer could still be
        // running underneath whatever we do below.
        pulseTimer.end();
        frequencyTimer.end();
        pulsePin = STIMULUS_PIN;
        timestampSessionActive = true;
        timestampSessionStartMicros = micros();

        if (manualFreq <= 0) {
          // 0 Hz is the limit of a pulse train as its period -> infinity,
          // i.e. the pin just stays on - same as MANUAL STIMULUS ON.
          digitalWriteFast(STIMULUS_PIN, HIGH);
          tft.println("Stimulus ON (0Hz)");
        } else {
          digitalWriteFast(pulsePin, HIGH);
          pulseOnUsecs = 1000;
          pulseTimer.begin(pulseInterrupt, pulseOnUsecs);
          int temp = 1e6 / manualFreq;
          frequencyTimer.begin(frequencyInterrupt, temp);
          tft.print("Stimulus ");
          tft.print(args[2]);
          tft.print("Hz");
          tft.println();
        }
      }
    }

    else if (strcmp(args[1], "VALVE") == 0) {
      if (strcmp(args[2], "ON") == 0) {
        digitalWriteFast(VALVE_PIN, HIGH);
        tft.println("Valve ON");
      } else {
        digitalWriteFast(VALVE_PIN, LOW);
        tft.println("Valve OFF");
      }
    } else
      return;
  }
}


// =========================
// === C M D   H E L P  ====
// =========================

void cmdHelp(int arg_cnt, char **args) {
  tft.println("HELP");

  Serial.print("Version:");
  Serial.println(VERSION);
  cmdList();
}

// ===========================================
//  ===  A N A L O G    I N T E R R U P T  ===
//  ==========================================

// circuit is 5V/AMP with 1.2V output offset
// 5mV / mA
// ADC is 13 bits
// ((ain-offset) * 3.3 / 2^13 ) * 1000 / 5

volatile static int16_t ain;
//volatile static int16_t abuff[2][64];
volatile static int ch = 0;
volatile static int idx = 0;
volatile static int sendFlag = -1;


// Runs every SAMPLE_TIME usecs (250 usec = 4 kHz). Only samples the ADCs and
// flags the result; the actual Serial.println() happens in loop(). Serial I/O
// can block waiting on the USB buffer, which is not safe to do from an ISR -
// see VERSION changelog for how that interacted badly with protocol mode.
void analogInterrupt() {
  
  current = analogRead(A0);
  voltage = analogRead(A6);
  //voltage = analogRead(VIN_PIN);

  //fcurrent = ((float)current * 0.0133) - 3.5382;
  fcurrent = ((float)current * 0.028) - 114.94;
  fvoltage = ((float)voltage * 0.0112) - 45.939;

  //ain = (int16_t)(((float)(analogRead(A0) - ZERO_OFFSET)) * 0.080566);
  //int16_t vin = (int16_t)((float)analogRead(VIN_PIN) * VIN_MV_PER_COUNT);
  //ainValue = fcurrent;
  //vinValue = fvoltage;
  // unsigned subtraction wraps correctly even across a micros() rollover
  ainElapsedUsValue = timestampSessionActive ? (micros() - timestampSessionStartMicros) : 0;
  ainReady = true;

  //    abuff[ch][idx] =
  //    idx++;
  //    if( idx == 64 )
  //    {
  //       sendFlag = ch;
  //       if( ch == 1)
  //          ch = 0;
  //       else
  //          ch = 1;
  //    }
}


// ====================
//  ===  S E T U P  ===
//  ===================
void setup() {
  bcs.begin();  // set up miniBCS hardwware


  //    Serial.print("Perfusion Control - V:");
  //    Serial.println(VERSION);

  pinMode(STIMULUS_PIN, OUTPUT);
  digitalWriteFast(STIMULUS_PIN, LOW);
  pinMode(VALVE_PIN, OUTPUT);
  bcs.driverOff(1);

  analogReadResolution(13);
  analogReadAveraging(4);

  // basic display setups
  tft.begin();         // start up display
  tft.setRotation(1);  // rotate 180 for miniBCS mechanical attachment
  tft.fillScreen(ILI9341_BLACK);
  tft.setTextColor(ILI9341_YELLOW);
  tft.setTextSize(2);
  tft.println("      Perfusion Control");
  tft.print("      VERSION: ");
  tft.println(VERSION);
  tft.println();
  tft.println();
  tft.println("Waiting on Host");

  // set up command port and list
  Serial.begin(115200);  // USB serial startup
  while (!Serial)
    ;

  tft.print("Connected");

  // touchscreen
  //    ts.begin();
  // Serial.println( ts.bufferSize());
  //    ts.setRotation(3);

  // The cmd.h library is used to set up and parse commands and parameters
  cmdInit(&Serial);  // set up for command parsing
  // add commands
  cmdAdd("CLEAR", clearCmd);
  cmdAdd("PULSE", pulseCmd);
  cmdAdd("ON", onCmd);
  cmdAdd("OFF", offCmd);
  cmdAdd("RUN", runCmd);
  cmdAdd("STOP", stopCmd);
  cmdAdd("MANUAL", manualCmd);
  cmdAdd("???", cmdHelp);

  isp = instr;

  outList[0].type = END_TYPE;

  //  bcs.driverOn(1);


  //   digitalWriteFast(VALVE_PIN , HIGH);
  //    for( int i = 0; i < 10; i++)
  //    {
  //       digitalWriteFast( STIMULUS_PIN, HIGH);
  //       delay(500);
  //       digitalWriteFast( STIMULUS_PIN, LOW);
  //       delay(500);
  //    }
  //     digitalWriteFast(VALVE_PIN , LOW);

  //   bcs.driverOff(1);
  
  analogTimer.begin(analogInterrupt, SAMPLE_TIME);  // analog sampling
  //analogTimer.begin(analogInterrupt, 1000000);  // analog sampling
}

int32_t pos = 0;
int32_t oldpos = 0;

boolean wastouched = true;

int16_t vave;
int16_t iave;


// ===========================
//  ===  M A I N  L O O P  ===
//  ==========================
void loop() {
  // boolean istouched = ts.touched();
  //  if (istouched)
  //  {
  //    TS_Point p = ts.getPoint();
  //    Serial.print("Pressure = ");
  //    Serial.print(p.z);
  //    Serial.print(", x = ");
  //    Serial.print(p.x);
  //    Serial.print(", y = ");
  //    Serial.print(p.y);
  //    delay(30);
  //    Serial.println();
  //    tft.setCursor(60, 80);
  //    tft.print("touch: ");
  //    tft.fillRect(140,80, 120, 100, ILI9341_BLACK);
  //    tft.setCursor(140, 80);
  //    tft.print(p.x);
  //    tft.print(",");
  //    tft.print(p.y);
  //  }

  //  while( Serial.available() )
  //  {
  //      tft.print( Serial.read() );
  //      tft.print(" ");
  //  }

  //if (sendFlag >= 0) {
  //  noInterrupts();
  //  int ch = sendFlag;
  //  sendFlag = -1;
  //  interrupts();
  //  Serial.write((byte *)&abuff[ch][0], 128);
  //}

  if (ainReady) {
    noInterrupts();
    float v = fcurrent;
    float vinV = fvoltage;
    uint32_t elapsedUs = ainElapsedUsValue;
    ainReady = false;
    interrupts();

    // Wire format the Python GUI's parser expects: "<current>,<voltage>,<elapsed_us>"
    // (comma-separated, calibrated values) - see ProtocolCodec.parse_stream_text().

    #ifdef DEBUG
      
      vave = (vave + vave + vave + voltage) / 4;
      iave = (iave + iave + iave + current) / 4;
      Serial.print(vave);
      Serial.print('\t');
      Serial.println(iave);
    #else
      Serial.print(v);
      Serial.print(",");
      Serial.print(vinV);
      Serial.print(",");
      Serial.println(elapsedUs);
    #endif  
  }

  if (pulseStartPending) {
    startPendingPulse();
  }

  if (protocolStopPending) {
    protocolStopPending = false;
    stopProtocol();
  }

  cmdPoll();  // look for commands
}
