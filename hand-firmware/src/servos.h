#pragma once
// =============================================================================
//  servos.h — Layer 1 servo core.
//  Direct ESP32 GPIO PWM (ESP32Servo) + smooth (non-blocking) interpolation +
//  built-in actions. All angles are LOGICAL degrees 0..180 in the canonical
//  channel order (thumb, index, middle, ring, pinky, wrist) — see config.h.
// =============================================================================

#include <Arduino.h>
#include "config.h"

// Attach the 6 servos and drive the hand to "relax". Returns false if any pin
// could not be attached (firmware keeps running: angles are still tracked so
// the web app works on a bench with nothing wired).
bool servosBegin();

// Step the interpolation; call every loop() pass. Cheap when idle.
void servosUpdate();

// Set targets (smoothly interpolated over MOVE_DURATION_MS).
void servoSetTarget(uint8_t channel, int angle);
void servosSetTargets(const uint8_t angles[SERVO_COUNT]);

// Current logical angles (what the fingers are doing right now).
const uint8_t* servosCurrent();

// Look up a built-in action ("open_hand"...) → its angles, or nullptr.
const uint8_t* builtinActionAngles(const char* name);
