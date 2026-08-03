#pragma once
// =============================================================================
//  dispatch.h — the one place an "action" (built-in or saved pose) turns into
//  servo targets + a status update. Used by the UART link AND the web API so
//  the two paths can never disagree.
// =============================================================================

#include "status.h"

// Resolve `action` (built-in name or saved-pose name) and drive the hand.
// Returns false if the action is unknown. `source` records who asked.
bool applyAction(const char* action, CmdSource source);

// Contract A entry point: a validated label arrived from the Pi.
// Looks up the mapping and applies it; refreshes the fail-safe clock.
void applyLabel(const char* label);
