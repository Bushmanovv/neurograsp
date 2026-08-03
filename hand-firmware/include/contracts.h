#pragma once
// =============================================================================
//  contracts.h  —  the two system contracts, expressed in code so they cannot
//  silently drift from the documentation in CONTRACTS.md.
//
//  Contract A: the labels the Raspberry Pi may send over UART.
//  Contract B: the built-in actions a label can be mapped to (a mapping value
//              is EITHER one of these strings OR the name of a saved pose).
//
//  Both lists are intentionally editable — add/remove entries here as your EEG
//  classifier and gesture set evolve.
// =============================================================================

#include <stddef.h>
#include <string.h>

// ---- Contract A: valid UART labels (Pi -> ESP32) --------------------------
// One label per line, newline-terminated, lower_snake_case. Unknown labels are
// logged and ignored by the firmware.
static const char* const VALID_LABELS[] = {
    "single_blink",
    "double_blink",
    "clinch",           // canonical: matches the Pi classifier's output
    "bruxism_left",
    "bruxism_right",
    "rest"
};

// `rest` is the Pi's link HEARTBEAT, not a gesture. The Pi resends it every
// REST_HEARTBEAT_SEC (1.2 s) whenever it has nothing to report, purely so this
// firmware's 3 s fail-safe does not trip. It means "the link is alive", NOT
// "move the hand" -- see applyLabel() in dispatch.cpp.
static const char* const REST_LABEL = "rest";
static const size_t VALID_LABELS_COUNT =
    sizeof(VALID_LABELS) / sizeof(VALID_LABELS[0]);

// ---- Built-in actions (code-implemented gestures) -------------------------
// A mapping value is valid if it is one of these OR matches a saved pose name.
static const char* const BUILTIN_ACTIONS[] = {
    "open_hand",
    "close_fist",
    "point",
    "pinch",
    "wrist_left",
    "wrist_right",
    "relax"
};
static const size_t BUILTIN_ACTIONS_COUNT =
    sizeof(BUILTIN_ACTIONS) / sizeof(BUILTIN_ACTIONS[0]);

// Convenience: is `s` a known label / built-in action?
static inline bool isValidLabel(const char* s) {
    for (size_t i = 0; i < VALID_LABELS_COUNT; i++)
        if (strcmp(s, VALID_LABELS[i]) == 0) return true;
    return false;
}
static inline bool isBuiltinAction(const char* s) {
    for (size_t i = 0; i < BUILTIN_ACTIONS_COUNT; i++)
        if (strcmp(s, BUILTIN_ACTIONS[i]) == 0) return true;
    return false;
}
