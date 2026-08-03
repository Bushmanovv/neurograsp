#pragma once
// =============================================================================
//  config.h  —  EVERY hardware + system tunable lives here.
//  EEG-controlled InMoov prosthetic hand — ESP32 firmware.
//
//  Everything below is either an ASSUMPTION about your wiring or a value you
//  will calibrate on the bench. Each is a #define so you can tune it without
//  digging through the logic. Where I guessed, the comment says "ASSUMPTION".
//  Correct anything that doesn't match your build.
// =============================================================================

// ---------------------------------------------------------------------------
//  FIRMWARE
// ---------------------------------------------------------------------------
#define FW_VERSION              "0.5.0-layer4"

// ---------------------------------------------------------------------------
//  SERVO DRIVE  —  direct ESP32 GPIO PWM via the ESP32Servo library.
//  NO PCA9685. Each servo signal wire goes straight to one ESP32 GPIO; the
//  servos are powered from an EXTERNAL supply (not the ESP32's regulator) with
//  a common ground back to the ESP32.
// ---------------------------------------------------------------------------
#define SERVO_PWM_FREQ_HZ       50          // analog hobby servos want ~50 Hz

// ---------------------------------------------------------------------------
//  SERVO CHANNEL MAP  (which ESP32 GPIO drives which joint)
//  6 servos total: 5 fingers on channels 0..4, wrist rotation on channel 5.
//  This is the canonical order for every angles[6] array in the API & poses.
//  Pins per the bench wiring: thumb 13, index 14, middle 25, ring 26,
//  pinky 27, wrist 33 (all output-capable; GPIO34 stays free for the battery ADC).
// ---------------------------------------------------------------------------
#define SERVO_COUNT             6
#define CH_THUMB                0
#define CH_INDEX                1
#define CH_MIDDLE               2
#define CH_RING                 3
#define CH_PINKY                4
#define CH_WRIST                5

#define SERVO_PIN_THUMB         13
#define SERVO_PIN_INDEX         14
#define SERVO_PIN_MIDDLE        25
#define SERVO_PIN_RING          26
#define SERVO_PIN_PINKY         27
#define SERVO_PIN_WRIST         33

// ---------------------------------------------------------------------------
//  SERVO PULSE LIMITS  (microseconds — ESP32Servo attach() min/max)
//  A logical 0 deg maps to SERVO_PULSE_MIN_US, 180 deg to SERVO_PULSE_MAX_US.
//  500..2500 us suits most MG996R-class servos; TIGHTEN per channel (arrays in
//  the Layer-1 servo module) so a finger/wrist physically cannot be driven past
//  its safe travel.
// ---------------------------------------------------------------------------
#define SERVO_PULSE_MIN_US      500         // logical "0 deg" end
#define SERVO_PULSE_MAX_US      2500        // logical "180 deg" end

// Logical angle range used by the UI, poses, and API (degrees).
#define SERVO_ANGLE_MIN         0
#define SERVO_ANGLE_MAX         180

// Wrist (channel 5) rotation. NEUTRAL (hand straight) is the centre used by
// every non-wrist gesture. On this build the servo spans 0..180 with neutral
// near the low end: wrist_right rotates toward 0, wrist_left toward 180.
// wrist_left / wrist_right HOLD the finger angles and only turn the wrist.
#define WRIST_ANGLE_NEUTRAL     40
#define WRIST_ANGLE_LEFT        180         // 40 -> 180
#define WRIST_ANGLE_RIGHT       0           // 40 -> 0

// ---------------------------------------------------------------------------
//  SMOOTH MOVEMENT  (don't snap servos — protect cables/gears)
// ---------------------------------------------------------------------------
#define MOVE_DURATION_MS        400         // interpolate to a target over this
#define MOVE_STEP_MS            15          // interpolation update interval

// ---------------------------------------------------------------------------
//  UART  —  Link A: Raspberry Pi 5 -> ESP32  (Contract A, see CONTRACTS.md)
//  The Pi sends one label per line, newline-terminated. Two ways to carry it:
//
//  UART_USE_USB 1  (default) — a single USB cable, Pi USB port -> ESP32 USB.
//      The board's USB-serial bridge IS Serial (UART0), so the labels arrive
//      there. One locked connector carries data, ground and the ESP32's power:
//      nothing to fall out of a hand that gets picked up, and the "is the
//      ground common?" question disappears. On the Pi this is /dev/ttyUSB0.
//      Cost: opening the port toggles DTR/RTS, so the ESP32 reboots once when
//      the Pi's service starts. Harmless — it just re-homes the hand.
//
//  UART_USE_USB 0 — the original three jumpers on Serial2:
//      Pi TX (hdr pin 8) -> GPIO16, Pi RX (hdr pin 10) <- GPIO17, common GND.
//      On the Pi this is /dev/ttyAMA0 (NOT /dev/serial0 — that is the Pi 5's
//      debug connector).
// ---------------------------------------------------------------------------
#define UART_USE_USB            1

#define UART_RX_PIN             16          // ESP32 Serial2 RX  <- Pi TX  (USB=0 only)
#define UART_TX_PIN             17          // ESP32 Serial2 TX  -> Pi RX  (USB=0 only)
#define UART_BAUD               115200
#define UART_LINE_MAX           64          // max label line length (bytes)

// ---------------------------------------------------------------------------
//  FAIL-SAFE
//  If no VALID label arrives within this window, HOLD the current position
//  (do NOT go limp, do NOT snap to a default). UI also exposes a relax button.
// ---------------------------------------------------------------------------
#define FAILSAFE_TIMEOUT_MS     3000        // default 3 s

// ---------------------------------------------------------------------------
//  BATTERY MONITOR  (battery -> voltage divider -> ESP32 ADC)
//  ASSUMPTION: 2S LiPo (~6.4–8.4 V) and a divider that keeps the ADC < 3.3 V.
//  Example divider R1=100k (top), R2=33k (bottom): ratio = (R1+R2)/R2 ≈ 4.03,
//  so 8.4 V -> ~2.08 V at the ADC. CALIBRATE the ratio + full/empty against a
//  multimeter; ESP32 ADCs are not very linear.
// ---------------------------------------------------------------------------
#define BATT_ADC_PIN            34          // input-only ADC1 pin (safe choice)
#define BATT_DIVIDER_RATIO      4.03f       // Vbattery = Vadc * ratio
#define BATT_ADC_VREF           3.30f       // ADC full-scale voltage (approx)
#define BATT_ADC_MAX            4095.0f     // 12-bit ADC
#define BATT_VOLT_FULL          8.40f       // -> 100%  (2S LiPo charged)
#define BATT_VOLT_EMPTY         6.40f       // ->   0%  (2S LiPo cutoff: protect cells!)

// ---------------------------------------------------------------------------
//  WiFi ACCESS POINT  —  Link B. The phone joins THIS network. No internet:
//  every asset MUST be served locally from LittleFS (no CDNs anywhere).
// ---------------------------------------------------------------------------
#define AP_SSID                 "ProstheticHand"
#define AP_PASSWORD             "inmoov1234"  // >= 8 chars, or "" for an open AP
#define AP_CHANNEL              6
#define AP_MAX_CLIENTS          4

// ---------------------------------------------------------------------------
//  WEBSOCKET TELEMETRY  (Layer 2+)  — push live status to the dashboard.
// ---------------------------------------------------------------------------
#define WS_PUSH_INTERVAL_MS     150         // ~6–7 Hz

// ---------------------------------------------------------------------------
//  LittleFS PATHS  (source of truth for mappings + poses; survive power cycle)
// ---------------------------------------------------------------------------
#define PATH_MAPPINGS           "/mappings.json"
#define PATH_POSES              "/poses.json"
