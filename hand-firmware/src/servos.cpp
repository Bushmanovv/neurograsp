// =============================================================================
//  servos.cpp — Layer 1 servo core.
//  Direct ESP32 GPIO PWM via ESP32Servo (no PCA9685), smooth non-blocking
//  interpolation, and the built-in actions.
//
//  Thread-safety: the interpolation arrays are read by servosUpdate() on the
//  loop task and written by servoSetTarget()/servosSetTargets() from BOTH the
//  loop task (UART cues) and the async web task. Every access is under
//  StateLock (see sync.h). The actual PWM hardware write happens only in
//  servosUpdate() on the loop task.
// =============================================================================

#include "servos.h"

#include <ESP32Servo.h>

#include "contracts.h"
#include "sync.h"

static Servo servos[SERVO_COUNT];
static bool  hwPresent = false;

// GPIO per channel, canonical order (thumb, index, middle, ring, pinky, wrist).
static const uint8_t SERVO_PINS[SERVO_COUNT] = {
    SERVO_PIN_THUMB, SERVO_PIN_INDEX, SERVO_PIN_MIDDLE,
    SERVO_PIN_RING,  SERVO_PIN_PINKY, SERVO_PIN_WRIST,
};

// Per-channel pulse limits (microseconds). TIGHTEN each entry on the bench so
// a finger/wrist physically cannot be driven past its safe travel.
static const uint16_t PULSE_MIN_US[SERVO_COUNT] = {
    SERVO_PULSE_MIN_US, SERVO_PULSE_MIN_US, SERVO_PULSE_MIN_US,
    SERVO_PULSE_MIN_US, SERVO_PULSE_MIN_US, SERVO_PULSE_MIN_US,
};
static const uint16_t PULSE_MAX_US[SERVO_COUNT] = {
    SERVO_PULSE_MAX_US, SERVO_PULSE_MAX_US, SERVO_PULSE_MAX_US,
    SERVO_PULSE_MAX_US, SERVO_PULSE_MAX_US, SERVO_PULSE_MAX_US,
};

// Built-in actions (Contract B). MUST stay in sync with ACTION_ANGLES in
// data/app.js so the on-screen hand and the physical hand agree.
// NOTE: wrist_left / wrist_right are NOT in this table — they HOLD the current
// finger angles and only rotate the wrist, so they're synthesized on demand in
// builtinActionAngles() from the live position.
struct BuiltinAction { const char* name; uint8_t angles[SERVO_COUNT]; };
static const BuiltinAction BUILTIN_TABLE[] = {
    { "open_hand",   {   0,   0,   0,   0,   0, WRIST_ANGLE_NEUTRAL } },
    { "close_fist",  { 180, 180, 180, 180, 180, WRIST_ANGLE_NEUTRAL } },
    { "point",       { 180,   0, 180, 180, 180, WRIST_ANGLE_NEUTRAL } },
    { "pinch",       { 130, 130,   0,   0,   0, WRIST_ANGLE_NEUTRAL } },
    { "relax",       {  20,  20,  20,  20,  20, WRIST_ANGLE_NEUTRAL } },
};

// Interpolation state: each channel eases start→target over MOVE_DURATION_MS.
// Initial position = HOME (open hand, wrist neutral) — the hand resets to this
// on power-on. Guarded by StateLock.
static uint8_t  curAngle[SERVO_COUNT]   = { 0, 0, 0, 0, 0, WRIST_ANGLE_NEUTRAL };
static uint8_t  startAngle[SERVO_COUNT] = { 0, 0, 0, 0, 0, WRIST_ANGLE_NEUTRAL };
static uint8_t  tgtAngle[SERVO_COUNT]   = { 0, 0, 0, 0, 0, WRIST_ANGLE_NEUTRAL };
static uint32_t moveStart[SERVO_COUNT]  = { 0 };
static uint32_t lastStepMs = 0;

// Drive one channel to a logical angle. ESP32Servo::write() maps 0..180 onto the
// channel's attach() min/max microseconds. Loop task only.
static void writeChannel(uint8_t ch, uint8_t angle) {
    if (!hwPresent) return;
    servos[ch].write(angle);
}

bool servosBegin() {
    // ESP32Servo shares the ESP32 LEDC timers; reserve them so nothing else
    // (tone(), analogWrite()) steals a timer out from under the servos.
    ESP32PWM::allocateTimer(0);
    ESP32PWM::allocateTimer(1);
    ESP32PWM::allocateTimer(2);
    ESP32PWM::allocateTimer(3);

    hwPresent = true;
    for (uint8_t ch = 0; ch < SERVO_COUNT; ch++) {
        servos[ch].setPeriodHertz(SERVO_PWM_FREQ_HZ);
        servos[ch].attach(SERVO_PINS[ch], PULSE_MIN_US[ch], PULSE_MAX_US[ch]);
        if (!servos[ch].attached()) hwPresent = false;
    }

    if (hwPresent) {
        for (uint8_t ch = 0; ch < SERVO_COUNT; ch++) writeChannel(ch, curAngle[ch]);
        Serial.println("[SERVO] ESP32Servo attached on 6 GPIOs, hand homed (open, wrist neutral)");
    } else {
        // Angles are still tracked so the web app works on a bench with nothing
        // wired; we just can't drive real PWM.
        Serial.println("[SERVO] WARNING: could not attach all servos — running without servo HW");
    }
    return hwPresent;
}

void servoSetTarget(uint8_t ch, int angle) {
    if (ch >= SERVO_COUNT) return;
    angle = constrain(angle, SERVO_ANGLE_MIN, SERVO_ANGLE_MAX);
    StateLock lk;
    startAngle[ch] = curAngle[ch];
    tgtAngle[ch]   = (uint8_t)angle;
    moveStart[ch]  = millis();
}

void servosSetTargets(const uint8_t angles[SERVO_COUNT]) {
    for (uint8_t ch = 0; ch < SERVO_COUNT; ch++) servoSetTarget(ch, angles[ch]);
}

void servosUpdate() {
    const uint32_t now = millis();
    if (now - lastStepMs < MOVE_STEP_MS) return;
    lastStepMs = now;

    StateLock lk;
    for (uint8_t ch = 0; ch < SERVO_COUNT; ch++) {
        if (curAngle[ch] == tgtAngle[ch]) continue;
        const uint32_t elapsed = now - moveStart[ch];
        uint8_t next;
        if (elapsed >= MOVE_DURATION_MS) {
            next = tgtAngle[ch];
        } else {
            const float t = (float)elapsed / MOVE_DURATION_MS;
            next = (uint8_t)(startAngle[ch] + (tgtAngle[ch] - startAngle[ch]) * t);
        }
        if (next != curAngle[ch]) {
            curAngle[ch] = next;
            writeChannel(ch, next);
        }
    }
}

const uint8_t* servosCurrent() { return curAngle; }

const uint8_t* builtinActionAngles(const char* name) {
    if (!name) return nullptr;

    // wrist_left / wrist_right: hold the live finger angles, rotate only the
    // wrist. Synthesized into a static buffer from the current position.
    const bool wl = (strcmp(name, "wrist_left")  == 0);
    const bool wr = (strcmp(name, "wrist_right") == 0);
    if (wl || wr) {
        static uint8_t buf[SERVO_COUNT];
        StateLock lk;
        memcpy(buf, curAngle, SERVO_COUNT);
        buf[CH_WRIST] = wl ? WRIST_ANGLE_LEFT : WRIST_ANGLE_RIGHT;
        return buf;
    }

    for (const auto& a : BUILTIN_TABLE)
        if (strcmp(name, a.name) == 0) return a.angles;
    return nullptr;
}
