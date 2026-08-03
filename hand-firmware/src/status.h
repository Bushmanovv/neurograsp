#pragma once
// =============================================================================
//  status.h — the single shared "system status" snapshot.
//  Every module writes its slice; the web layer serializes it for /api/state
//  and the /ws telemetry push (Contract B: Status).
// =============================================================================

#include <Arduino.h>
#include "config.h"

// Who last commanded the hand — shown on the dashboard.
enum class CmdSource : uint8_t { None, Cue, Manual };

struct SystemStatus {
    float     batteryV        = 0.0f;
    int       batteryPct      = 0;
    bool      linkAConnected  = false;     // valid label within FAILSAFE_TIMEOUT_MS
    char      lastLabel[UART_LINE_MAX] = "";
    char      lastAction[32]  = "";        // what lastLabel resolved to
    char      activePose[32]  = "";        // "" = none / built-in
    CmdSource source          = CmdSource::None;
    uint32_t  lastLabelMs     = 0;         // millis() of last VALID label
};

extern SystemStatus g_status;

inline const char* cmdSourceName(CmdSource s) {
    switch (s) {
        case CmdSource::Cue:    return "cue";
        case CmdSource::Manual: return "manual";
        default:                return "";
    }
}
